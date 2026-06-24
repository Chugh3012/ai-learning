import unittest
from unittest import mock

from prism.repositories.blob import BlobStore


class TestDownloadUrl(unittest.TestCase):
    def test_disabled_is_graceful(self):
        self.assertEqual(BlobStore("").download_url("x"), "")

    def test_builds_keyless_user_delegation_sas_url(self):
        b = BlobStore("acct", "knowledge")
        svc = mock.Mock()
        svc.get_user_delegation_key.return_value = "KEY"
        with mock.patch.object(b, "_service", return_value=svc), \
             mock.patch("azure.storage.blob.generate_blob_sas", return_value="sig=abc"):
            url = b.download_url("digests/reels/ai/x.mp4", days=7)
        self.assertEqual(
            url, "https://acct.blob.core.windows.net/knowledge/digests/reels/ai/x.mp4?sig=abc")
        svc.get_user_delegation_key.assert_called_once()   # keyless: Entra-signed, no account key


if __name__ == "__main__":
    unittest.main()
