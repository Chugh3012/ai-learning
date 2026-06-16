#!/usr/bin/env python3
"""ai-scout embeddings (two-tower personalization) — the scalable, per-user lens.

This is the industry-standard recsys pattern (YouTube, Etsy, Zalando, Spotify), sized down:
  * ITEM TOWER  — embed each item ONCE (shared across all users), stored in the KB.
  * USER TOWER  — embed each user's one-sentence `interest` ONCE.
  * MATCH       — per-user relevance bonus = a cheap dot product. No LLM call per user.
Cost is O(items + users), never O(items × users): the 100th user is a single sentence embed.

The shared `relevance` score stays the query-independent QUALITY gate ("is this substantive
AI at all"); the interest match STEERS each user's pick on top of it (so e.g. a paper on
better prompting surfaces for the builder by semantic match — not by hand-filtering sources).

Vectors are text-embedding-3-large (Azure's latest/most-capable embedding model) reduced to
256 dims via the `dimensions` param — cheap, tiny, still strong — L2-normalized at store time so
a match is a plain dot product. Pure stdlib math (array + math) — no numpy dependency.
Passwordless throughout (DefaultAzureCredential). Every step degrades gracefully: if the
embedding deployment is unset/unavailable, items simply stay unembedded and delivery falls
back to relevance + feedback only.
"""
from __future__ import annotations

import array
import html
import math
import re
import sqlite3
import time

BATCH = 128
DIMS = 256
_TXT_LIMIT = 1000


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:_TXT_LIMIT]


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def pack(v: list[float]) -> bytes:
    """L2-normalize then store as float32 bytes (so a later match is just a dot product)."""
    return array.array("f", _normalize(v)).tobytes()


def unpack(b: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(b)
    return a.tolist()


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def embed_unembedded(con: sqlite3.Connection, endpoint: str, deployment: str,
                     days: int, max_items: int) -> int:
    """Item tower: embed recent items that have no embedding yet (incremental, capped).
    Returns count embedded (0 if embeddings unavailable). Never raises."""
    if not endpoint:
        return 0
    cutoff = int(time.time()) - days * 86400
    rows = con.execute(
        "SELECT i.id, i.title, i.summary FROM item i "
        "WHERE i.published >= ? AND NOT EXISTS "
        "(SELECT 1 FROM embedding e WHERE e.item_id=i.id) "
        "ORDER BY i.published DESC LIMIT ?",
        (cutoff, max_items),
    ).fetchall()
    if not rows:
        return 0

    from foundry import embed as _embed
    now = int(time.time())
    done = 0
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        texts = [f"{t}\n{_clean(s)}" if _clean(s) else str(t) for _, t, s in batch]
        try:
            vecs = _embed(endpoint, deployment, texts, DIMS)
        except Exception as e:  # noqa: BLE001 — embeddings are optional, never break the pipeline
            print(f"embed: batch failed, stopping ({e})")
            break
        con.executemany(
            "INSERT OR REPLACE INTO embedding(item_id,vec,ts) VALUES(?,?,?)",
            [(batch[i][0], pack(vecs[i]), now) for i in range(len(batch))],
        )
        con.commit()
        done += len(batch)
    print(f"embed: embedded {done} items")
    return done


def embed_interest(endpoint: str, deployment: str, interest: str) -> list[float] | None:
    """User tower: embed one user's interest sentence (normalized). None on any failure."""
    if not (endpoint and interest):
        return None
    try:
        from foundry import embed as _embed
        return _normalize(_embed(endpoint, deployment, [interest], DIMS)[0])
    except Exception as e:  # noqa: BLE001
        print(f"embed: interest embed failed ({e}); no interest steering this run")
        return None


def match_bonus(interest_vec: list[float] | None, vecs: dict[int, bytes],
                weight: float) -> dict[int, float]:
    """Per-item interest bonus = weight × z-scored cosine(interest, item) across the candidate
    pool. Mean-centering gives real ± dynamic range despite embedding cosines being compressed:
    on-interest items get a positive lift, off-interest a penalty, average items ~0. Returns
    {item_id: bonus}; all-zero when there's no interest vector or no embeddings yet."""
    if not interest_vec or not vecs:
        return {}
    cos = {iid: dot(interest_vec, unpack(b)) for iid, b in vecs.items() if b}
    if len(cos) < 2:
        return {iid: 0.0 for iid in cos}
    vals = list(cos.values())
    mean = sum(vals) / len(vals)
    std = math.sqrt(sum((c - mean) ** 2 for c in vals) / len(vals)) or 1.0
    return {iid: weight * (c - mean) / std for iid, c in cos.items()}
