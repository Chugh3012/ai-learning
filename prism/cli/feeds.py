from __future__ import annotations

import argparse
import sys

from prism.lib.settings import Settings
from prism.repositories.subscribers import SubscriberStore

# Admin CLI to provision automation FEEDS (reel / builder lenses) owned by the registry. This is
# the single, reproducible way to create a feed — no hand-poking tables, no scratch scripts. The
# registry mints the ids; consumers (reel render) only ever READ the lenses this creates.

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Provision registry-owned automation feeds (lenses).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="create/update a feed (idempotent by kind+topic+channel)")
    a.add_argument("--kind", required=True, help="feed kind, e.g. reel or builder")
    a.add_argument("--topic", required=True, help="topic pack id, e.g. ai or politics")
    a.add_argument("--interest", required=True, help="the lens's selection interest (its source of truth)")
    a.add_argument("--channel", default="digest")
    a.add_argument("--cadence", default="daily")
    a.add_argument("--top", type=int, default=6)
    a.add_argument("--name", default="")
    lp = sub.add_parser("list", help="list automation feeds")
    lp.add_argument("--kind", default="")
    r = sub.add_parser("remove", help="remove a feed's topic profile")
    r.add_argument("--kind", required=True)
    r.add_argument("--topic", required=True)
    args = ap.parse_args(argv)

    s = Settings()
    store = SubscriberStore(s.subscriber_storage or s.feedback_storage)
    if not store.enabled:
        print("feeds: no subscriber storage configured")
        return 1

    if args.cmd == "add":
        uid, pid = store.provision_feed(args.kind, args.topic, args.interest, channel=args.channel,
                                        cadence=args.cadence, top=args.top, name=args.name)
        print(f"feeds: provisioned {args.kind}/{args.topic} -> {uid}:{pid}")
    elif args.cmd == "list":
        for f in store.list_feeds(args.kind):
            print(f"{f['kind']:8} {f['topic_id']:10} {f['user_id']}:{f['profile_id']} "
                  f"({f['channel']}, {f['cadence']}) {f['interest'][:60]}")
    elif args.cmd == "remove":
        print(f"feeds: removed {store.remove_feed(args.kind, args.topic)} profile(s)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
