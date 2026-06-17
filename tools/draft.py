#!/usr/bin/env python3
"""Content drafting, called by kb_sync. Turns the highest-relevance KB items into HUMAN-REVIEW
drafts (KB `draft` table, status='pending') via a Foundry model. The content target is a named
profile in config/content.yml (default 'social'); the model returns JSON and the renderer prints
whatever keys the profile produces, so output shape is config-driven. Nothing is published —
publishing is a separate opt-in step. Incremental, cost-capped, passwordless.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

CONTENT_CFG = Path(__file__).resolve().parent.parent / "config" / "content.yml"


def _load_profile(name: str) -> dict:
    """Tiny reader for the flat profiles file (avoids a yaml dependency). Each profile may carry
    a `temperature` scalar and any number of `key: >` folded blocks (e.g. `instruction`, the
    production prompt, and `interest`, the optional SELECTION lens sentence)."""
    profiles: dict[str, dict] = {}
    cur: str | None = None
    block_key: str | None = None       # which `>` folded block we're currently collecting
    blocks: dict[str, list[str]] = {}

    def flush() -> None:
        if cur:
            for k, lines in blocks.items():
                profiles[cur][k] = " ".join(lines).strip()

    for raw in CONTENT_CFG.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        m = re.match(r"^  (\w[\w-]*):\s*$", raw)            # new profile
        if m:
            flush()
            cur, block_key, blocks = m.group(1), None, {}
            profiles[cur] = {"temperature": 0.6, "instruction": "", "interest": ""}
            continue
        t = re.match(r"^    temperature:\s*([\d.]+)\s*$", raw)
        if t and cur:
            profiles[cur]["temperature"] = float(t.group(1))
            block_key = None
            continue
        b = re.match(r"^    (\w[\w-]*):\s*>\s*$", raw)        # start a folded block
        if b and cur:
            block_key = b.group(1)
            blocks[block_key] = []
            continue
        if block_key and raw.startswith("      "):
            blocks[block_key].append(raw.strip())
    flush()
    if name not in profiles:
        raise KeyError(f"content profile '{name}' not found in {CONTENT_CFG.name}")
    return profiles[name]


def _client(endpoint: str):
    from foundry import openai_client
    return openai_client(endpoint)


def generate_drafts(con: sqlite3.Connection, endpoint: str, deployment: str, embed_model: str,
                    profile_name: str, min_score: int, max_drafts: int) -> int:
    """Reel/content SINK (on-demand): select items through the profile's lens, then PRODUCE a
    content kit for each. Selection reuses the shared filter (tools/selection.py) so this sink gets
    the same curation as delivery — interest match, dedup, diversity — instead of a raw
    top-relevance scan. The profile's `interest` is the lens (empty -> plain relevance pick).
    Producing marks sent:<profile> so an item is never re-drafted. Returns count drafted."""
    if not endpoint:
        return 0
    try:
        profile = _load_profile(profile_name)
    except (FileNotFoundError, KeyError) as e:
        print(f"draft: skipped ({e})")
        return 0

    from selection import select_items, mark_sent, _interest_weight
    interest_vec = None
    if profile.get("interest"):
        from embed import embed_interest
        interest_vec = embed_interest(endpoint, embed_model, profile["interest"])
    # Deterministic pick (explore_ratio=0): a content sink shouldn't gamble a production slot on
    # a wildcard. Lens id = profile name, so state lives under sent:<profile> / affinity:<profile>.
    selected = select_items(con, profile_name, max_drafts, float(min_score),
                            interest_vec, _interest_weight(), explore_ratio=0.0)
    # Belt-and-suspenders: skip anything already in the draft table (e.g. drafted before this
    # lens existed, so unmarked by sent:<profile>).
    drafted = {r[0] for r in con.execute("SELECT item_id FROM draft").fetchall()}
    rows = [(d["id"], d["title"], d["summary"]) for d in selected if d["id"] not in drafted]
    if not rows:
        print("draft: no new items above threshold")
        return 0

    try:
        client = _client(endpoint)
    except Exception as e:  # noqa: BLE001 — optional stage, never break the pipeline
        print(f"draft: skipped (client init failed: {e})")
        return 0

    now = int(time.time())
    made: list[int] = []
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
        made.append(item_id)
    con.commit()
    if made:
        mark_sent(con, profile_name, made)
    print(f"draft: created {len(made)} pending drafts (profile '{profile_name}')")
    return len(made)
