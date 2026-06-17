"""Selector — per-lens candidate generation + re-ranking (the standard recsys design).

Two stages: RETRIEVAL (the KB returns rank-eligible, not-yet-sent candidates with relevance +
this lens's affinity + embedding) then RANKING (final = relevance + affinity + interest-match
bonus), gated by min_score, curated (dedup -> drop-seen -> diversify to a window), and balanced
exploit-vs-explore. Returns ScoredItem value objects. Depends on a KnowledgeBase (DI); pure logic
otherwise (interest match + curation are injected/imported, no Azure here).
"""
from __future__ import annotations

import random

from ai_scout.domain.item import ScoredItem
from ai_scout.lib.config import config_json
from ai_scout.lib.vectors import match_bonus
from ai_scout.repositories.knowledge import KnowledgeBase
from ai_scout.services import curation


def interest_weight() -> float:
    """How strongly a lens's interest match steers its pick (config/feedback.json)."""
    try:
        return float(config_json("feedback.json").get("interest_weight", 0))
    except Exception:  # noqa: BLE001
        return 0.0


def _explore_ratio() -> float:
    try:
        return float(config_json("feedback.json").get("explore_ratio", 0.0))
    except Exception:  # noqa: BLE001
        return 0.0


class Selector:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    @staticmethod
    def _weighted_sample(items: list[ScoredItem], k: int, rng: random.Random) -> list[ScoredItem]:
        pool = list(items)
        weights = [max(float(d.score), 1.0) for d in pool]
        out: list[ScoredItem] = []
        for _ in range(min(k, len(pool))):
            i = rng.choices(range(len(pool)), weights=weights, k=1)[0]
            out.append(pool.pop(i))
            weights.pop(i)
        return out

    def _explore_exploit(self, items: list[ScoredItem], top: int, ratio: float,
                         rng: random.Random | None = None) -> list[ScoredItem]:
        """Balance EXPLOIT (highest score) with EXPLORE (a score-weighted stochastic pick from
        below the cut). `items` pre-sorted best-first and already gated/curated. ratio<=0 or too
        few spare items -> pure exploit. Returns up to `top`, score-sorted."""
        rng = rng or random
        if ratio <= 0 or len(items) <= top:
            return items[:top]
        n_explore = min(max(1, round(top * ratio)), top - 1, len(items) - top)
        if n_explore <= 0:
            return items[:top]
        n_exploit = top - n_explore
        chosen = items[:n_exploit] + self._weighted_sample(items[n_exploit:], n_explore, rng)
        chosen.sort(key=lambda d: d.score, reverse=True)
        return chosen

    def select(self, lens: str, top: int, min_score: float = 0.0,
               interest_vec: list[float] | None = None, weight: float = 0.0,
               explore_ratio: float | None = None) -> list[ScoredItem]:
        rows = self.kb.candidates(lens, max(top * 20, 200))
        if not rows:
            return []
        vecs = {r[0]: r[8] for r in rows if r[8]}
        bonus = match_bonus(interest_vec, vecs, weight)
        pool: list[ScoredItem] = []
        for iid, title, url, summary, source_id, topic, rel, aff, _vec, category in rows:
            score = rel + aff + bonus.get(iid, 0.0)
            if score >= min_score:
                pool.append(ScoredItem(id=iid, title=title, url=url, summary=summary,
                                       source_id=source_id, topic=topic, category=category,
                                       score=score))
        pool.sort(key=lambda d: d.score, reverse=True)
        gated = curation.drop_seen(curation.dedup(pool), self.kb.sent_titles(lens))
        window = curation.diversify(gated, max(top * 3, top + 6))
        ratio = _explore_ratio() if explore_ratio is None else explore_ratio
        return self._explore_exploit(window, top, ratio)
