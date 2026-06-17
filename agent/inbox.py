#!/usr/bin/env python3
"""Maintainer inbox — the agent reading its delivery (read-only).

The maintainer is a USER of ai-scout, never its engine. It only READS the digest that kb-sync has
already produced and published to Blob (exactly like the human opens their top-5 email). It does
NOT run the pipeline (no fetch / rank / embed / deliver / KB access). This resolves the user by
ROLE, then downloads digests/<filesafe_lens>-<today>.md from Blob into the checkout so the
builder-radar agent can read it. Passwordless (DefaultAzureCredential / OIDC in CI). Never raises.

Usage:  python agent/inbox.py maintainer
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIGESTS = ROOT / "digests"


def _resolve_filesafe_lens(role: str) -> str:
    """Resolve a user ROLE to its agent profile's filesafe lens (digest filename stem)."""
    try:
        sys.path.insert(0, str(ROOT))
        from ai_scout.repositories.registry import UserRegistry
        prof = UserRegistry.load().profile_for_role(role)
        return prof.filesafe_lens if prof else ""
    except Exception as e:  # noqa: BLE001
        print(f"inbox: could not resolve role '{role}' ({e})")
        return ""


def fetch_digest(account: str, container: str, role: str) -> Path | None:
    """Download the digest for the user with this ROLE for today from Blob to digests/.
    Returns the path, or None."""
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
    except Exception as e:  # noqa: BLE001 — reading mail is best-effort, never break the run
        print(f"inbox: failed ({e})")
        return None


def main() -> int:
    role = sys.argv[1] if len(sys.argv) > 1 else "maintainer"
    fetch_digest(os.environ.get("STORAGE_ACCOUNT", ""),
                 os.environ.get("BLOB_CONTAINER", "knowledge"), role)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
