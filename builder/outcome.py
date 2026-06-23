#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time

def record_votes(account: str, lens: str, item_ids: list[int], value: float) -> int:
    if not account or not item_ids or not lens:
        return 0
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from prism.repositories.feedback import FeedbackStore
    return FeedbackStore(account).record_votes(lens, [int(i) for i in item_ids], value)

def _resolve_lens(role: str) -> str:
    import os
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from prism.repositories.registry import UserRegistry
    reg = UserRegistry.from_subscribers(os.environ.get("FEEDBACK_STORAGE", ""))
    prof = reg.profile_for_role(role)
    return prof.lens if prof else ""

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vote", choices=["up", "down"], required=True)
    ap.add_argument("--items", required=True, help="comma-separated item ids from the radar issue")
    ap.add_argument("--role", default="builder", help="user role whose lens receives the votes")
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
