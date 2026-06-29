from __future__ import annotations

from prism.domain.item import PickReason, ScoredItem
from prism.lib.config import config_json
from prism.lib.vectors import match_bonus
from prism.repositories.knowledge import KnowledgeBase
from prism.services import curation
from prism.services.personalization.explorer import EpsilonExplorer
from prism.services.personalization.novelty import novelty_penalties, novelty_weight

def interest_weight() -> float:
    try:
        return float(config_json("feedback.json").get("interest_weight", 0))
    except Exception:
        return 0.0

class Selector:
    def __init__(self, kb: KnowledgeBase, explorer=None):
        self.kb = kb
        self.explorer = explorer

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

    def _add_interest_candidates(self, rows: list[tuple], lens: str,
                                 interest_vec: list[float] | None, k: int,
                                 topic_id: str | None) -> list[tuple]:
        # Two-tower retrieval: also pull the items most similar to the reader's interest/taste
        # vector, so a stated interest surfaces matching items even when their shared relevance is
        # mid -- the interest lens drives retrieval, not just re-ranking. No-op without an interest
        # vector (most users), so default behaviour is unchanged.
        # ponytail: O(n) cosine over a recency window (~1500). Swap to an ANN index if the embedded
        # KB ever grows past tens of thousands of items.
        if not interest_vec:
            return rows
        emb = self.kb.embedded_candidates(lens, 1500, topic_id)
        if not emb:
            return rows
        sims = match_bonus(interest_vec, {r[0]: r[8] for r in emb if r[8]}, 1.0)
        if not sims:
            return rows
        # Decision-aware: blend z-scored similarity with normalised LLM relevance (rel/50 ∈ [0,2])
        # so the interest tower preferentially retrieves items likely to change the final selection,
        # not just the ones closest to the interest centroid regardless of quality.
        # ponytail: fixed /50 weight; tune per-topic if relevance-vs-interest tradeoff needs adjustment.
        rel_map = {r[0]: float(r[6] or 0) / 50.0 for r in emb}
        combined = {iid: s + rel_map.get(iid, 0.0) for iid, s in sims.items()}
        top_ids = set(sorted(combined, key=combined.get, reverse=True)[:k])
        have = {r[0] for r in rows}
        return rows + [r for r in emb if r[0] in top_ids and r[0] not in have]

    def select(self, lens: str, top: int, min_score: float = 0.0,
               interest_vec: list[float] | None = None, weight: float = 0.0,
               explore_ratio: float | None = None, topic_id: str | None = None) -> list[ScoredItem]:
        k = max(top * 20, 200)
        rows = self.kb.candidates(lens, k, topic_id)
        rows = self._add_interest_candidates(rows, lens, interest_vec, k, topic_id)
        if not rows:
            return []
        vecs = {r[0]: r[8] for r in rows if r[8]}
        bonus = match_bonus(interest_vec, vecs, weight)
        nw = novelty_weight()
        penalty = (novelty_penalties([v for *_x, v in self.kb.sent_with_embeddings(lens, set())],
                                     vecs, nw) if nw > 0 else {})
        pool: list[ScoredItem] = []
        for iid, title, url, summary, source_id, topic, rel, aff, _vec, category in rows:
            interest_bonus = bonus.get(iid, 0.0)
            score = rel + aff + interest_bonus - penalty.get(iid, 0.0)
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
        explorer = self.explorer or EpsilonExplorer(explore_ratio)
        return explorer.choose(window, top, lens)
