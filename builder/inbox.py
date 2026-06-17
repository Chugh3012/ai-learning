#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIGESTS = ROOT / "digests"

def _resolve_filesafe_lens(role: str) -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from ai_scout.repositories.registry import UserRegistry
        reg = UserRegistry.from_subscribers(os.environ.get("FEEDBACK_STORAGE", ""))
        prof = reg.profile_for_role(role)
        return prof.filesafe_lens if prof else ""
    except Exception as e:
        print(f"inbox: could not resolve role '{role}' ({e})")
        return ""

def fetch_digest(account: str, container: str, role: str) -> Path | None:
    if not account:
        print("inbox: STORAGE_ACCOUNT not set — skipping")
        return None
    stem = _resolve_filesafe_lens(role)
    if not stem:
        print(f"inbox: no profile for role '{role}'")
        return None
    name = f"{stem}-{datetime.now(timezone.utc):%Y-%m-%d}.md"
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        svc = BlobServiceClient(
            f"https://{account}.blob.core.windows.net", credential=DefaultAzureCredential())
        blob = svc.get_blob_client(container, f"digests/{name}")
        if not blob.exists():
            print(f"inbox: digests/{name} not in Blob (quiet day?)")
            return None
        DIGESTS.mkdir(exist_ok=True)
        out = DIGESTS / name
        with open(out, "wb") as f:
            f.write(blob.download_blob().readall())
        print(f"inbox: downloaded digests/{name}")
        return out
    except Exception as e:
        print(f"inbox: failed ({e})")
        return None

def main() -> int:
    role = sys.argv[1] if len(sys.argv) > 1 else "builder"
    fetch_digest(os.environ.get("STORAGE_ACCOUNT", ""),
                 os.environ.get("BLOB_CONTAINER", "knowledge"), role)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
