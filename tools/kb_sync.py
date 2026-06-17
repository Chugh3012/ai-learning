#!/usr/bin/env python3
"""Owned knowledge-base sync — the orchestrator. Reads config/sources.opml (feedparser),
dedupes into the SQLite KB, optionally ranks/embeds/drafts/delivers per the flags, and backs
up to Azure Blob. The KB schema is generic (see SCHEMA) so new signal kinds need no migration.
Passwordless (DefaultAzureCredential). Run `python tools/kb_sync.py --help` for flags.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
OPML = ROOT / "config" / "sources.opml"
TAGS = ROOT / "config" / "tags.json"
KB_DIR = ROOT / "data" / "kb"
KB_PATH = KB_DIR / "kb.sqlite"
DRAFTS_DIR = ROOT / "drafts"
DIGESTS_DIR = ROOT / "digests"

SCHEMA = """
CREATE TABLE IF NOT EXISTS source(
  id INTEGER PRIMARY KEY, title TEXT, url TEXT UNIQUE, kind TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS item(
  id INTEGER PRIMARY KEY,
  source_id INTEGER REFERENCES source(id),
  title TEXT, url TEXT, summary TEXT,
  published INTEGER, fetched_at INTEGER, hash TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS tag(
  item_id INTEGER REFERENCES item(id), topic TEXT,
  PRIMARY KEY(item_id, topic));
CREATE TABLE IF NOT EXISTS signal(
  id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES item(id),
  kind TEXT, value REAL, ts INTEGER);
CREATE TABLE IF NOT EXISTS draft(
  id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES item(id) UNIQUE,
  status TEXT, body TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS embedding(
  item_id INTEGER PRIMARY KEY REFERENCES item(id), vec BLOB, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_item_published ON item(published);
"""


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines (ignoring blanks/comments) from a dotenv-style file."""
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def load_env() -> dict[str, str]:
    """Local .env (if present) overlaid by os.environ, limited to keys declared in
    .env.example. The manifest IS the allowlist — adding an integration is a config edit
    there (+ a repo Variable), never a code change here ('growth = config, not code'). The
    allowlist also keeps unrelated CI runner env (tokens etc.) out of the config dict."""
    env = _parse_env_file(ENV)
    keys = set(_parse_env_file(ENV.parent / ".env.example"))
    env.update({k: v for k, v in os.environ.items() if k in keys})
    return env


def read_sources() -> list[dict]:
    tree = ET.parse(OPML)
    out: list[dict] = []
    for cat in tree.getroot().iter("outline"):
        cat_name = cat.get("text", "")
        for child in cat.findall("outline"):
            url = child.get("xmlUrl")
            if url:
                out.append({"title": child.get("text", url), "url": url,
                            "category": cat_name, "fallback": child.get("fallbackUrl", "")})
    return out


def connect() -> sqlite3.Connection:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(KB_PATH)
    con.executescript(SCHEMA)
    _migrate_legacy_signals(con)
    return con


def _migrate_legacy_signals(con: sqlite3.Connection) -> None:
    """One-time, idempotent: the single-user pipeline used global signal kinds (emailed,
    affinity, fb_*). Multi-user namespaces per recipient; attribute the legacy history to
    'primary' so the original user isn't re-sent items or stripped of learned affinity.
    No-op once migrated (no rows match)."""
    con.execute("UPDATE signal SET kind='sent:primary' WHERE kind='emailed'")
    con.execute("UPDATE signal SET kind='affinity:primary' WHERE kind='affinity'")
    con.execute("UPDATE signal SET kind=kind||':primary' "
                "WHERE kind IN ('fb_vote','fb_save','fb_click')")
    con.commit()



def upsert_source(con: sqlite3.Connection, s: dict) -> int:
    con.execute(
        "INSERT INTO source(title,url,kind,category) VALUES(?,?,?,?) "
        "ON CONFLICT(url) DO UPDATE SET title=excluded.title, category=excluded.category",
        (s["title"], s["url"], "feed", s["category"]),
    )
    return con.execute("SELECT id FROM source WHERE url=?", (s["url"],)).fetchone()[0]


def tag_text(text: str, rules: dict[str, list[str]]) -> list[str]:
    low = text.lower()
    return [t for t, kws in rules.items() if any(k in low for k in kws)] or ["other"]


# HTTP statuses worth a retry: rate-limit + transient server errors. 403/404 (blocks/dead feeds)
# are NOT transient and are returned immediately — retrying them just wastes time.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _fetch_feed(url: str, ua: str, attempts: int = 3):
    """Parse a feed, retrying ONLY on transient failures (HTTP 429/5xx, or a connection-level
    error where feedparser sets bozo with no status). Linear backoff, capped. A feed that simply
    returned no entries with an OK/permanent status is returned as-is (no point retrying)."""
    import feedparser  # local import so --help works without the dep
    feed = feedparser.parse(url, agent=ua)
    tries = 1
    while tries < attempts and not feed.entries:
        status = getattr(feed, "status", None)
        transient = status in _RETRY_STATUS or (getattr(feed, "bozo", 0) and status is None)
        if not transient:
            break
        time.sleep(min(1.5 * tries, 5))
        feed = feedparser.parse(url, agent=ua)
        tries += 1
    return feed


def sync(con: sqlite3.Connection, rules: dict) -> tuple[int, int]:
    # Browser-like UA: some hosts (Substack) 403 the default feedparser/bot UA, especially from
    # datacenter IPs. A real UA fixes most such blocks at zero cost.
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0 Safari/537.36")

    def _fetch(url: str):
        return _fetch_feed(url, ua)

    sources = read_sources()
    now = int(time.time())
    new_items = 0
    empty: list[str] = []  # sources that returned no entries (often a CI/IP block — visible in logs)
    for s in sources:
        sid = upsert_source(con, s)
        feed = _fetch(s["url"])
        # Config-driven escape hatch: if the primary feed is empty and a fallbackUrl is set
        # (e.g. an RSSHub route or mirror), try it before giving up.
        if not feed.entries and s.get("fallback"):
            feed = _fetch(s["fallback"])
        if not feed.entries:
            status = getattr(feed, "status", "?")
            empty.append(f"{s['title']} (HTTP {status})")
        for e in feed.entries:
            title = (e.get("title") or "(untitled)").strip()
            url = e.get("link") or ""
            summary = e.get("summary", "")[:2000]
            pp = e.get("published_parsed") or e.get("updated_parsed")
            published = int(time.mktime(pp)) if pp else now
            h = hashlib.sha1(f"{url}|{title}".encode("utf-8", "replace")).hexdigest()
            cur = con.execute(
                "INSERT OR IGNORE INTO item(source_id,title,url,summary,published,fetched_at,hash) "
                "VALUES(?,?,?,?,?,?,?)",
                (sid, title, url, summary, published, now, h),
            )
            if cur.rowcount:
                new_items += 1
                item_id = con.execute("SELECT id FROM item WHERE hash=?", (h,)).fetchone()[0]
                for topic in tag_text(f"{title} {summary}", rules):
                    con.execute("INSERT OR IGNORE INTO tag(item_id,topic) VALUES(?,?)", (item_id, topic))
        con.commit()
    ok = len(sources) - len(empty)
    print(f"fetch: {ok}/{len(sources)} sources returned entries")
    if empty:
        print("fetch: EMPTY (no entries — possible block/dead feed): " + "; ".join(empty))
    total = con.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    return new_items, total


def render_review(con: sqlite3.Connection) -> Path | None:
    """Write pending content drafts to a human-review markdown file. Generic over the
    JSON shape: prints whatever keys each draft profile produced."""
    rows = con.execute(
        "SELECT d.id, i.title, i.url, d.body FROM draft d JOIN item i ON i.id=d.item_id "
        "WHERE d.status='pending' ORDER BY d.created_at DESC"
    ).fetchall()
    if not rows:
        return None
    DRAFTS_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = DRAFTS_DIR / f"{today}-review.md"
    lines = [f"# Content drafts for review — {today}", "",
             f"_{len(rows)} pending. Edit/approve before any publishing (publishing is manual)._", ""]
    for draft_id, title, url, body_json in rows:
        body = json.loads(body_json)
        profile = body.pop("_profile", "")
        lines.append(f"## #{draft_id} — {title}")
        lines.append(f"_source: {url}{(' · profile: ' + profile) if profile else ''}_")
        lines.append("")
        for key, val in body.items():
            if isinstance(val, list):
                lines.append(f"**{key}:**")
                for i, v in enumerate(val, 1):
                    if isinstance(v, dict):
                        # storyboard-style beat: render each field on its own line
                        parts = " · ".join(f"{k}: {vv}" for k, vv in v.items())
                        lines.append(f"{i}. {parts}")
                    else:
                        lines.append(f"- {v}")
            else:
                lines.append(f"**{key}:** {val}")
            lines.append("")
        lines.append("---")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def blob_client(account: str):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    cred = DefaultAzureCredential()
    return BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=cred)


def blob_download(account: str, container: str) -> None:
    svc = blob_client(account)
    blob = svc.get_blob_client(container, "kb.sqlite")
    if blob.exists():
        KB_DIR.mkdir(parents=True, exist_ok=True)
        with open(KB_PATH, "wb") as f:
            f.write(blob.download_blob().readall())
        print("downloaded existing kb.sqlite from Blob")


def blob_upload(account: str, container: str, review: Path | None) -> None:
    svc = blob_client(account)
    with open(KB_PATH, "rb") as f:
        svc.get_blob_client(container, "kb.sqlite").upload_blob(f, overwrite=True)
    msg = "uploaded kb.sqlite"
    if review:
        with open(review, "rb") as f:
            svc.get_blob_client(container, f"drafts/{review.name}").upload_blob(f, overwrite=True)
        msg += f" + drafts/{review.name}"
    # Publish each user's digest so every user just READS their delivery from Blob (the builder
    # agent downloads digests/builder-<date>.md; it never re-runs the engine to regenerate it).
    n = 0
    if DIGESTS_DIR.exists():
        for p in DIGESTS_DIR.glob("*.md"):
            with open(p, "rb") as f:
                svc.get_blob_client(container, f"digests/{p.name}").upload_blob(f, overwrite=True)
            n += 1
    if n:
        msg += f" + {n} digest(s)"
    print(msg + " to Blob")


def main() -> int:
    # Source titles / log lines contain non-ASCII (≥, em-dash); force UTF-8 so a Windows
    # cp1252 console can't crash the run on a print. No-op where stdout is already UTF-8 (CI).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — older/non-reconfigurable streams: best-effort
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--no-upload", action="store_true", help="skip Blob download/upload (local only)")
    ap.add_argument("--rank", action="store_true", help="score new items for relevance (Azure OpenAI)")
    ap.add_argument("--rank-max", type=int, default=400, help="max items to score per run (cost cap)")
    ap.add_argument("--embed-max", type=int, default=2000,
                    help="max items to embed per run (embedding is cheap; backlog self-heals)")
    ap.add_argument("--draft", action="store_true", help="generate human-review content drafts (Foundry)")
    ap.add_argument("--draft-profile", default="social", help="content profile from config/content.yml")
    ap.add_argument("--draft-min", type=int, default=70, help="min relevance score to draft")
    ap.add_argument("--draft-max", type=int, default=5, help="max drafts per run (cost cap)")
    ap.add_argument("--deliver", "--email", action="store_true", dest="deliver",
                    help="deliver each user's personalized top-N (config/users.json) via their channel")
    ap.add_argument("--feedback", action="store_true",
                    help="ingest per-user feedback events into the KB and recompute affinity")
    ap.add_argument("--discover", action="store_true",
                    help="propose new feeds into config/proposals.yml from recurring item links")
    args = ap.parse_args()

    env = load_env()
    account = env.get("STORAGE_ACCOUNT", "")
    container = env.get("BLOB_CONTAINER", "knowledge")

    rules = json.loads(TAGS.read_text(encoding="utf-8"))["topics"]

    use_blob = not args.no_upload and bool(account)
    if use_blob:
        blob_download(account, container)

    con = connect()
    new_items, total = sync(con, rules)
    endpoint = env.get("FOUNDRY_PROJECT_ENDPOINT", "")
    model = env.get("FOUNDRY_MODEL_NAME", "nano")
    if args.rank:
        from rank import score_unscored
        score_unscored(con, endpoint, model, args.days, args.rank_max)
        # Item tower: embed every ranked-but-unembedded item (not just this window) so the
        # interest-match candidate pool has full embedding coverage. Cheap; backlog self-heals.
        from embed import embed_unembedded
        embed_unembedded(con, endpoint, env.get("FOUNDRY_EMBED_NAME", "embed"), args.embed_max)
    if args.feedback:
        from feedback_ingest import ingest_feedback
        ingest_feedback(con, env.get("FEEDBACK_STORAGE", ""))
    if args.draft:
        from draft import generate_drafts
        generate_drafts(con, endpoint, model, args.draft_profile, args.draft_min, args.draft_max)
    if args.deliver:
        from notify import deliver_all
        users = json.loads((ROOT / "config" / "users.json").read_text(encoding="utf-8"))["users"]
        deliver_all(con, users, env, endpoint, model)
    if args.discover:
        from discover import discover_sources
        discover_sources(con)
    review = render_review(con)
    con.close()
    print(f"sync: +{new_items} new, {total} total items")

    if use_blob:
        blob_upload(account, container, review)
    elif not args.no_upload:
        print("note: STORAGE_ACCOUNT not set — skipped Blob (set it in .env or repo Variables)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
