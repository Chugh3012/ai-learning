#!/usr/bin/env python3
"""Relevance ranking, called by kb_sync. Scores each new KB item 0–100 for how strongly it
shows a new/practical way to USE AI — the shared quality gate — via a Foundry model, writing
signal kind='relevance'. Incremental (only unscored recent items), batched, cost-capped,
graceful (no-op if unconfigured), passwordless. The calibrated rubric is the SYSTEM prompt below.
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
    "You are the curator of a daily AI/LLM brief. Every item already comes from an AI-focused "
    "source, so your job is NOT 'is this about AI' — it is 'is this SIGNAL worth a curious "
    "reader's attention, or NOISE?'. Reward signal broadly; demote noise hard. Rate each 0-100.\n"
    "FIRST GATE: if an item is genuinely NOT about AI/ML/LLMs (generic software, a game, an "
    "unrelated topic), score it 0-10 no matter how interesting.\n"
    "SIGNAL is any of: a concrete technique / tool / workflow / prompt-or-instruction craft you "
    "could use; a genuinely significant development you'd want to know about — a new model or "
    "product, a real new capability, or a notable shift; a clear explanation of how AI works or "
    "behaves; or a sharp idea about USING or UNDERSTANDING AI. NOISE is: version-bump / changelog "
    "churn, funding / PR / marketing, hype with nothing to learn, rehashed news, AI merely applied "
    "inside an unrelated domain (medicine, finance, biology, pure math), or pure ML / architecture "
    "/ math theory with no usable or significant takeaway.\n"
    "Calibrate to this rubric and USE THE FULL RANGE — most are NOT a 90:\n"
    "  85-100: high signal — a usable technique/craft you could act on now, OR a genuinely "
    "significant AI development (a new model, real new capability, or notable shift) worth knowing.\n"
    "  65-84:  solid signal — a useful applied insight, a notable real product/release, a "
    "how-someone-actually-uses-AI story, or a clear explanation of how AI works or behaves.\n"
    "  40-64:  mild signal — on-topic but general, early, shallow, or merely fun/interesting with "
    "little to take away.\n"
    "  15-39:  low signal — incremental version/changelog churn, AI applied inside an unrelated "
    "domain, or pure ML/math/architecture theory with no usable or significant takeaway.\n"
    "  0-14:   noise — non-AI, pure funding/policy/PR, or hype with nothing to learn.\n"
    "Be BROAD about what counts as signal (useful, significant, OR insightful — not just how-tos) "
    "but STRICT about noise. Spread the scores so the batch is genuinely ranked, not clustered. "
    "Judge the whole batch relative to each other. Return ONLY compact JSON: "
    "{\"scores\":[{\"id\":<int>,\"s\":<0-100>}, ...]} for every id given."
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
