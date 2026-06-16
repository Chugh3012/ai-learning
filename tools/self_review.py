#!/usr/bin/env python3
"""Self-review, called by kb_sync (--self-review). Closes the builder's feedback loop without a
human and without requiring a PR: for each user flagged self_review in users.json, an LLM reads
the items just delivered to that user and votes keep (worth their attention) or skip (noise) on
each — recorded as a real vote event (outcome_feedback.record_votes), exactly like a human click,
so feedback_ingest folds it into affinity:<user>.

Why this exists: the gh-aw coding agent only emits feedback when it opens a PR, so the common
no-op run taught the loop nothing and the agent's per-item judgment was discarded. Now the
builder votes on every digest. Idempotent: an item is reviewed once (marked reviewed:<user> in
the KB), so re-runs don't re-vote. Passwordless; optional + graceful (no-op if unconfigured).
"""
from __future__ import annotations

import json
import sqlite3
import time

BATCH = 25


def _unreviewed(con: sqlite3.Connection, user: str) -> list[tuple[int, str, str]]:
    """Items delivered to this user (sent:<user>) not yet self-reviewed (reviewed:<user>)."""
    return con.execute(
        "SELECT i.id, i.title, i.summary FROM item i "
        "JOIN signal s ON s.item_id=i.id AND s.kind=? "
        "WHERE NOT EXISTS (SELECT 1 FROM signal r WHERE r.item_id=i.id AND r.kind=?) "
        "GROUP BY i.id",
        (f"sent:{user}", f"reviewed:{user}"),
    ).fetchall()


def _judge(endpoint: str, model: str, interest: str, rows: list[tuple[int, str, str]]) -> dict[int, bool]:
    """Return {item_id: keep?} — True = worth the user's attention, False = noise."""
    try:
        from foundry import openai_client, log_usage
        client = openai_client(endpoint)
    except Exception as e:  # noqa: BLE001
        print(f"self-review: client unavailable ({e})")
        return {}
    import re
    def clean(t):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t or "")).strip()[:300]
    listing = "\n".join(f"[{i}] {t[:160]} — {clean(s)}" for i, t, s in rows)
    system = (
        "You are the maintainer of an AI/LLM pipeline, triaging a feed for YOUR interest:\n"
        f"  {interest}\n"
        "For each item decide KEEP (genuinely worth your attention — a technique, release, or "
        "idea relevant to that interest you'd want to read or could apply) or SKIP (off-interest, "
        "generic, or noise). Be selective; most items are SKIP. Return ONLY JSON: "
        '{"v":[{"id":<int>,"k":<true|false>}, ...]} for every id.'
    )
    out: dict[int, bool] = {}
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        sub = "\n".join(f"[{i}] {t[:160]} — {clean(s)}" for i, t, s in batch)
        try:
            resp = client.chat.completions.create(
                model=model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": sub}], max_tokens=900)
            log_usage("self-review", resp)
            for v in json.loads(resp.choices[0].message.content).get("v", []):
                out[int(v["id"])] = bool(v["k"])
        except Exception as e:  # noqa: BLE001
            print(f"self-review: batch failed ({e})")
            break
    return out


def self_review(con: sqlite3.Connection, users: list[dict], env: dict,
                endpoint: str, model: str) -> int:
    """Vote keep/skip on freshly delivered items for each self_review user. Returns votes cast."""
    account = env.get("FEEDBACK_STORAGE", "")
    if not (endpoint and account):
        return 0
    from outcome_feedback import record_votes
    now = int(time.time())
    total = 0
    for user in users:
        if not user.get("self_review"):
            continue
        uid = user["id"]
        rows = _unreviewed(con, uid)
        if not rows:
            continue
        verdicts = _judge(endpoint, model, user.get("interest", ""), rows)
        if not verdicts:
            continue
        keep = [i for i, k in verdicts.items() if k]
        skip = [i for i, k in verdicts.items() if not k]
        record_votes(account, uid, keep, 1.0)
        record_votes(account, uid, skip, -1.0)
        con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
            [(i, f"reviewed:{uid}", 1.0, now) for i in verdicts],
        )
        con.commit()
        total += len(verdicts)
        print(f"self-review: {uid} kept {len(keep)}, skipped {len(skip)} of {len(rows)} delivered")
    return total
