from __future__ import annotations

import time

import numpy as np

from prism.lib.config import config_json
from prism.lib.vectors import normalize
from prism.repositories.knowledge import KnowledgeBase

def recency_weight(age_seconds: float, half_life_days: float) -> float:
    # Exponential time decay: a signal's weight halves every `half_life_days`.
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (max(0.0, age_seconds) / (half_life_days * 86400.0))

class TasteModel:
    # A per-lens taste vector learned from behaviour: the recency-weighted centroid of the
    # embeddings of items the reader engaged with, blended with their typed interest (which
    # carries cold start). Content-based user profile, no training. Falls back to the typed
    # interest when there is no engagement yet.
    def __init__(self, kb: KnowledgeBase, half_life_days: float | None = None,
                 blend: float | None = None):
        self.kb = kb
        taste = config_json("personalization.json").get("taste", {})
        weights = config_json("feedback.json").get("weights", {})
        self.half_life_days = (float(taste.get("half_life_days", 30))
                               if half_life_days is None else float(half_life_days))
        self.blend = float(taste.get("blend", 0.5)) if blend is None else float(blend)
        self.w_vote = float(weights.get("vote", 1.0))
        self.w_save = float(weights.get("save", 0.5))
        self.w_click = float(weights.get("click", 0.25))

    def _learned(self, lens: str, now: float) -> list[float] | None:
        try:
            rows = self.kb.engaged_with_embeddings(lens)
        except Exception:
            return None
        acc = None
        total = 0.0
        for _item_id, vec_b, vote, save, click, sent_ts in rows:
            if not vec_b:
                continue
            strength = (self.w_vote * (vote or 0) + self.w_save * (save or 0)
                        + self.w_click * (click or 0))
            if strength <= 0:
                continue
            w = strength * recency_weight(now - float(sent_ts or now), self.half_life_days)
            if w <= 0:
                continue
            v = np.frombuffer(vec_b, dtype=np.float32) * w
            acc = v if acc is None else acc + v
            total += w
        if acc is None or total <= 0:
            return None
        return normalize((acc / total).tolist())

    def user_vector(self, lens: str,
                    interest_vec: list[float] | None = None) -> list[float] | None:
        learned = self._learned(lens, time.time())
        if learned is None:
            return interest_vec
        if not interest_vec:
            return learned
        b = max(0.0, min(1.0, self.blend))
        mixed = (np.asarray(learned, dtype=np.float32) * b
                 + np.asarray(interest_vec, dtype=np.float32) * (1.0 - b))
        return normalize(mixed.tolist())
