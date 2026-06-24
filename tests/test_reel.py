import unittest
import types
from unittest import mock

from prism.cli import reel
from prism.services.reel_script import ReelScripter
from prism.services.reel_playbook import load_playbook

class TestReelScript(unittest.TestCase):
    def test_no_endpoint_is_a_graceful_noop(self):
        hook, cards = ReelScripter("", "m").script([(1, "Title", "Summary")])
        self.assertEqual((hook, cards), ("", {}))

    def test_no_items_is_a_noop(self):
        self.assertEqual(ReelScripter("https://x", "m").script([]), ("", {}))

class TestPlaybook(unittest.TestCase):
    def test_default_playbook_loads_and_joins_prompt(self):
        pb = load_playbook("explainer")
        self.assertEqual(pb.name, "explainer")
        self.assertIn("HOOK", pb.deep_system)        # array-of-lines joined into one brief
        self.assertTrue(pb.cta)

    def test_missing_playbook_falls_back(self):
        pb = load_playbook("does-not-exist")
        self.assertEqual(pb.deep_system, "")          # empty -> ReelScripter uses its default
        self.assertEqual(pb.name, "does-not-exist")

class TestPoolFromDigest(unittest.TestCase):
    def test_blob_disabled_is_graceful(self):
        s = types.SimpleNamespace(subscriber_storage="", feedback_storage="")
        self.assertEqual(reel._pool_from_digest(types.SimpleNamespace(enabled=False), None, s), [])

    def test_consumes_published_ids_in_rank_order(self):
        # The consumer features exactly what kb-sync wrote to the reel-lens digest, in order.
        s = types.SimpleNamespace(subscriber_storage="acct", feedback_storage="")
        blob = types.SimpleNamespace(enabled=True,
                                     download_digest=lambda name: b"body\n\n<!-- items: 3,1 -->\n")
        rows = {3: object(), 1: object()}

        class _Ses:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, _model, iid): return rows.get(iid)

        kb = types.SimpleNamespace(session=lambda: _Ses())
        reg = types.SimpleNamespace(profile_for_role=lambda r: types.SimpleNamespace(filesafe_lens="u-reel"))
        with mock.patch.object(reel.UserRegistry, "from_subscribers", return_value=reg):
            out = reel._pool_from_digest(blob, kb, s)
        self.assertEqual(out, [rows[3], rows[1]])

    def test_missing_digest_falls_back_to_live_selection(self):
        s = types.SimpleNamespace(subscriber_storage="acct", feedback_storage="")
        blob = types.SimpleNamespace(enabled=True, download_digest=lambda name: None)
        reg = types.SimpleNamespace(profile_for_role=lambda r: types.SimpleNamespace(filesafe_lens="u-reel"))
        with mock.patch.object(reel.UserRegistry, "from_subscribers", return_value=reg):
            self.assertEqual(reel._pool_from_digest(blob, None, s), [])

if __name__ == "__main__":
    unittest.main()
