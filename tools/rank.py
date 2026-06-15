#!/usr/bin/env python3
"""ai-scout relevance ranking (Layer C/P4) — pluggable module, called by kb_sync.

Scores how strongly each item shows a *new or useful way to USE AI/LLMs* (not generic
news) on a 0-100 scale, via a cheap nano model deployed in a Microsoft Foundry project.
Scores are written to the KB `signal` table (kind='relevance') — no schema change (the
seam was reserved in P3).

Uses the Foundry SDK exactly per the Microsoft quickstart: build an AIProjectClient on the
project endpoint, then `get_openai_client()` for an authenticated, passwordless OpenAI
client. No keys, no classic endpoints, no hand-rolled token plumbing.

Design for cost & sleekness:
- INCREMENTAL: only scores recent items with no existing relevance signal. Never re-scans.
- Batched: many items per request, tiny JSON out. Sub-cent per run; $0 when idle.
- Passwordless: DefaultAzureCredential (az login locally, OIDC managed identity in CI).
- Graceful: if the endpoint is unset or a call fails, returns 0 and the digest falls back
  to recency ordering. The pipeline never breaks because ranking is optional.
"""
from __future__ import annotations

import json
import sqlite3
import time

SCORE_SCALE = 100
BATCH = 25
SYSTEM = (
    "You rate tech/AI feed items by how strongly each shows a NEW or PRACTICAL way to USE "
    "AI/LLMs (tools, techniques, workflows, agent patterns, prompting, real applications). "
    "Generic funding/policy/benchmark news scores low; concrete 'how to use AI' scores high. "
    "Return ONLY compact JSON: {\"scores\":[{\"id\":<int>,\"s\":<0-100>}, ...]} for every id given."
)


def _client(endpoint: str):
    """Return an authenticated OpenAI client from the Foundry project (passwordless)."""
    from foundry import openai_client
    return openai_client(endpoint)


def _score_batch(client, deployment: str, rows: list[tuple[int, str]]) -> dict[int, int]:
    listing = "\n".join(f'{i}: {t[:240]}' for i, t in rows)
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Rate these items:\n{listing}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=900,
    )
    data = json.loads(resp.choices[0].message.content)
    out: dict[int, int] = {}
    for r in data.get("scores", []):
        try:
            out[int(r["id"])] = max(0, min(SCORE_SCALE, int(r["s"])))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def score_unscored(con: sqlite3.Connection, endpoint: str, deployment: str,
                   days: int, max_items: int) -> int:
    """Score recent, not-yet-scored items. Returns count scored (0 if ranking unavailable)."""
    if not endpoint:
        return 0
    cutoff = int(time.time()) - days * 86400
    rows = con.execute(
        "SELECT i.id, i.title FROM item i "
        "WHERE i.published >= ? AND NOT EXISTS "
        "(SELECT 1 FROM signal s WHERE s.item_id=i.id AND s.kind='relevance') "
        "ORDER BY i.published DESC LIMIT ?",
        (cutoff, max_items),
    ).fetchall()
    if not rows:
        return 0

    try:
        client = _client(endpoint)
    except Exception as e:  # noqa: BLE001 — ranking is optional, never break the pipeline
        print(f"rank: skipped (client init failed: {e})")
        return 0

    now = int(time.time())
    scored = 0
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        try:
            scores = _score_batch(client, deployment, batch)
        except Exception as e:  # noqa: BLE001
            print(f"rank: batch failed, stopping ({e})")
            break
        for item_id, _ in batch:
            if item_id in scores:
                con.execute(
                    "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                    (item_id, "relevance", float(scores[item_id]), now),
                )
                scored += 1
        con.commit()
    print(f"rank: scored {scored} items")
    return scored
