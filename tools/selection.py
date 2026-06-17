#!/usr/bin/env python3
"""Shared SELECTION filter (candidate generation + re-ranking) for ai-scout.

One reusable stage — parameterized by a LENS — that turns the one shared ranking into a
curated per-lens shortlist. Every output SINK (the delivery email/digest, the content/reel
drafter, any future autonomous producer) calls select_items() instead of hand-rolling its own
retrieval, so curation lives in exactly one place. This is the standard recsys split:
shared scoring (relevance) -> per-lens candidate generation (interest match + affinity) ->
re-ranking (dedup, drop-seen, diversify, explore/exploit).

Named `selection` (not `select`) so it never shadows the Python stdlib `select` module, which
`selectors`/`urllib3`/asyncio import transitively (tools/ sits on sys.path[0]).

A LENS is just an id that namespaces per-lens state in signal.kind:
  sent:<lens>       items this lens already emitted (never re-select)
  affinity:<lens>   learned +/- feedback for this lens
The lens's interest vector + weight steer the pick semantically; with no interest vector the
pick is exactly relevance + affinity. Pure-stdlib, offline-testable; no channel/render here.
"""
from __future__ import annotations

import json
import random
import sqlite3
import time
from pathlib import Path

_FEEDBACK_CFG = Path(__file__).resolve().parent.parent / "config" / "feedback.json"


def _cfg_float(key: str, default: float = 0.0) -> float:
    """Read one numeric knob from config/feedback.json; default on any failure."""
    try:
        return float(json.loads(_FEEDBACK_CFG.read_text(encoding="utf-8")).get(key, default))
    except Exception:  # noqa: BLE001
        return default


def _interest_weight() -> float:
    """How strongly a lens's interest match steers its pick (config/feedback.json).
    0 = off (pure shared relevance + feedback). Read once per run."""
    return _cfg_float("interest_weight", 0.0)


def _explore_ratio() -> float:
    """Fraction of a lens's top-N reserved for EXPLORATION (config/feedback.json). 0 = pure
    exploit (always the highest-scored). e.g. 0.2 on a top-5 = 1 wildcard slot."""
    return _cfg_float("explore_ratio", 0.0)


def _weighted_sample(items: list[dict], k: int, rng: random.Random) -> list[dict]:
    """Pick k items WITHOUT replacement, weighted by score — exploration still favors decent
    items but is genuinely stochastic (a softmax-ish nudge, not pure random)."""
    pool = list(items)
    weights = [max(float(d.get("score", 0)), 1.0) for d in pool]
    out: list[dict] = []
    for _ in range(min(k, len(pool))):
        i = rng.choices(range(len(pool)), weights=weights, k=1)[0]
        out.append(pool.pop(i))
        weights.pop(i)
    return out


def _explore_exploit(items: list[dict], top: int, ratio: float,
                     rng: random.Random | None = None) -> list[dict]:
    """Balance EXPLOIT (highest final_score) with EXPLORE (a stochastic pick from the other
    quality-gated candidates). Reserves round(top*ratio) of the top-N for score-weighted samples
    drawn from BELOW the exploit cut — keeping the filter bubble from closing and gathering
    feedback on under-seen items. `items` must be pre-sorted best-first and already gated/deduped/
    diversified. ratio<=0 or too few spare items -> pure exploit. Returns up to `top`, score-sorted."""
    rng = rng or random
    if ratio <= 0 or len(items) <= top:
        return items[:top]
    n_explore = min(max(1, round(top * ratio)), top - 1, len(items) - top)
    if n_explore <= 0:
        return items[:top]
    n_exploit = top - n_explore
    exploit = items[:n_exploit]
    explore = _weighted_sample(items[n_exploit:], n_explore, rng)
    chosen = exploit + explore
    chosen.sort(key=lambda d: d["score"], reverse=True)
    return chosen


