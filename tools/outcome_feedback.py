#!/usr/bin/env python3
"""ai-scout outcome-as-feedback — the builder's POSITIVE feedback loop with ZERO clicks.

The agent (user 'builder') never clicks 👍/👎. Instead, the OUTCOME of its self-improvement
PR is the feedback: when a PR MERGES, the radar items it acted on were worth it (👍). The
negative side ("shown but not acted on") is owned by feedback_ingest's fb_skip rule, so this
tool records only the positive on merge — generalizing to any channel that can map an outcome
(merge, open-rate, reply) to a vote.

It writes events into the SAME `feedbackevents` table the Function uses (user='builder',
RowKey='builder:vote'), so the normal daily `feedback_ingest` turns them into affinity:builder
with no new code path. Passwordless: DefaultAzureCredential (OIDC in CI). Never raises fatally.

Usage (from the feedback-on-merge workflow):
  python tools/outcome_feedback.py --vote up   --items 1804,2327,11
  python tools/outcome_feedback.py --vote down --items 1804,2327,11
"""
from __future__ import annotations

import argparse
import os
import sys
import time


def record_votes(account: str, user: str, item_ids: list[int], value: float) -> int:
    """Write one vote event per item to the `feedbackevents` table (the gesture source of truth,
    same path a human click takes), so the daily feedback_ingest reconciles them into
    affinity:<user>. value > 0 = 👍, < 0 = 👎. Returns count written. Passwordless; never raises."""
    if not account or not item_ids:
        return 0
    action = "up" if value > 0 else "down"
    try:
        from azure.data.tables import TableServiceClient, UpdateMode
        from azure.identity import DefaultAzureCredential
        table = TableServiceClient(
            endpoint=f"https://{account}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        ).get_table_client("feedbackevents")
        now = int(time.time())
        for item_id in item_ids:
            table.upsert_entity(
                {"PartitionKey": str(item_id), "RowKey": f"{user}:vote", "user": user,
                 "value": float(value), "action": action, "ts": now},
                mode=UpdateMode.REPLACE,
            )
    except Exception as e:  # noqa: BLE001 — feedback is optional, never fail the caller
        print(f"votes: write failed ({e})")
        return 0
    return len(item_ids)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vote", choices=["up", "down"], required=True)
    ap.add_argument("--items", required=True, help="comma-separated item ids from the radar issue")
    ap.add_argument("--user", default="builder")
    args = ap.parse_args()

    account = os.environ.get("FEEDBACK_STORAGE", "")
    if not account:
        print("outcome: FEEDBACK_STORAGE not set — skipping")
        return 0
    ids = [s.strip() for s in args.items.split(",") if s.strip().isdigit()]
    if not ids:
        print("outcome: no valid item ids — nothing to record")
        return 0

    n = record_votes(account, args.user, [int(i) for i in ids], 1.0 if args.vote == "up" else -1.0)
    print(f"outcome: recorded {args.vote} for {n} item(s) as {args.user}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
