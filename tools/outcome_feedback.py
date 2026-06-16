#!/usr/bin/env python3
"""ai-scout outcome-as-feedback (P13) — the builder's feedback loop with ZERO clicks.

The agent (user 'builder') never clicks 👍/👎. Instead, the OUTCOME of its self-improvement
PR is the feedback: a PR that auto-merges means the radar items it acted on were worth it
(👍); a PR closed unmerged means they weren't (👎). This closes the builder's learning loop
using the one signal the system already produces — and it generalizes: any channel can map an
outcome (merge, open-rate, reply) to a vote.

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

    value = 1.0 if args.vote == "up" else -1.0
    try:
        from azure.data.tables import TableServiceClient, UpdateMode
        from azure.identity import DefaultAzureCredential
        table = TableServiceClient(
            endpoint=f"https://{account}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        ).get_table_client("feedbackevents")
        now = int(time.time())
        for item_id in ids:
            table.upsert_entity(
                {"PartitionKey": item_id, "RowKey": f"{args.user}:vote", "user": args.user,
                 "value": value, "action": args.vote, "ts": now},
                mode=UpdateMode.REPLACE,
            )
    except Exception as e:  # noqa: BLE001 — feedback is optional, never fail the workflow
        print(f"outcome: write failed ({e})")
        return 0
    print(f"outcome: recorded {args.vote} for {len(ids)} item(s) as {args.user}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
