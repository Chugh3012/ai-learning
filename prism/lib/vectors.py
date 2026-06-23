from __future__ import annotations

import numpy as np

def normalize(v: list[float]) -> list[float]:
    a = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(a)) or 1.0
    return (a / n).tolist()

def pack(v: list[float]) -> bytes:
    a = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(a)
    if n:
        a = a / n
    return a.astype(np.float32).tobytes()

def unpack(b: bytes) -> list[float]:
    return np.frombuffer(b, dtype=np.float32).tolist()

def dot(a: list[float], b: list[float]) -> float:
    return float(np.dot(np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)))

def match_bonus(interest_vec: list[float] | None, vecs: dict[int, bytes],
                weight: float) -> dict[int, float]:
    if not interest_vec or not vecs:
        return {}
    ids = [iid for iid, b in vecs.items() if b]
    if not ids:
        return {}
    iv = np.asarray(interest_vec, dtype=np.float32)
    mat = np.stack([np.frombuffer(vecs[i], dtype=np.float32) for i in ids])
    cos = mat @ iv
    if len(cos) < 2:
        return {i: 0.0 for i in ids}
    std = float(cos.std()) or 1.0
    z = weight * (cos - float(cos.mean())) / std
    return {ids[k]: float(z[k]) for k in range(len(ids))}
