import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.repositories import blob as blobmod


class _Snap:
    def __init__(self, snapshot):
        self.name = "kb.sqlite"
        self.snapshot = snapshot


class _FakeBlobClient:
    def __init__(self, store, snapshot=None):
        self.store = store
        self.snapshot = snapshot

    def upload_blob(self, data, overwrite=False):
        self.store["current"] = data.read() if hasattr(data, "read") else data

    def create_snapshot(self):
        ts = f"2026-06-18T0{len(self.store['snaps'])}:00:00Z"
        self.store["snaps"][ts] = self.store["current"]
        return {"snapshot": ts}

    def download_blob(self):
        data = self.store["snaps"][self.snapshot]
        return mock.Mock(readall=lambda: data)


class _FakeContainerClient:
    def __init__(self, store):
        self.store = store

    def list_blobs(self, name_starts_with=None, include=None):
        return [_Snap(ts) for ts in self.store["snaps"]]


class _FakeService:
    def __init__(self, store):
        self.store = store

    def get_blob_client(self, container, name, snapshot=None):
        return _FakeBlobClient(self.store, snapshot)

    def get_container_client(self, container):
        return _FakeContainerClient(self.store)


class TestSnapshotRestore(unittest.TestCase):
    def setUp(self):
        self.store = {"current": b"", "snaps": {}}
        self.tmp = tempfile.mkdtemp()
        self.kb_path = Path(self.tmp) / "kb.sqlite"
        self.bs = blobmod.BlobStore("acct", "knowledge")
        for p in (
            mock.patch.object(self.bs, "_service", return_value=_FakeService(self.store)),
            mock.patch.object(blobmod, "KB_PATH", self.kb_path),
            mock.patch.object(blobmod, "KB_DIR", Path(self.tmp)),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_upload_creates_a_snapshot(self):
        self.kb_path.write_bytes(b"DB-V1")
        self.bs.upload_kb()
        self.assertEqual(len(self.bs.list_snapshots()), 1)

    def test_restore_latest_snapshot(self):
        self.kb_path.write_bytes(b"DB-V1")
        self.bs.upload_kb()
        self.kb_path.write_bytes(b"DB-V2")
        self.bs.upload_kb()
        # corrupt local, then restore the latest snapshot back
        self.kb_path.write_bytes(b"CORRUPT")
        restored = self.bs.restore_snapshot()
        self.assertTrue(restored)
        self.assertEqual(self.kb_path.read_bytes(), b"DB-V2")

    def test_restore_specific_snapshot(self):
        self.kb_path.write_bytes(b"DB-V1")
        self.bs.upload_kb()
        first = self.bs.list_snapshots()[0]
        self.kb_path.write_bytes(b"DB-V2")
        self.bs.upload_kb()
        restored = self.bs.restore_snapshot(first)
        self.assertEqual(restored, first)
        self.assertEqual(self.kb_path.read_bytes(), b"DB-V1")

    def test_restore_with_no_snapshots_is_graceful(self):
        self.assertEqual(self.bs.restore_snapshot(), "")


if __name__ == "__main__":
    unittest.main()
