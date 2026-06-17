"""ai-scout curation helpers (P8) — near-duplicate clustering + source/topic diversity.

These run AFTER ranking, over the candidate list, to make the digest/email feel curated
instead of monotone. Both are cheap, dependency-free, and config-driven (config/curate.json).

- dedup(): collapse near-identical stories (same launch on HN + a blog + arXiv) so the
  reader sees one row, keeping the highest-scored representative. Similarity = Jaccard over
  normalized title tokens (fast, no embeddings, good enough for headlines).
- diversify(): a light MMR-style pass that caps how many items any single source or topic
  may contribute, so one arXiv firehose can't own the whole top-N.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CFG = Path(__file__).resolve().parent.parent / "config" / "curate.json"
_STOP = {"the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "with", "via",
         "using", "how", "new", "is", "are", "be", "your", "you", "we", "this", "that"}


def _cfg() -> dict:
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in _STOP and len(w) > 2}


def _similar(a: set[str], b: set[str], thresh: float) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    union = len(a | b)
    return union > 0 and inter / union >= thresh


def dedup(items: list[dict]) -> list[dict]:
    """Collapse near-duplicate titles, keeping the first (highest-ranked) of each cluster.
    `items` must be pre-sorted best-first; each dict needs at least 'title'. Returns the
    survivors in the same order."""
    thresh = float(_cfg().get("dedup_jaccard", 0.6))
    kept: list[dict] = []
    kept_tokens: list[set[str]] = []
    for it in items:
        toks = _tokens(it.get("title", ""))
        if any(_similar(toks, k, thresh) for k in kept_tokens):
            continue
        kept.append(it)
        kept_tokens.append(toks)
    return kept


def drop_seen(items: list[dict], seen_titles: list[str]) -> list[dict]:
    """Cross-delivery dedup: remove items whose title near-duplicates one ALREADY shown to this
    user — so the same story resurfacing from a different source (a new item id) isn't sent
    twice. Same Jaccard threshold as dedup(). `seen_titles` = titles previously delivered."""
    if not seen_titles:
        return items
    thresh = float(_cfg().get("dedup_jaccard", 0.6))
    seen_tokens = [_tokens(t) for t in seen_titles]
    return [it for it in items
            if not any(_similar(_tokens(it.get("title", "")), s, thresh) for s in seen_tokens)]


def diversify(items: list[dict], limit: int) -> list[dict]:
    """Pick up to `limit` items, capping per-source, per-topic and per-category contributions
    so the result is varied. `items` pre-sorted best-first; each dict needs 'source_id' and
    optionally 'topic'/'category'. The category cap makes a multi-feed firehose (e.g. arXiv's
    cs.AI + cs.CL + cs.LG, one 'Research' category) obey a single bucket limit instead of
    smuggling N× items past the per-source cap. Falls back to filling remaining slots if caps
    are too tight."""
    cfg = _cfg()
    max_src = int(cfg.get("max_per_source", 2))
    max_topic = int(cfg.get("max_per_topic", 2))
    max_cat = int(cfg.get("max_per_category", 0)) or None  # 0/absent = no category cap
    chosen: list[dict] = []
    src_count: dict = {}
    topic_count: dict = {}
    cat_count: dict = {}
    deferred: list[dict] = []
    for it in items:
        if len(chosen) >= limit:
            break
        sid = it.get("source_id")
        topic = it.get("topic")
        cat = it.get("category")
        if (src_count.get(sid, 0) >= max_src
                or (topic and topic_count.get(topic, 0) >= max_topic)
                or (max_cat and cat and cat_count.get(cat, 0) >= max_cat)):
            deferred.append(it)
            continue
        chosen.append(it)
        src_count[sid] = src_count.get(sid, 0) + 1
        if topic:
            topic_count[topic] = topic_count.get(topic, 0) + 1
        if cat:
            cat_count[cat] = cat_count.get(cat, 0) + 1
    # If caps left us short, backfill from deferred (relevance order preserved).
    for it in deferred:
        if len(chosen) >= limit:
            break
        chosen.append(it)
    return chosen
