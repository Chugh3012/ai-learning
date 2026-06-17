from __future__ import annotations

from ai_scout.lib.config import KB_DIR, KB_PATH

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

    def upload_kb(self) -> None:
        if not self.enabled:
            print("note: STORAGE_ACCOUNT not set — skipped Blob upload")
            return
        with open(KB_PATH, "rb") as f:
            self._service().get_blob_client(self.container, "kb.sqlite").upload_blob(
                f, overwrite=True)
        print("uploaded kb.sqlite to Blob")

    def put_text(self, path: str, text: str) -> bool:
        if not self.enabled:
            return False
        self._service().get_blob_client(self.container, path).upload_blob(
            text.encode("utf-8"), overwrite=True)
        return True

    def download_digest(self, name: str) -> bytes | None:
        if not self.enabled:
            return None
        blob = self._service().get_blob_client(self.container, f"digests/{name}")
        if not blob.exists():
            return None
        return blob.download_blob().readall()
