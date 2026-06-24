import unittest

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

if __name__ == "__main__":
    unittest.main()
