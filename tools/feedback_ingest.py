#!/usr/bin/env python3
"""Feedback ingest, called by kb_sync. Drains the Function's gesture events (Azure Tables) into
per-LENS KB signals and recomputes a small bounded affinity per source/topic (additive,
NewsBlur-style — weights in config/feedback.json; LLM relevance still dominates). Also ages out
implicit negatives: items delivered but not acted on within skip_days. Fully reconciled each run
(idempotent). Passwordless (DefaultAzureCredential).

Everything is keyed by LENS (`<user_id>:<profile_id>`), the opaque namespace carried on each
event. Only CLICK-bearing lenses (email/digest profiles) are reconciled — a 'draft' profile has
no click loop, so it is never aged into false negatives.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

CFG = Path(__file__).resolve().parent.parent / "config" / "feedback.json"
# events table 'action' -> KB signal kind prefix (namespaced per lens at write time)
_ROW_TO_KIND = {"vote": "fb_vote", "save": "fb_save", "click": "fb_click"}
_ACTION_TO_ROW = {"up": "vote", "down": "vote", "save": "save", "click": "click"}


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _load_cfg() -> tuple[dict[str, float], dict[str, float], int]:
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    return cfg.get("weights", {}), cfg.get("influence", {}), int(cfg.get("skip_days", 2))


def _drain_events(account: str) -> list[tuple[int, str, str, float]]:
    """Read all feedback events. Returns [(item_id, lens, row, value)] where lens is the opaque
    `<user_id>:<profile_id>` namespace the gesture was minted for. Events without a `lens` field
    (legacy, pre-surrogate-id) are ignored — the loop is fresh, not retro-compatible."""
    from azure.data.tables import TableServiceClient
    from azure.identity import DefaultAzureCredential

    table = TableServiceClient(
        endpoint=f"https://{account}.table.core.windows.net",
        credential=DefaultAzureCredential(),
    ).get_table_client("feedbackevents")
    out: list[tuple[int, str, str, float]] = []
    for e in table.list_entities():
        try:
            lens = str(e.get("lens", ""))
            row = _ACTION_TO_ROW.get(str(e.get("action", "")))
            if not lens or row is None:
                continue
            out.append((int(e["PartitionKey"]), lens, row, float(e["value"])))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def ingest_feedback(con: sqlite3.Connection, account: str, feedback_lenses: set[str]) -> int:
    """Drain events -> per-lens KB feedback signals, then recompute each lens's affinity. Only the
    CLICK-bearing `feedback_lenses` (email/digest profiles) are reconciled. Signals are namespaced
    per lens (fb_vote:<lens> ...) so profiles personalize independently. Returns the number of
    events ingested (0 if unavailable). Never raises."""
    try:
        events = _drain_events(account) if account else []
    except Exception as e:  # noqa: BLE001 — optional stage, never break the pipeline
        print(f"feedback: events unavailable ({e}); aging skips from local KB only")
        events = []

    now = int(time.time())
    lenses = sorted(feedback_lenses)
    for lens in lenses:
        # Full reconcile of this lens's gesture signals from the events table (idempotent).
        con.execute(
            "DELETE FROM signal WHERE kind IN (?,?,?)",
            (f"fb_vote:{lens}", f"fb_save:{lens}", f"fb_click:{lens}"),
        )
        con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
            [(item_id, f"{_ROW_TO_KIND[row]}:{lens}", val, now)
             for item_id, l, row, val in events if l == lens and row in _ROW_TO_KIND],
        )
        _age_out_skips(con, lens, now)
        con.commit()
        _recompute_affinity(con, lens, now)
    print(f"feedback: ingested {len(events)} events across {len(lenses)} lens(es)")
    return len(events)


def _age_out_skips(con: sqlite3.Connection, lens: str, now: int) -> None:
    """Implicit-negative: items delivered to this lens (sent:<lens>) older than skip_days with NO
    explicit gesture become a mild 'fb_skip:<lens>' signal — 'shown, reviewed, not acted on'.
    Recomputed from scratch each run (idempotent): a later vote/save/click removes the skip."""
    _, _, skip_days = _load_cfg()
    cutoff = now - int(skip_days) * 86400
    con.execute("DELETE FROM signal WHERE kind=?", (f"fb_skip:{lens}",))
    rows = con.execute(
        "SELECT DISTINCT s.item_id FROM signal s "
        "WHERE s.kind=? AND s.ts < ? "
        "AND NOT EXISTS (SELECT 1 FROM signal a WHERE a.item_id=s.item_id "
        "  AND a.kind IN (?,?,?))",
        (f"sent:{lens}", cutoff, f"fb_vote:{lens}", f"fb_save:{lens}", f"fb_click:{lens}"),
    ).fetchall()
    if rows:
        con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
            [(item_id, f"fb_skip:{lens}", 1.0, now) for (item_id,) in rows],
        )


def _recompute_affinity(con: sqlite3.Connection, lens: str, now: int) -> None:
    """Recompute and persist a bounded 'affinity:<lens>' signal per rank-eligible item."""
    weights, influence, _ = _load_cfg()
    w_vote = float(weights.get("vote", 1.0))
    w_save = float(weights.get("save", 0.5))
    w_click = float(weights.get("click", 0.25))
    w_skip = float(weights.get("skip", -0.3))
    infl_src = float(influence.get("source", 12))
    infl_topic = float(influence.get("topic", 8))

    # Per-item raw feedback score from this lens's reconciled fb_*:<lens> signals.
    raw: dict[int, float] = {}
    for item_id, vote, save, click, skip in con.execute(
        "SELECT item_id, "
        "SUM(CASE WHEN kind=? THEN value END), "
        "SUM(CASE WHEN kind=? THEN value END), "
        "SUM(CASE WHEN kind=? THEN value END), "
        "SUM(CASE WHEN kind=? THEN value END) "
        "FROM signal WHERE kind IN (?,?,?,?) GROUP BY item_id",
        (f"fb_vote:{lens}", f"fb_save:{lens}", f"fb_click:{lens}", f"fb_skip:{lens}",
         f"fb_vote:{lens}", f"fb_save:{lens}", f"fb_click:{lens}", f"fb_skip:{lens}"),
    ).fetchall():
        raw[item_id] = (w_vote * (vote or 0) + w_save * (save or 0)
                        + w_click * (click or 0) + w_skip * (skip or 0))

    # Aggregate raw scores into per-source and per-topic affinity in [-1, 1].
    src_sum: dict[int, float] = {}
    src_cnt: dict[int, int] = {}
    for item_id, source_id in con.execute(
        "SELECT id, source_id FROM item WHERE id IN (%s)"
        % (",".join("?" * len(raw)) or "NULL"), tuple(raw)
    ).fetchall() if raw else []:
        src_sum[source_id] = src_sum.get(source_id, 0.0) + raw[item_id]
        src_cnt[source_id] = src_cnt.get(source_id, 0) + 1

    topic_sum: dict[str, float] = {}
    topic_cnt: dict[str, int] = {}
    for item_id, topic in con.execute(
        "SELECT item_id, topic FROM tag WHERE item_id IN (%s)"
        % (",".join("?" * len(raw)) or "NULL"), tuple(raw)
    ).fetchall() if raw else []:
        topic_sum[topic] = topic_sum.get(topic, 0.0) + raw[item_id]
        topic_cnt[topic] = topic_cnt.get(topic, 0) + 1

    src_aff = {s: _clamp(src_sum[s] / src_cnt[s]) for s in src_sum}
    topic_aff = {t: _clamp(topic_sum[t] / topic_cnt[t]) for t in topic_sum}

    # Persist a bounded affinity per rank-eligible item (those with a relevance score).
    con.execute("DELETE FROM signal WHERE kind=?", (f"affinity:{lens}",))
    rows = con.execute(
        "SELECT i.id, i.source_id, GROUP_CONCAT(t.topic) FROM item i "
        "JOIN signal r ON r.item_id=i.id AND r.kind='relevance' "
        "LEFT JOIN tag t ON t.item_id=i.id GROUP BY i.id, i.source_id"
    ).fetchall()
    inserts = []
    for item_id, source_id, topics in rows:
        s_aff = src_aff.get(source_id, 0.0)
        topic_list = [t for t in (topics or "").split(",") if t]
        t_aff = (sum(topic_aff.get(t, 0.0) for t in topic_list) / len(topic_list)
                 if topic_list else 0.0)
        points = infl_src * s_aff + infl_topic * t_aff
        if points:
            inserts.append((item_id, f"affinity:{lens}", points, now))
    if inserts:
        con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)", inserts
        )
    con.commit()
