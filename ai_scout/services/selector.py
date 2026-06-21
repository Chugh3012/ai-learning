from __future__ import annotations

import random

from ai_scout.domain.item import PickReason, ScoredItem
from ai_scout.lib.config import config_json
from ai_scout.lib.vectors import match_bonus
from ai_scout.repositories.knowledge import KnowledgeBase
from ai_scout.services import curation

def interest_weight() -> float:
    try:
        return float(config_json("feedback.json").get("interest_weight", 0))
    except Exception:
        return 0.0

def _explore_ratio() -> float:
    try:
        return float(config_json("feedback.json").get("explore_ratio", 0.0))
    except Exception:
        return 0.0

class Selector:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    @staticmethod
    def _pick_reasons(relevance: float, affinity: float, interest_bonus: float,
                      topic: str | None, category: str | None) -> tuple[PickReason, ...]:
        reasons: list[PickReason] = []
        if relevance >= 80:
            reasons.append(PickReason(code="relevance", text="Strong ranking signal"))
        elif relevance >= 60:
            reasons.append(PickReason(code="quality", text="Cleared the quality bar"))
        else:
            reasons.append(PickReason(code="ranked", text="Selected from the ranked pool"))
        if interest_bonus >= 2.0:
            reasons.append(PickReason(code="interest", text="Matches your stated interests"))
        if affinity >= 2.0:
            reasons.append(PickReason(code="affinity", text="Boosted by your past feedback"))
        if topic:
            reasons.append(PickReason(code="topic", text=f"Covers {topic}"))
        elif category:
            reasons.append(PickReason(code="category", text=f"Adds {category} coverage"))
        return tuple(reasons[:3])

    @staticmethod
    def _append_reason(item: ScoredItem, reason: PickReason) -> ScoredItem:
        if any(r.code == reason.code for r in item.reasons):
            return item
        return item.model_copy(update={"reasons": (*item.reasons, reason)})

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
        rng = rng or random
        if ratio <= 0 or len(items) <= top:
            return items[:top]
        n_explore = min(max(1, round(top * ratio)), top - 1, len(items) - top)
        if n_explore <= 0:
            return items[:top]
        n_exploit = top - n_explore
        explore_reason = PickReason(
            code="exploration",
            text="Exploration slot to keep your edition varied",
        )
        explored = [self._append_reason(it, explore_reason)
                    for it in self._weighted_sample(items[n_exploit:], n_explore, rng)]
        chosen = items[:n_exploit] + explored
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
            interest_bonus = bonus.get(iid, 0.0)
            score = rel + aff + interest_bonus
            if score >= min_score:
                pool.append(ScoredItem(id=iid, title=title, url=url, summary=summary,
                                       source_id=source_id, topic=topic, category=category,
                                       score=score,
                                       reasons=self._pick_reasons(
                                           float(rel), float(aff), float(interest_bonus),
                                           topic, category)))
        pool.sort(key=lambda d: d.score, reverse=True)
        gated = curation.drop_seen(curation.dedup(pool), self.kb.sent_titles(lens))
        window = curation.diversify(gated, max(top * 3, top + 6))
        ratio = _explore_ratio() if explore_ratio is None else explore_ratio
        return self._explore_exploit(window, top, ratio)
