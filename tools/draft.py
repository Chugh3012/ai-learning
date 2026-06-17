#!/usr/bin/env python3
"""Content production SINK. Turns already-SELECTED KB items into HUMAN-REVIEW drafts (KB `draft`
table, status='pending') via a Foundry model. The output shape is a named FORMAT in
config/content.yml (e.g. 'reel', 'social'): the model returns JSON and the review file renders
whatever keys it produces, so a new format changes output without code. Selection (which items)
lives in the orchestrator + shared filter; this module only PRODUCES. Nothing is published.
Incremental, cost-capped, passwordless.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

CONTENT_CFG = Path(__file__).resolve().parent.parent / "config" / "content.yml"


def _load_format(name: str) -> dict:
    """Tiny reader for the flat formats file (avoids a yaml dependency). Each format may carry
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
        raise KeyError(f"content format '{name}' not found in {CONTENT_CFG.name}")
    return profiles[name]


def _client(endpoint: str):
    from foundry import openai_client
    return openai_client(endpoint)


def produce(con: sqlite3.Connection, endpoint: str, deployment: str,
            profile: "object", items: list[dict]) -> int:
    """Produce a content kit per ALREADY-SELECTED item using the profile's content FORMAT
    (config/content.yml, named by `profile.format`). Selection (which items) happened upstream in
    the orchestrator + shared filter; this only renders the artifact and stores it pending review.
    The orchestrator owns sent:<lens> marking. Returns count produced (0 = nothing/unconfigured)."""
    if not endpoint or not items:
        return 0
    fmt_name = getattr(profile, "format", None)
    if not fmt_name:
        print("draft: profile has no `format` — nothing to produce")
        return 0
    try:
        fmt = _load_format(fmt_name)
    except (FileNotFoundError, KeyError) as e:
        print(f"draft: skipped ({e})")
        return 0
    try:
        client = _client(endpoint)
    except Exception as e:  # noqa: BLE001 — optional stage, never break the pipeline
        print(f"draft: skipped (client init failed: {e})")
        return 0

    now = int(time.time())
    made = 0
    for d in items:
        item_id, title, summary = d["id"], d["title"], d.get("summary", "")
        try:
            resp = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": fmt["instruction"]},
                    {"role": "user", "content": f"Title: {title}\n\nSummary: {(summary or '')[:1200]}"},
                ],
                temperature=fmt["temperature"],
                response_format={"type": "json_object"},
                max_tokens=600,
            )
            body = json.loads(resp.choices[0].message.content)
        except Exception as e:  # noqa: BLE001
            print(f"draft: stopped ({e})")
            break
        body["_format"] = fmt_name
        con.execute(
            "INSERT OR IGNORE INTO draft(item_id,status,body,created_at) VALUES(?,?,?,?)",
            (item_id, "pending", json.dumps(body), now),
        )
        made += 1
    con.commit()
    print(f"draft: produced {made} pending kit(s) (format '{fmt_name}')")
    return made
