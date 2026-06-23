from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import urljoin, urlparse

from prism.lib.config import CONFIG_DIR
from prism.repositories.knowledge import KnowledgeBase

_PROPOSALS = CONFIG_DIR / "proposals.yml"
_UA = {"User-Agent": "ai-scout-discovery/1.0 (+https://github.com/Chugh3012/ai-learning)"}
_FEED_PATHS = ("/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/index.xml", "/feed.xml")
_SKIP = {"arxiv.org", "news.ycombinator.com", "github.com", "youtube.com", "youtu.be",
         "twitter.com", "x.com", "reddit.com", "producthunt.com", "medium.com"}

def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "").lower()
    except Exception:
        return ""

def _our_domains() -> set[str]:
    from prism.lib.topics import list_topics, load_pack
    out: set[str] = set()
    for topic_id in list_topics():
        try:
            for o in ET.parse(load_pack(topic_id).sources_opml).getroot().iter("outline"):
                u = o.get("xmlUrl")
                if u:
                    out.add(_domain(u))
        except Exception:
            pass
    return out

def _already_proposed() -> set[str]:
    try:
        text = _PROPOSALS.read_text(encoding="utf-8")
    except Exception:
        return set()
    return {_domain(u) for u in re.findall(r"candidate_url:\s*(\S+)", text)}

def _discover_feed(domain: str) -> str | None:
    import feedparser
    home = f"https://{domain}/"
    candidates: list[str] = []
    try:
        req = urllib.request.Request(home, headers=_UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            page = resp.read(200_000).decode("utf-8", "replace")
        for m in re.finditer(r'<link[^>]+rel=["\']alternate["\'][^>]+>', page, re.I):
            tag = m.group(0)
            if re.search(r'type=["\']application/(rss|atom)\+xml["\']', tag, re.I):
                href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
                if href:
                    candidates.append(urljoin(home, href.group(1)))
    except Exception:
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
        except Exception:
            continue
    return None

def _append_proposals(found: list[dict]) -> None:
    text = _PROPOSALS.read_text(encoding="utf-8") if _PROPOSALS.exists() else "proposals: []\n"
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
    _PROPOSALS.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")

class SourceDiscoverer:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    def _candidate_domains(self, skip: set[str], min_seen: int) -> list[tuple[str, int]]:
        counts: Counter[str] = Counter()
        for u in self.kb.item_links():
            d = _domain(u)
            if d and d not in skip and d not in _SKIP:
                counts[d] += 1
        return [(d, n) for d, n in counts.most_common() if n >= min_seen]

    def discover(self, min_seen: int = 3, max_probe: int = 25) -> int:
        try:
            skip = _our_domains() | _already_proposed()
            candidates = self._candidate_domains(skip, min_seen)[:max_probe]
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
        except Exception as e:
            print(f"discover: skipped ({e})")
            return 0
