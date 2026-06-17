from __future__ import annotations

import sys

from ai_scout.lib.settings import Settings
from ai_scout.repositories.blob import BlobStore

def main(argv=None) -> int:
    # Restore the owned KB from a Blob snapshot. `--list` shows available snapshots; an
    # explicit snapshot id restores that one; no argument restores the latest.
    args = argv if argv is not None else sys.argv[1:]
    s = Settings()
    blob = BlobStore(s.storage_account, s.blob_container)
    if not blob.enabled:
        print("restore: STORAGE_ACCOUNT not set")
        return 1
    if args and args[0] == "--list":
        snaps = blob.list_snapshots()
        for snap in snaps:
            print(snap)
        if not snaps:
            print("restore: no snapshots found")
        return 0
    restored = blob.restore_snapshot(args[0] if args else None)
    if not restored:
        print("restore: no snapshot found")
        return 1
    print(f"restored kb.sqlite from snapshot {restored}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
