"""Pure vector math for the two-tower interest match — stdlib only (array + math), no numpy.

Vectors are stored L2-normalized as float32 bytes, so a similarity is a plain dot product.
"""
from __future__ import annotations

import array
import math


def normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def pack(v: list[float]) -> bytes:
    """L2-normalize then store as float32 bytes (so a later match is just a dot product)."""
    return array.array("f", normalize(v)).tobytes()


def unpack(b: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(b)
    return a.tolist()


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def match_bonus(interest_vec: list[float] | None, vecs: dict[int, bytes],
                weight: float) -> dict[int, float]:
    """Per-item interest bonus = weight × z-scored cosine(interest, item) across the candidate
    pool. Mean-centering gives real ± dynamic range despite embedding cosines being compressed:
    on-interest items get a positive lift, off-interest a penalty, average items ~0. Returns
    {item_id: bonus}; empty when there's no interest vector or no embeddings yet."""
    if not interest_vec or not vecs:
        return {}
    cos = {iid: dot(interest_vec, unpack(b)) for iid, b in vecs.items() if b}
    if len(cos) < 2:
        return {iid: 0.0 for iid in cos}
    vals = list(cos.values())
    mean = sum(vals) / len(vals)
    std = math.sqrt(sum((c - mean) ** 2 for c in vals) / len(vals)) or 1.0
    return {iid: weight * (c - mean) / std for iid, c in cos.items()}
