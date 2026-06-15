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

import html
import json
import re
import sqlite3
import time

SCORE_SCALE = 100
BATCH = 25
SYSTEM = (
    "You are a strict curator for a daily brief about NEW, PRACTICAL ways to USE AI/LLMs "
    "(tools, techniques, workflows, agent patterns, prompting, real applications, shipped "
    "products). You rate each item 0-100.\n"
    "FIRST GATE: the item must be specifically about AI/ML/LLMs. If it is generic software, a "
    "library release, a game, or any non-AI topic, score it 0-10 no matter how interesting.\n"
    "For on-topic items, calibrate to this rubric and USE THE FULL RANGE — most are NOT a 90:\n"
    "  85-100: a concrete AI technique/tool/workflow a builder could apply this week.\n"
    "  65-84:  useful applied AI insight or a notable real AI product/release.\n"
    "  40-64:  on-topic but general, early, or shallow.\n"
    "  15-39:  academic AI paper or benchmark with no directly usable takeaway.\n"
    "  0-14:   non-AI, funding, policy, or hype.\n"
    "Bias HARD toward applied/hands-on over academic. A pure arXiv research paper tops out "
    "around 40 unless it describes a technique a practitioner could use directly. Spread the "
    "scores so the batch is genuinely ranked, not clustered. Judge the whole batch relative to "
    "each other. Return ONLY compact JSON: {\"scores\":[{\"id\":<int>,\"s\":<0-100>}, ...]} for "
    "every id given."
)


def _clean(text: str, limit: int = 300) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _client(endpoint: str):
    """Return an authenticated OpenAI client from the Foundry project (passwordless)."""
    from foundry import openai_client
    return openai_client(endpoint)


def _score_batch(client, deployment: str, rows: list[tuple[int, str, str]]) -> dict[int, int]:
    listing = "\n\n".join(
        f"[{i}] {t[:160]}" + (f"\n{_clean(s)}" if _clean(s) else "")
        for i, t, s in rows
    )
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Rank and rate these {len(rows)} items:\n{listing}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=900,
    )
    from foundry import log_usage
    log_usage("rank", resp)
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
        "SELECT i.id, i.title, i.summary FROM item i "
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
        for item_id, _title, _summary in batch:
            if item_id in scores:
                con.execute(
                    "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                    (item_id, "relevance", float(scores[item_id]), now),
                )
                scored += 1
        con.commit()
    print(f"rank: scored {scored} items")
    return scored
