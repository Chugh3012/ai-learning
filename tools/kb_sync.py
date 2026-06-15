#!/usr/bin/env python3
"""ai-scout knowledge-base sync (Layer D / P3) — the owned system of record.

Pipeline (runs locally or in GitHub Actions cron):
  1. (cloud) download existing kb.sqlite from Azure Blob  -> incremental
  2. read feed list from config/sources.opml
  3. fetch + parse feeds (feedparser), dedupe into SQLite (generic schema)
  4. tag items via config/tags.json
  5. render a grouped markdown digest
  6. (cloud) upload kb.sqlite + digest back to Blob (Entra/RBAC, no keys)

Schema is generic so new signal types never need migrations:
  source(id,title,url,kind,category)
  item(id,source_id,title,url,summary,published,fetched_at,hash UNIQUE)
  tag(item_id,topic)            -- many-to-many topics
  signal(id,item_id,kind,value,ts)  -- reserved for P4 feedback/relevance

Auth: passwordless. DefaultAzureCredential uses `az login` locally and the
GitHub OIDC federated token in Actions. No secrets, no connection strings.

Usage:
  python tools/kb_sync.py                 # sync + digest + Blob backup
  python tools/kb_sync.py --no-upload     # local only, skip Blob
  python tools/kb_sync.py --days 7        # digest window
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
DIGEST_DIR = ROOT / "digests"
DRAFTS_DIR = ROOT / "drafts"

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
CREATE INDEX IF NOT EXISTS idx_item_published ON item(published);
"""


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items()
                if k in ("STORAGE_ACCOUNT", "BLOB_CONTAINER",
                         "FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_MODEL_NAME",
                         "ACS_ENDPOINT", "EMAIL_SENDER", "EMAIL_TO",
                         "FEEDBACK_URL", "FEEDBACK_STORAGE")})
    return env


def read_sources() -> list[dict]:
    tree = ET.parse(OPML)
    out: list[dict] = []
    for cat in tree.getroot().iter("outline"):
        cat_name = cat.get("text", "")
        for child in cat.findall("outline"):
            url = child.get("xmlUrl")
            if url:
                out.append({"title": child.get("text", url), "url": url, "category": cat_name})
    return out


def connect() -> sqlite3.Connection:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(KB_PATH)
    con.executescript(SCHEMA)
    return con


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


def sync(con: sqlite3.Connection, rules: dict) -> tuple[int, int]:
    import feedparser  # local import so --help works without the dep

    sources = read_sources()
    now = int(time.time())
    new_items = 0
    for s in sources:
        sid = upsert_source(con, s)
        feed = feedparser.parse(s["url"])
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
    total = con.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    return new_items, total


def render_digest(con: sqlite3.Connection, rules: dict, days: int) -> Path:
    cutoff = int(time.time()) - days * 86400
    order = list(rules.keys()) + ["other"]
    DIGEST_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = DIGEST_DIR / f"{today}.md"

    rows = con.execute(
        "SELECT i.title, i.url, s.title, i.published, t.topic, "
        "       (SELECT value FROM signal sg WHERE sg.item_id=i.id AND sg.kind='relevance' "
        "        ORDER BY sg.ts DESC LIMIT 1) AS score, "
        "       (SELECT value FROM signal af WHERE af.item_id=i.id AND af.kind='affinity' "
        "        ORDER BY af.ts DESC LIMIT 1) AS aff "
        "FROM item i JOIN tag t ON t.item_id=i.id JOIN source s ON s.id=i.source_id "
        "WHERE i.published>=? "
        "ORDER BY score IS NULL, (COALESCE(score,0)+COALESCE(aff,0)) DESC, i.published DESC",
        (cutoff,),
    ).fetchall()

    buckets: dict[str, list] = {}
    kept = set()
    for title, url, feed, ts, topic, score, aff in rows:
        buckets.setdefault(topic, []).append((title, url, feed, score))
        kept.add(url)

    # Drop near-duplicate headlines within each topic (keep the highest-ranked).
    from curate import dedup
    for topic, lst in buckets.items():
        survivors = dedup([{"title": t, "url": u, "feed": f, "score": sc} for t, u, f, sc in lst])
        buckets[topic] = [(d["title"], d["url"], d["feed"], d["score"]) for d in survivors]
    kept = {u for lst in buckets.values() for _, u, _, _ in lst}

    ranked = any(s is not None for b in buckets.values() for *_, s in b)
    note = "ranked by relevance" if ranked else "by recency"
    lines = [f"# ai-scout digest — {today}", "",
             f"_{len(kept)} items from the last {days} days, grouped by topic, {note}._", ""]
    for topic in order:
        if topic not in buckets:
            continue
        lines.append(f"## {topic}  ({len(buckets[topic])})")
        for title, url, feed, score in buckets[topic]:
            badge = f"**[{int(score)}]** " if score is not None else ""
            src = f" — _{feed}_" if feed else ""
            lines.append(f"- {badge}[{title}]({url}){src}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


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
                lines.extend(f"- {v}" for v in val)
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


def blob_upload(account: str, container: str, digest: Path, review: Path | None) -> None:
    svc = blob_client(account)
    with open(KB_PATH, "rb") as f:
        svc.get_blob_client(container, "kb.sqlite").upload_blob(f, overwrite=True)
    with open(digest, "rb") as f:
        svc.get_blob_client(container, f"digests/{digest.name}").upload_blob(f, overwrite=True)
    msg = f"uploaded kb.sqlite + digests/{digest.name}"
    if review:
        with open(review, "rb") as f:
            svc.get_blob_client(container, f"drafts/{review.name}").upload_blob(f, overwrite=True)
        msg += f" + drafts/{review.name}"
    print(msg + " to Blob")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--no-upload", action="store_true", help="skip Blob download/upload (local only)")
    ap.add_argument("--rank", action="store_true", help="score new items for relevance (Azure OpenAI)")
    ap.add_argument("--rank-max", type=int, default=400, help="max items to score per run (cost cap)")
    ap.add_argument("--draft", action="store_true", help="generate human-review content drafts (Foundry)")
    ap.add_argument("--draft-profile", default="social", help="content profile from config/content.yml")
    ap.add_argument("--draft-min", type=int, default=70, help="min relevance score to draft")
    ap.add_argument("--draft-max", type=int, default=5, help="max drafts per run (cost cap)")
    ap.add_argument("--email", action="store_true", help="email top ranked items (ACS, passwordless)")
    ap.add_argument("--email-top", type=int, default=5, help="items per email")
    ap.add_argument("--feedback", action="store_true",
                    help="ingest email feedback events into the KB and recompute ranking affinity")
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
    if args.feedback:
        from feedback_ingest import ingest_feedback
        ingest_feedback(con, env.get("FEEDBACK_STORAGE", ""))
    if args.draft:
        from draft import generate_drafts
        generate_drafts(con, endpoint, model, args.draft_profile, args.draft_min, args.draft_max)
    if args.email:
        from notify import send_email
        send_email(con, env.get("ACS_ENDPOINT", ""), env.get("EMAIL_SENDER", ""),
                   env.get("EMAIL_TO", ""), endpoint, model, args.email_top,
                   env.get("FEEDBACK_URL", ""), env.get("FEEDBACK_STORAGE", ""))
    digest = render_digest(con, rules, args.days)
    review = render_review(con)
    con.close()
    print(f"sync: +{new_items} new, {total} total items; wrote {digest.name}")

    if use_blob:
        blob_upload(account, container, digest, review)
    elif not args.no_upload:
        print("note: STORAGE_ACCOUNT not set — skipped Blob (set it in .env or repo Variables)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
