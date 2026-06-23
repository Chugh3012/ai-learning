from __future__ import annotations

import numpy as np

from prism.lib.config import config_json

def novelty_weight() -> float:
    try:
        return float(config_json("personalization.json").get("novelty_weight", 0.0))
    except Exception:
        return 0.0

def novelty_penalties(history_vecs: list[bytes], cand_vecs: dict[int, bytes],
                      weight: float) -> dict[int, float]:
    # Penalize each candidate by its closeness to what the reader was already sent, so editions
    # don't repeat near-duplicates. Penalty = weight * max cosine to history (vecs are normalized).
    if weight <= 0 or not cand_vecs:
        return {}
    hist = [np.frombuffer(b, dtype=np.float32) for b in history_vecs if b]
    if not hist:
        return {}
    mat = np.stack(hist)
    out: dict[int, float] = {}
    for iid, b in cand_vecs.items():
        if not b:
            continue
        out[iid] = weight * max(0.0, float(np.max(mat @ np.frombuffer(b, dtype=np.float32))))
    return out
