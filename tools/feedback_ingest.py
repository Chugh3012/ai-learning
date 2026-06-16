#!/usr/bin/env python3
"""ai-scout feedback ingest + affinity (P7) — pluggable module, called by kb_sync.

Closes the loop: the Azure Function records email gestures as events in the `feedbackevents`
table (decoupled from the KB). Once a day this module drains those events into the owned KB
and recomputes a small, bounded ranking *affinity* per item — so sources and topics you like
rise in tomorrow's digest, and ones you dislike sink.

The math is deliberately not novel: it mirrors NewsBlur's proven "intelligence trainer" —
feedback is *additive affinity*, not ML. Each gesture contributes a weight; we average those
to a per-source and per-topic affinity in [-1, 1], then add a bounded point budget to the
relevance score. LLM relevance (0-100) still dominates; feedback only nudges (~±20 max).

Idempotent: feedback signals and affinity are fully reconciled from the events table each run
(DELETE + re-INSERT), so re-running — or a changed vote (👍→👎) — always converges, never
double-counts.

Passwordless: DefaultAzureCredential (az login locally, OIDC managed identity in CI). The
runner has Storage Table Data Contributor on the function storage account. No keys.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

CFG = Path(__file__).resolve().parent.parent / "config" / "feedback.json"
# events table RowKey suffix -> KB signal kind prefix (namespaced per user at write time)
_ROW_TO_KIND = {"vote": "fb_vote", "save": "fb_save", "click": "fb_click"}


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _load_cfg() -> tuple[dict[str, float], dict[str, float]]:
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    return cfg.get("weights", {}), cfg.get("influence", {})


def _drain_events(account: str) -> list[tuple[int, str, str, float]]:
    """Read all feedback events. Returns [(item_id, user, row, value)]. Events are keyed
    PartitionKey=item_id, RowKey='<user>:<row>' so each user's vote toggles independently."""
    from azure.data.tables import TableServiceClient
    from azure.identity import DefaultAzureCredential

    table = TableServiceClient(
        endpoint=f"https://{account}.table.core.windows.net",
        credential=DefaultAzureCredential(),
    ).get_table_client("feedbackevents")
    out: list[tuple[int, str, str, float]] = []
    for e in table.list_entities():
        try:
            rk = str(e["RowKey"])
            user = str(e.get("user", "")) or (rk.split(":", 1)[0] if ":" in rk else "primary")
            row = rk.split(":", 1)[1] if ":" in rk else rk
            out.append((int(e["PartitionKey"]), user, row, float(e["value"])))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def ingest_feedback(con: sqlite3.Connection, account: str) -> int:
    """Drain events -> per-user KB feedback signals, then recompute each user's affinity.
    Signals are namespaced per user (fb_vote:<id> ...) so users personalize independently.
    Returns the number of feedback events ingested (0 if unavailable). Never raises."""
    if not account:
        return 0
    try:
        events = _drain_events(account)
    except Exception as e:  # noqa: BLE001 — optional stage, never break the pipeline
        print(f"feedback: skipped (events unavailable: {e})")
        return 0

    now = int(time.time())
    users = sorted({user for _, user, _, _ in events})
    for user in users:
        # Full reconcile of this user's feedback signals from the events table (idempotent).
        con.execute(
            "DELETE FROM signal WHERE kind IN (?,?,?)",
            (f"fb_vote:{user}", f"fb_save:{user}", f"fb_click:{user}"),
        )
        con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
            [(item_id, f"{_ROW_TO_KIND[row]}:{user}", val, now)
             for item_id, u, row, val in events if u == user and row in _ROW_TO_KIND],
        )
        con.commit()
        _recompute_affinity(con, user, now)
    print(f"feedback: ingested {len(events)} events for {len(users)} user(s)")
    return len(events)


def _recompute_affinity(con: sqlite3.Connection, user: str, now: int) -> None:
    """Recompute and persist a bounded 'affinity:<user>' signal per rank-eligible item."""
    weights, influence = _load_cfg()
    w_vote = float(weights.get("vote", 1.0))
    w_save = float(weights.get("save", 0.5))
    w_click = float(weights.get("click", 0.25))
    infl_src = float(influence.get("source", 12))
    infl_topic = float(influence.get("topic", 8))

    # Per-item raw feedback score from this user's reconciled fb_*:<user> signals.
    raw: dict[int, float] = {}
    for item_id, vote, save, click in con.execute(
        "SELECT item_id, "
        "SUM(CASE WHEN kind=?  THEN value END), "
        "SUM(CASE WHEN kind=?  THEN value END), "
        "SUM(CASE WHEN kind=? THEN value END) "
        "FROM signal WHERE kind IN (?,?,?) GROUP BY item_id",
        (f"fb_vote:{user}", f"fb_save:{user}", f"fb_click:{user}",
         f"fb_vote:{user}", f"fb_save:{user}", f"fb_click:{user}"),
    ).fetchall():
        raw[item_id] = w_vote * (vote or 0) + w_save * (save or 0) + w_click * (click or 0)

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
    con.execute("DELETE FROM signal WHERE kind=?", (f"affinity:{user}",))
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
            inserts.append((item_id, f"affinity:{user}", points, now))
    if inserts:
        con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)", inserts
        )
    con.commit()
