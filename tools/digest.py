#!/usr/bin/env python3
"""ai-scout digest (Layer C) — sleek, stdlib-only.

Pulls recent items from FreshRSS via its Google Reader API (the same decoupled
interface P3 will reuse), tags them using config/tags.json, groups by topic, and
writes a markdown digest to digests/. No third-party dependencies.

Usage:
    python tools/digest.py [--days 7] [--max 300]

Config/credentials come from .env (FRESHRSS_PORT, FRESHRSS_ADMIN_USER,
FRESHRSS_ADMIN_PASSWORD). Growth = edit config/tags.json, not this file.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
TAGS = ROOT / "config" / "tags.json"
OUT_DIR = ROOT / "digests"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def api(base: str, path: str, token: str | None = None, data: dict | None = None) -> str:
    url = f"{base}{path}"
    headers = {"User-Agent": "ai-scout-digest"}
    if token:
        headers["Authorization"] = f"GoogleLogin auth={token}"
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def login(base: str, user: str, password: str) -> str:
    raw = api(base, "/accounts/ClientLogin", data={"Email": user, "Passwd": password})
    for line in raw.splitlines():
        if line.startswith("Auth="):
            return line[5:]
    raise SystemExit("login failed: no Auth token returned (check API password / API enabled)")


def fetch_items(base: str, token: str, max_items: int) -> list[dict]:
    path = (
        "/reader/api/0/stream/contents/user/-/state/com.google/reading-list"
        f"?output=json&n={max_items}"
    )
    payload = json.loads(api(base, path, token=token))
    return payload.get("items", [])


def tag(text: str, rules: dict[str, list[str]]) -> list[str]:
    low = text.lower()
    return [topic for topic, kws in rules.items() if any(k in low for k in kws)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="include items newer than N days")
    ap.add_argument("--max", type=int, default=300, help="max items to pull from the API")
    args = ap.parse_args()

    env = load_env()
    base = f"http://localhost:{env.get('FRESHRSS_PORT', '8080')}/api/greader.php"
    user = env.get("FRESHRSS_ADMIN_USER", "admin")
    password = env.get("FRESHRSS_ADMIN_PASSWORD", "")
    rules = json.loads(TAGS.read_text(encoding="utf-8"))["topics"]

    token = login(base, user, password)
    items = fetch_items(base, token, args.max)

    cutoff = time.time() - args.days * 86400
    buckets: dict[str, list[dict]] = {}
    seen_topics: set[str] = set()
    kept = 0
    for it in items:
        published = it.get("published", 0)
        if published and published < cutoff:
            continue
        title = it.get("title", "(untitled)").strip()
        url = (it.get("canonical") or it.get("alternate") or [{}])[0].get("href", "")
        feed = it.get("origin", {}).get("title", "")
        summary = it.get("summary", {}).get("content", "") or it.get("content", {}).get("content", "")
        topics = tag(f"{title} {summary}", rules) or ["other"]
        kept += 1
        for t in topics:
            seen_topics.add(t)
            buckets.setdefault(t, []).append({"title": title, "url": url, "feed": feed, "ts": published})

    OUT_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = OUT_DIR / f"{today}.md"

    lines = [f"# ai-scout digest — {today}", "", f"_{kept} items from the last {args.days} days, grouped by topic._", ""]
    # Stable order: tags.json order first, then 'other' last.
    order = [t for t in rules if t in buckets] + (["other"] if "other" in buckets else [])
    for topic in order:
        entries = sorted(buckets[topic], key=lambda e: e["ts"], reverse=True)
        lines.append(f"## {topic}  ({len(entries)})")
        for e in entries:
            src = f" — _{e['feed']}_" if e["feed"] else ""
            lines.append(f"- [{e['title']}]({e['url']}){src}")
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} — {kept} items across {len(order)} topics")
    return 0


if __name__ == "__main__":
    sys.exit(main())
