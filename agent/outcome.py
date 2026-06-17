#!/usr/bin/env python3
"""ai-scout outcome-as-feedback — the builder's POSITIVE feedback gesture with ZERO clicks.

The maintainer agent never clicks 👍/👎. Instead, the OUTCOME of its self-improvement
PR is the feedback: when a PR MERGES, the radar items it acted on were worth it (👍). The
negative side ("shown but not acted on") is owned by feedback_ingest's fb_skip rule, so this
tool records only the positive on merge — generalizing to any channel that can map an outcome
(merge, open-rate, reply) to a vote.

It writes events into the SAME `feedbackevents` table the Function uses (RowKey '<lens>:vote',
carrying the opaque lens), so the normal daily `feedback_ingest` turns them into affinity:<lens>
with no new code path. Passwordless: DefaultAzureCredential (OIDC in CI). Never raises fatally.

Usage (from the feedback-on-merge workflow):
  python agent/outcome.py --vote up   --items 1804,2327,11 [--role maintainer]
  python agent/outcome.py --vote down --items 1804,2327,11 [--role maintainer]
"""
from __future__ import annotations

import argparse
import os
import sys
import time


def record_votes(account: str, lens: str, item_ids: list[int], value: float) -> int:
    """Write one vote event per item to `feedbackevents` (the gesture source of truth, same path a
    human click takes), so the daily feedback ingest reconciles them into affinity:<lens>.
    value > 0 = up, < 0 = down. Returns count written. Passwordless; never raises."""
    if not account or not item_ids or not lens:
        return 0
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ai_scout.repositories.feedback import FeedbackStore
    return FeedbackStore(account).record_votes(lens, [int(i) for i in item_ids], value)


def _resolve_lens(role: str) -> str:
    """Resolve a user ROLE to its agent profile's lens (never a hardcoded id)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ai_scout.repositories.registry import UserRegistry
    prof = UserRegistry.load().profile_for_role(role)
    return prof.lens if prof else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vote", choices=["up", "down"], required=True)
    ap.add_argument("--items", required=True, help="comma-separated item ids from the radar issue")
    ap.add_argument("--role", default="maintainer", help="user role whose lens receives the votes")
    args = ap.parse_args()

    account = os.environ.get("FEEDBACK_STORAGE", "")
    if not account:
        print("outcome: FEEDBACK_STORAGE not set — skipping")
        return 0
    ids = [s.strip() for s in args.items.split(",") if s.strip().isdigit()]
    if not ids:
        print("outcome: no valid item ids — nothing to record")
        return 0

    lens = _resolve_lens(args.role)
    if not lens:
        print(f"outcome: could not resolve role '{args.role}' — skipping")
        return 0
    n = record_votes(account, lens, [int(i) for i in ids], 1.0 if args.vote == "up" else -1.0)
    print(f"outcome: recorded {args.vote} for {n} item(s) on {lens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
