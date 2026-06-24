import unittest

from prism.services.reel_script import ReelScripter

class TestReelScript(unittest.TestCase):
    def test_no_endpoint_is_a_graceful_noop(self):
        hook, cards = ReelScripter("", "m").script([(1, "Title", "Summary")])
        self.assertEqual((hook, cards), ("", {}))

    def test_no_items_is_a_noop(self):
        self.assertEqual(ReelScripter("https://x", "m").script([]), ("", {}))

if __name__ == "__main__":
    unittest.main()
