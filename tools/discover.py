#!/usr/bin/env python3
"""Source discovery, called by kb_sync (--discover). Mines external domains that KB item links
point to but we don't yet ingest, does RSS/Atom autodiscovery on the recurring ones, and writes
verified-live candidates to config/proposals.yml for HUMAN review (approve -> merge into
sources.opml). The pipeline grows its own intake instead of waiting to be handed URLs; humans
stay the gate. Stdlib + feedparser only; no network writes, never raises.
"""
from __future__ import annotations

import re
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
OPML = ROOT / "config" / "sources.opml"
PROPOSALS = ROOT / "config" / "proposals.yml"
_UA = {"User-Agent": "ai-scout-discovery/1.0 (+https://github.com/Chugh3012/ai-learning)"}
_FEED_PATHS = ("/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/index.xml", "/feed.xml")
# Domains that are aggregators or already-covered hubs — never propose these as sources.
_SKIP = {"arxiv.org", "news.ycombinator.com", "github.com", "youtube.com", "youtu.be",
         "twitter.com", "x.com", "reddit.com", "producthunt.com", "medium.com"}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _our_domains() -> set[str]:
    out: set[str] = set()
    try:
        for o in ET.parse(OPML).getroot().iter("outline"):
            u = o.get("xmlUrl")
            if u:
                out.add(_domain(u))
    except Exception:  # noqa: BLE001
        pass
    return out


def _already_proposed() -> set[str]:
    """URLs/domains already sitting in proposals.yml (so we never re-propose)."""
    try:
        text = PROPOSALS.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return set()
    return {_domain(u) for u in re.findall(r"candidate_url:\s*(\S+)", text)}


def _candidate_domains(con: sqlite3.Connection, skip: set[str], min_seen: int) -> list[tuple[str, int]]:
    """External domains in item links we don't ingest, seen >= min_seen times."""
    counts: Counter[str] = Counter()
    for (u,) in con.execute("SELECT url FROM item WHERE url LIKE 'http%'"):
        d = _domain(u)
        if d and d not in skip and d not in _SKIP:
            counts[d] += 1
    return [(d, n) for d, n in counts.most_common() if n >= min_seen]


def _discover_feed(domain: str) -> str | None:
    """Best-effort: find an RSS/Atom feed for a domain via <link rel=alternate> then common
    paths. Returns a verified feed URL (parses with >=1 entry) or None."""
    import feedparser

    home = f"https://{domain}/"
    candidates: list[str] = []
    try:
        req = urllib.request.Request(home, headers=_UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read(200_000).decode("utf-8", "replace")
        for m in re.finditer(
            r'<link[^>]+rel=["\']alternate["\'][^>]+>', html, re.I):
            tag = m.group(0)
            if re.search(r'type=["\']application/(rss|atom)\+xml["\']', tag, re.I):
                href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
                if href:
                    candidates.append(urljoin(home, href.group(1)))
    except Exception:  # noqa: BLE001 — site may be down/blocking; fall through to common paths
        pass
    candidates += [urljoin(home, p) for p in _FEED_PATHS]

    seen: set[str] = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            f = feedparser.parse(url)
            if getattr(f, "entries", None):
                return url
        except Exception:  # noqa: BLE001
            continue
    return None


def _append_proposals(found: list[dict]) -> None:
    """Append verified candidates to proposals.yml as YAML text (no yaml dep). Replaces the
    'proposals: []' placeholder or appends under an existing list."""
    text = PROPOSALS.read_text(encoding="utf-8") if PROPOSALS.exists() else "proposals: []\n"
    block = "".join(
        f"  - name: {d['name']}\n"
        f"    candidate_url: {d['url']}\n"
        f"    kind: native\n"
        f"    seen_count: {d['seen']}\n"
        f"    reason: {d['reason']}\n"
        f"    status: proposed\n"
        for d in found
    )
    if "proposals: []" in text:
        text = text.replace("proposals: []", "proposals:\n" + block.rstrip("\n"))
    else:
        text = text.rstrip("\n") + "\n" + block
    PROPOSALS.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def discover_sources(con: sqlite3.Connection, min_seen: int = 3, max_probe: int = 25) -> int:
    """Propose new feeds into proposals.yml from recurring external item-link domains.
    Returns the count proposed (0 if none clear the bar). Human reviews + merges. Never raises."""
    try:
        skip = _our_domains() | _already_proposed()
        candidates = _candidate_domains(con, skip, min_seen)[:max_probe]
        found: list[dict] = []
        for domain, seen in candidates:
            feed = _discover_feed(domain)
            if feed:
                found.append({"name": domain, "url": feed, "seen": seen,
                              "reason": f"linked by {seen} KB items; feed auto-discovered"})
        if found:
            _append_proposals(found)
        print(f"discover: probed {len(candidates)} domain(s) (seen>={min_seen}); "
              f"proposed {len(found)} new feed(s) -> config/proposals.yml")
        return len(found)
    except Exception as e:  # noqa: BLE001 — discovery is optional, never break the pipeline
        print(f"discover: skipped ({e})")
        return 0
