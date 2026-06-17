"""Ingestor — reads sources (OPML), fetches their feeds, dedupes new items into the KB, and tags
them. The first stage of the pipeline. Depends on a KnowledgeBase (DI); feedparser for fetching.
"""
from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET

from ai_scout.lib.config import CONFIG_DIR, config_json
from ai_scout.repositories.knowledge import KnowledgeBase

_OPML = CONFIG_DIR / "sources.opml"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")
# Statuses worth a retry: rate-limit + transient server errors. 403/404 are permanent.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def read_sources() -> list[dict]:
    tree = ET.parse(_OPML)
    out: list[dict] = []
    for cat in tree.getroot().iter("outline"):
        cat_name = cat.get("text", "")
        for child in cat.findall("outline"):
            url = child.get("xmlUrl")
            if url:
                out.append({"title": child.get("text", url), "url": url,
                            "category": cat_name, "fallback": child.get("fallbackUrl", "")})
    return out


def tag_text(text: str, rules: dict[str, list[str]]) -> list[str]:
    low = text.lower()
    return [t for t, kws in rules.items() if any(k in low for k in kws)] or ["other"]


def _fetch_feed(url: str, attempts: int = 3):
    """Parse a feed, retrying ONLY on transient failures (HTTP 429/5xx, or a connection-level
    bozo with no status). Linear backoff, capped."""
    import feedparser
    feed = feedparser.parse(url, agent=_UA)
    tries = 1
    while tries < attempts and not feed.entries:
        status = getattr(feed, "status", None)
        transient = status in _RETRY_STATUS or (getattr(feed, "bozo", 0) and status is None)
        if not transient:
            break
        time.sleep(min(1.5 * tries, 5))
        feed = feedparser.parse(url, agent=_UA)
        tries += 1
    return feed


class Ingestor:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    def sync(self) -> tuple[int, int]:
        """Fetch every source, insert new items (dedup by hash), tag them. Returns (new, total)."""
        rules = config_json("tags.json").get("topics", {})
        sources = read_sources()
        now = int(time.time())
        new_items = 0
        empty: list[str] = []
        for s in sources:
            sid = self.kb.upsert_source(s)
            feed = _fetch_feed(s["url"])
            if not feed.entries and s.get("fallback"):
                feed = _fetch_feed(s["fallback"])
            if not feed.entries:
                empty.append(f"{s['title']} (HTTP {getattr(feed, 'status', '?')})")
            for e in feed.entries:
                title = (e.get("title") or "(untitled)").strip()
                url = e.get("link") or ""
                summary = e.get("summary", "")[:2000]
                pp = e.get("published_parsed") or e.get("updated_parsed")
                published = int(time.mktime(pp)) if pp else now
                h = hashlib.sha1(f"{url}|{title}".encode("utf-8", "replace")).hexdigest()
                item_id = self.kb.insert_item(sid, title, url, summary, published, now, h)
                if item_id is not None:
                    new_items += 1
                    for topic in tag_text(f"{title} {summary}", rules):
                        self.kb.add_tag(item_id, topic)
            self.kb.commit()
        ok = len(sources) - len(empty)
        print(f"fetch: {ok}/{len(sources)} sources returned entries")
        if empty:
            print("fetch: EMPTY (no entries — possible block/dead feed): " + "; ".join(empty))
        return new_items, self.kb.item_count()