def select_items(con: sqlite3.Connection, lens_id: str, top: int,
                 min_score: float = 0.0, interest_vec: list[float] | None = None,
                 interest_weight: float = 0.0,
                 explore_ratio: float | None = None) -> list[dict]:
    """Per-lens pick, two-stage (the standard recsys design):
      1. RETRIEVAL (SQL): candidate items this lens hasn't emitted that carry a relevance
         score (the shared quality gate), capped — with their affinity and embedding.
      2. RANKING (Python): final = relevance + this lens's affinity + interest match bonus
         (z-scored cosine to the lens's interest vector). Gate by min_score, then curate
         (dedup -> drop already-seen -> diversify to a window) and balance exploit vs explore.
    The interest bonus lets a semantically-matching item SURFACE without hand-filtering sources.
    With no interest vector (or no embeddings yet) the bonus is 0 and this is exactly the plain
    relevance+affinity pick. State is namespaced per lens in signal.kind: sent:<lens>,
    affinity:<lens>. `explore_ratio` None -> use the config default; pass 0.0 for a deterministic
    top-N (e.g. a content sink that shouldn't gamble a production slot)."""
    sent_kind = f"sent:{lens_id}"
    aff_kind = f"affinity:{lens_id}"
    rows = con.execute(
        "SELECT i.id, i.title, i.url, i.summary, i.source_id, "
        "  (SELECT t.topic FROM tag t WHERE t.item_id=i.id LIMIT 1) AS topic, "
        "  s.value AS rel, "
        "  COALESCE((SELECT a.value FROM signal a WHERE a.item_id=i.id AND a.kind=?), 0) AS aff, "
        "  (SELECT e.vec FROM embedding e WHERE e.item_id=i.id) AS vec, "
        "  (SELECT src.category FROM source src WHERE src.id=i.source_id) AS category "
        "FROM item i "
        "JOIN signal s ON s.item_id=i.id AND s.kind='relevance' "
        "WHERE NOT EXISTS (SELECT 1 FROM signal e WHERE e.item_id=i.id AND e.kind=?) "
        "GROUP BY i.id "
        "ORDER BY (s.value + aff) DESC, i.published DESC LIMIT ?",
        (aff_kind, sent_kind, max(top * 20, 200)),
    ).fetchall()
    if not rows:
        return []

    from embed import match_bonus
    vecs = {r[0]: r[8] for r in rows if r[8]}
    bonus = match_bonus(interest_vec, vecs, interest_weight)

    pool = []
    for iid, title, url, summary, source_id, topic, rel, aff, _vec, category in rows:
        score = rel + aff + bonus.get(iid, 0.0)
        if score >= min_score:
            pool.append({"id": iid, "title": title, "url": url, "summary": summary,
                         "source_id": source_id, "topic": topic, "category": category,
                         "score": score})
    pool.sort(key=lambda d: d["score"], reverse=True)

    # Cross-delivery dedup: never re-emit a story already shown to this lens, even from a
    # different source/item id (sent:<lens> only blocks the exact item). Compare titles.
    seen_titles = [r[0] for r in con.execute(
        "SELECT i.title FROM item i JOIN signal s ON s.item_id=i.id AND s.kind=?", (sent_kind,)
    ).fetchall()]

    from curate import dedup, diversify, drop_seen
    # Quality-gate -> dedup -> drop already-seen, then diversify to a WINDOW larger than top so
    # exploration has genuine alternatives to sample from; finally balance exploit vs explore.
    gated = drop_seen(dedup(pool), seen_titles)
    window = diversify(gated, max(top * 3, top + 6))
    ratio = _explore_ratio() if explore_ratio is None else explore_ratio
    return _explore_exploit(window, top, ratio)


def mark_sent(con: sqlite3.Connection, lens_id: str, item_ids: list[int]) -> None:
    """Record that this lens emitted these items (signal kind sent:<lens>), so select_items
    never re-selects them. Each sink calls this after it successfully emits/produces."""
    now = int(time.time())
    con.executemany(
        "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
        [(i, f"sent:{lens_id}", 1.0, now) for i in item_ids],
    )
    con.commit()
