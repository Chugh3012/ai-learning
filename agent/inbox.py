#!/usr/bin/env python3
"""Builder inbox — the builder reading its delivery (read-only).

The builder is a USER of ai-scout, never its engine. It only READS the digest that kb-sync has
already produced and published to Blob (exactly like the human opens their top-5 email). It does
NOT run the pipeline (no fetch / rank / embed / deliver / KB access). This downloads
digests/<user>-<today>.md from Blob into the checkout so the builder-radar agent can read it.
Passwordless (DefaultAzureCredential / OIDC in CI). Best-effort: never raises fatally.

Usage:  python agent/inbox.py builder
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DIGESTS = Path(__file__).resolve().parent.parent / "digests"


def fetch_digest(account: str, container: str, user: str) -> Path | None:
    """Download <user>'s digest for today from Blob to digests/. Returns the path, or None."""
    if not account:
        print("inbox: STORAGE_ACCOUNT not set — skipping")
        return None
    name = f"{user}-{datetime.now(timezone.utc):%Y-%m-%d}.md"
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
    except Exception as e:  # noqa: BLE001 — reading mail is best-effort, never break the run
        print(f"inbox: failed ({e})")
        return None


def main() -> int:
    user = sys.argv[1] if len(sys.argv) > 1 else "builder"
    fetch_digest(os.environ.get("STORAGE_ACCOUNT", ""),
                 os.environ.get("BLOB_CONTAINER", "knowledge"), user)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
