from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET

from prism.lib.topics import DEFAULT_TOPIC, list_topics, load_pack
from prism.repositories.knowledge import KnowledgeBase

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

def read_sources(opml_path) -> list[dict]:
    tree = ET.parse(opml_path)
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

def _is_retryable(feed) -> bool:
    if feed is None or getattr(feed, "entries", None):
        return False
    status = getattr(feed, "status", None)
    return status in _RETRY_STATUS or bool(getattr(feed, "bozo", 0) and status is None)

def _fetch_feed(url: str, attempts: int = 3):
    import feedparser
    from tenacity import Retrying, stop_after_attempt, wait_incrementing, retry_if_result
    retryer = Retrying(
        stop=stop_after_attempt(attempts),
        wait=wait_incrementing(start=1.5, increment=1.5, max=5),
        retry=retry_if_result(_is_retryable),
        retry_error_callback=lambda state: state.outcome.result(),
    )
    return retryer(lambda: feedparser.parse(url, agent=_UA))

class Ingestor:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.sources_total = 0
        self.feeds_failed = 0

    def sync(self) -> tuple[int, int]:
        now = int(time.time())
        new_items = 0
        empty: list[str] = []
        total_sources = 0
        for topic_id in list_topics() or [DEFAULT_TOPIC]:
            pack = load_pack(topic_id)
            rules = pack.tags
            sources = read_sources(pack.sources_opml)
            total_sources += len(sources)
            for s in sources:
                s["topic_id"] = topic_id
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
                    item_id = self.kb.insert_item(sid, title, url, summary, published, now, h,
                                                  topic_id)
                    if item_id is not None:
                        new_items += 1
                        for topic in tag_text(f"{title} {summary}", rules):
                            self.kb.add_tag(item_id, topic)
                self.kb.commit()
        ok = total_sources - len(empty)
        self.sources_total = total_sources
        self.feeds_failed = len(empty)
        print(f"fetch: {ok}/{total_sources} sources returned entries")
        if empty:
            print("fetch: EMPTY (no entries — possible block/dead feed): " + "; ".join(empty))
        return new_items, self.kb.item_count()
