from __future__ import annotations

from pathlib import Path

from ai_scout.lib.config import KB_DIR, KB_PATH, DIGESTS_DIR

class BlobStore:

    def __init__(self, account: str, container: str = "knowledge"):
        self.account = account
        self.container = container

    @property
    def enabled(self) -> bool:
        return bool(self.account)

    def _service(self):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        return BlobServiceClient(f"https://{self.account}.blob.core.windows.net",
                                 credential=DefaultAzureCredential())

    def download_kb(self) -> None:
        if not self.enabled:
            return
        blob = self._service().get_blob_client(self.container, "kb.sqlite")
        if blob.exists():
            KB_DIR.mkdir(parents=True, exist_ok=True)
            with open(KB_PATH, "wb") as f:
                f.write(blob.download_blob().readall())
            print("downloaded existing kb.sqlite from Blob")

    def upload_kb(self, review: Path | None = None) -> None:
        if not self.enabled:
            print("note: STORAGE_ACCOUNT not set — skipped Blob upload")
            return
        svc = self._service()
        with open(KB_PATH, "rb") as f:
            svc.get_blob_client(self.container, "kb.sqlite").upload_blob(f, overwrite=True)
        msg = "uploaded kb.sqlite"
        if review:
            with open(review, "rb") as f:
                svc.get_blob_client(self.container, f"drafts/{review.name}").upload_blob(
                    f, overwrite=True)
            msg += f" + drafts/{review.name}"
        n = 0
        if DIGESTS_DIR.exists():
            for p in DIGESTS_DIR.glob("*.md"):
                with open(p, "rb") as f:
                    svc.get_blob_client(self.container, f"digests/{p.name}").upload_blob(
                        f, overwrite=True)
                n += 1
        if n:
            msg += f" + {n} digest(s)"
        print(msg + " to Blob")

    def download_digest(self, name: str) -> bytes | None:
        if not self.enabled:
            return None
        blob = self._service().get_blob_client(self.container, f"digests/{name}")
        if not blob.exists():
            return None
        return blob.download_blob().readall()
