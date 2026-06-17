"""Curation — pure, dependency-free transforms over a ranked candidate list (no I/O, no state).

These run AFTER ranking to make a delivery feel curated instead of monotone. Kept as functions
(not a class) on purpose: they are stateless pure transforms — the idiomatic Python unit here is a
module, and wrapping them in a class would be the "ravioli" the style guides warn against.
Config-driven via config/curate.json. Operate on ScoredItem value objects.
"""
from __future__ import annotations

import json
import re

from ai_scout.domain.item import ScoredItem
from ai_scout.lib.config import CONFIG_DIR

_CFG = CONFIG_DIR / "curate.json"
_STOP = {"the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "with", "via",
         "using", "how", "new", "is", "are", "be", "your", "you", "we", "this", "that"}


def _cfg() -> dict:
    try:
        return json.loads(_CFG.read_text(encoding="utf-8"))
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


def dedup(items: list[ScoredItem]) -> list[ScoredItem]:
    """Collapse near-duplicate titles, keeping the first (highest-ranked) of each cluster.
    `items` must be pre-sorted best-first. Returns survivors in the same order."""
    thresh = float(_cfg().get("dedup_jaccard", 0.6))
    kept: list[ScoredItem] = []
    kept_tokens: list[set[str]] = []
    for it in items:
        toks = _tokens(it.title)
        if any(_similar(toks, k, thresh) for k in kept_tokens):
            continue
        kept.append(it)
        kept_tokens.append(toks)
    return kept


def drop_seen(items: list[ScoredItem], seen_titles: list[str]) -> list[ScoredItem]:
    """Cross-delivery dedup: remove items whose title near-duplicates one ALREADY shown to this
    lens — so the same story resurfacing from a different source isn't sent twice."""
    if not seen_titles:
        return items
    thresh = float(_cfg().get("dedup_jaccard", 0.6))
    seen_tokens = [_tokens(t) for t in seen_titles]
    return [it for it in items
            if not any(_similar(_tokens(it.title), s, thresh) for s in seen_tokens)]


def diversify(items: list[ScoredItem], limit: int) -> list[ScoredItem]:
    """Pick up to `limit` items, capping per-source, per-topic and per-category contributions so
    the result is varied. Falls back to filling remaining slots if caps are too tight."""
    cfg = _cfg()
    max_src = int(cfg.get("max_per_source", 2))
    max_topic = int(cfg.get("max_per_topic", 2))
    max_cat = int(cfg.get("max_per_category", 0)) or None
    chosen: list[ScoredItem] = []
    src_count: dict = {}
    topic_count: dict = {}
    cat_count: dict = {}
    deferred: list[ScoredItem] = []
    for it in items:
        if len(chosen) >= limit:
            break
        if (src_count.get(it.source_id, 0) >= max_src
                or (it.topic and topic_count.get(it.topic, 0) >= max_topic)
                or (max_cat and it.category and cat_count.get(it.category, 0) >= max_cat)):
            deferred.append(it)
            continue
        chosen.append(it)
        src_count[it.source_id] = src_count.get(it.source_id, 0) + 1
        if it.topic:
            topic_count[it.topic] = topic_count.get(it.topic, 0) + 1
        if it.category:
            cat_count[it.category] = cat_count.get(it.category, 0) + 1
    for it in deferred:
        if len(chosen) >= limit:
            break
        chosen.append(it)
    return chosen
