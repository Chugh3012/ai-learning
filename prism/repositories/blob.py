from __future__ import annotations

from prism.lib.config import KB_DIR, KB_PATH

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
        blob = self._service().get_blob_client(self.container, "kb.sqlite")
        with open(KB_PATH, "rb") as f:
            blob.upload_blob(f, overwrite=True)
        print("uploaded kb.sqlite to Blob")
        # Timestamped recovery point on top of overwrite (versioning also protects the
        # account; an explicit daily snapshot gives an obvious restore target). Graceful.
        try:
            snap = blob.create_snapshot()
            print(f"snapshot: kb.sqlite @ {snap.get('snapshot')}")
        except Exception as e:
            print(f"snapshot: skipped ({e})")

    def list_snapshots(self) -> list[str]:
        if not self.enabled:
            return []
        cc = self._service().get_container_client(self.container)
        snaps = [b.snapshot for b in cc.list_blobs(name_starts_with="kb.sqlite",
                                                   include=["snapshots"])
                 if getattr(b, "snapshot", None)]
        return sorted(snaps)

    def restore_snapshot(self, snapshot: str | None = None) -> str:
        # Restore kb.sqlite from a snapshot (latest if none given) into the local KB path.
        # Returns the snapshot id restored, or "" if there was nothing to restore.
        if not self.enabled:
            return ""
        snapshot = snapshot or (self.list_snapshots() or [None])[-1]
        if not snapshot:
            return ""
        blob = self._service().get_blob_client(self.container, "kb.sqlite", snapshot=snapshot)
        KB_DIR.mkdir(parents=True, exist_ok=True)
        with open(KB_PATH, "wb") as f:
            f.write(blob.download_blob().readall())
        return snapshot

    def put_text(self, path: str, text: str) -> bool:
        if not self.enabled:
            return False
        self._service().get_blob_client(self.container, path).upload_blob(
            text.encode("utf-8"), overwrite=True)
        return True

    def put_file(self, path: str, local_path, content_type: str = "") -> bool:
        if not self.enabled:
            return False
        from azure.storage.blob import ContentSettings
        cs = ContentSettings(content_type=content_type) if content_type else None
        with open(local_path, "rb") as f:
            self._service().get_blob_client(self.container, path).upload_blob(
                f, overwrite=True, content_settings=cs)
        return True

    def download_digest(self, name: str) -> bytes | None:
        if not self.enabled:
            return None
        blob = self._service().get_blob_client(self.container, f"digests/{name}")
        if not blob.exists():
            return None
        return blob.download_blob().readall()

    def read_edition(self, lens: str, date: str):
        # Return the typed Edition a lens published on a date (or None). The Edition owns parsing;
        # this just owns the blob IO. Consumers read structured data, never raw markdown.
        from prism.domain.edition import Edition
        data = self.download_digest(f"{lens}-{date}.md")
        return Edition.from_markdown(lens, data.decode("utf-8", "replace")) if data else None

    def download_url(self, path: str, days: int = 7) -> str:
        # A time-limited, KEYLESS download link: a user-delegation SAS signed by the Entra identity
        # at runtime (no account key, nothing stored). content_disposition=attachment makes the
        # browser DOWNLOAD the file (with a filename) instead of playing the mp4 inline.
        if not self.enabled:
            return ""
        from datetime import datetime, timedelta, timezone
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions
        start = datetime.now(timezone.utc) - timedelta(minutes=5)
        expiry = datetime.now(timezone.utc) + timedelta(days=days)
        key = self._service().get_user_delegation_key(start, expiry)
        filename = path.rsplit("/", 1)[-1]
        sas = generate_blob_sas(account_name=self.account, container_name=self.container,
                                blob_name=path, user_delegation_key=key,
                                permission=BlobSasPermissions(read=True), start=start, expiry=expiry,
                                content_disposition=f'attachment; filename="{filename}"')
        return f"https://{self.account}.blob.core.windows.net/{self.container}/{path}?{sas}"
