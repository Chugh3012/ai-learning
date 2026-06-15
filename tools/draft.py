#!/usr/bin/env python3
"""ai-scout content drafting (Layer E / P5) — pluggable, called by kb_sync.

Turns the highest-relevance KB items into HUMAN-REVIEW content drafts using the same
Microsoft Foundry project + nano model. Drafts land in the KB `draft` table with
status='pending'. Nothing is published.

Platform-agnostic by design: the *content target* is a named profile in config/content.yml
(default 'social'). Adding a new target (LinkedIn, blog, newsletter, ...) = add a profile
block there — no code change. The model returns JSON; the review renderer prints whatever
keys the profile produces, so output shape is config-driven too.

Actual publishing to any platform is a separate, opt-in step (not built): it needs that
platform's account + auth (and, for Instagram, app review + public media hosting), none of
which fit the passwordless/owned model. We keep a human in the loop here.

Design (matches rank.py): Foundry SDK get_openai_client(), passwordless, incremental
(only un-drafted items above a score threshold), cost-capped via --draft-max.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

CONTENT_CFG = Path(__file__).resolve().parent.parent / "config" / "content.yml"


def _load_profile(name: str) -> dict:
    """Tiny reader for the flat profiles file (avoids a yaml dependency)."""
    profiles: dict[str, dict] = {}
    cur: str | None = None
    instr: list[str] = []
    in_instr = False
    for raw in CONTENT_CFG.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        m = re.match(r"^  (\w[\w-]*):\s*$", raw)
        if m:
            if cur:
                profiles[cur]["instruction"] = " ".join(instr).strip()
            cur, instr, in_instr = m.group(1), [], False
            profiles[cur] = {"temperature": 0.6, "instruction": ""}
            continue
        t = re.match(r"^    temperature:\s*([\d.]+)\s*$", raw)
        if t and cur:
            profiles[cur]["temperature"] = float(t.group(1))
            continue
        if re.match(r"^    instruction:\s*>\s*$", raw):
            in_instr = True
            continue
        if in_instr and raw.startswith("      "):
            instr.append(raw.strip())
    if cur:
        profiles[cur]["instruction"] = " ".join(instr).strip()
    if name not in profiles:
        raise KeyError(f"content profile '{name}' not found in {CONTENT_CFG.name}")
    return profiles[name]


def _client(endpoint: str):
    from foundry import openai_client
    return openai_client(endpoint)


def generate_drafts(con: sqlite3.Connection, endpoint: str, deployment: str,
                    profile_name: str, min_score: int, max_drafts: int) -> int:
    """Draft top un-drafted items with relevance >= min_score. Returns count drafted."""
    if not endpoint:
        return 0
    try:
        profile = _load_profile(profile_name)
    except (FileNotFoundError, KeyError) as e:
        print(f"draft: skipped ({e})")
        return 0

    rows = con.execute(
        "SELECT i.id, i.title, i.summary FROM item i "
        "JOIN signal s ON s.item_id=i.id AND s.kind='relevance' "
        "WHERE s.value >= ? AND NOT EXISTS "
        "(SELECT 1 FROM draft d WHERE d.item_id=i.id) "
        "ORDER BY s.value DESC LIMIT ?",
        (min_score, max_drafts),
    ).fetchall()
    if not rows:
        print("draft: no new items above threshold")
        return 0

    try:
        client = _client(endpoint)
    except Exception as e:  # noqa: BLE001 — optional stage, never break the pipeline
        print(f"draft: skipped (client init failed: {e})")
        return 0

    now = int(time.time())
    made = 0
    for item_id, title, summary in rows:
        try:
            resp = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": profile["instruction"]},
                    {"role": "user", "content": f"Title: {title}\n\nSummary: {(summary or '')[:1200]}"},
                ],
                temperature=profile["temperature"],
                response_format={"type": "json_object"},
                max_tokens=600,
            )
            body = json.loads(resp.choices[0].message.content)
        except Exception as e:  # noqa: BLE001
            print(f"draft: stopped ({e})")
            break
        body["_profile"] = profile_name
        con.execute(
            "INSERT OR IGNORE INTO draft(item_id,status,body,created_at) VALUES(?,?,?,?)",
            (item_id, "pending", json.dumps(body), now),
        )
        made += 1
    con.commit()
    print(f"draft: created {made} pending drafts (profile '{profile_name}')")
    return made
