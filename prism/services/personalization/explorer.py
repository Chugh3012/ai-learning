from __future__ import annotations

import random
from typing import Protocol

from prism.domain.item import PickReason, ScoredItem
from prism.lib.config import config_json

_EXPLORE_REASON = PickReason(code="exploration",
                             text="Exploration slot to keep your edition varied")

def _config_ratio() -> float:
    try:
        return float(config_json("feedback.json").get("explore_ratio", 0.0))
    except Exception:
        return 0.0

def _append_reason(item: ScoredItem, reason: PickReason) -> ScoredItem:
    if any(r.code == reason.code for r in item.reasons):
        return item
    return item.model_copy(update={"reasons": (*item.reasons, reason)})

def _slots(top: int, ratio: float, n: int) -> tuple[int, int] | None:
    # (n_exploit, n_explore), or None to fall back to pure top-N exploit.
    if ratio <= 0 or n <= top:
        return None
    n_explore = min(max(1, round(top * ratio)), top - 1, n - top)
    if n_explore <= 0:
        return None
    return top - n_explore, n_explore

class Explorer(Protocol):
    def choose(self, window: list[ScoredItem], top: int, lens: str = "") -> list[ScoredItem]: ...

class EpsilonExplorer:
    # Reserve a fraction of slots for a score-weighted stochastic pick from below the cut.
    def __init__(self, ratio: float | None = None, rng: random.Random | None = None):
        self.ratio = _config_ratio() if ratio is None else float(ratio)
        self.rng = rng or random

    @staticmethod
    def _weighted_sample(items: list[ScoredItem], k: int,
                         rng: random.Random) -> list[ScoredItem]:
        pool = list(items)
        weights = [max(float(d.score), 1.0) for d in pool]
        out: list[ScoredItem] = []
        for _ in range(min(k, len(pool))):
            i = rng.choices(range(len(pool)), weights=weights, k=1)[0]
            out.append(pool.pop(i))
            weights.pop(i)
        return out

    def choose(self, window: list[ScoredItem], top: int, lens: str = "") -> list[ScoredItem]:
        slots = _slots(top, self.ratio, len(window))
        if slots is None:
            return window[:top]
        n_exploit, n_explore = slots
        explored = [_append_reason(it, _EXPLORE_REASON)
                    for it in self._weighted_sample(window[n_exploit:], n_explore, self.rng)]
        chosen = window[:n_exploit] + explored
        chosen.sort(key=lambda d: d.score, reverse=True)
        return chosen

class ThompsonExplorer:
    # Contextual exploration via Thompson sampling: each source is a Bernoulli arm with a
    # Beta(1+keeps, 1+skips) posterior from the lens's feedback. We draw one sample per source
    # per round and fill the explore slots with the highest-sampled sources. Under-sampled
    # sources have wide posteriors, so they surface often early (cold start) and less as
    # evidence accrues -- self-tuning, no fixed schedule.
    def __init__(self, kb, ratio: float | None = None, rng: random.Random | None = None):
        self.kb = kb
        self.ratio = _config_ratio() if ratio is None else float(ratio)
        self.rng = rng or random

    def choose(self, window: list[ScoredItem], top: int, lens: str = "") -> list[ScoredItem]:
        slots = _slots(top, self.ratio, len(window))
        if slots is None:
            return window[:top]
        n_exploit, n_explore = slots
        candidates = window[n_exploit:]
        try:
            counts = self.kb.source_feedback_counts(lens) if lens else {}
        except Exception:
            counts = {}
        theta: dict[int, float] = {}
        for it in candidates:
            sid = it.source_id
            if sid not in theta:
                succ, fail = counts.get(sid, (0.0, 0.0))
                theta[sid] = self.rng.betavariate(1.0 + succ, 1.0 + fail)
        ranked = sorted(candidates, key=lambda it: theta.get(it.source_id, 0.0), reverse=True)
        explored = [_append_reason(it, _EXPLORE_REASON) for it in ranked[:n_explore]]
        chosen = window[:n_exploit] + explored
        chosen.sort(key=lambda d: d.score, reverse=True)
        return chosen
