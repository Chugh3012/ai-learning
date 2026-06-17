"""draft._load_profile — flat content-profile parser, incl. the optional `interest` lens (offline)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import draft  # noqa: E402


class TestLoadProfile(unittest.TestCase):
    def test_reel_has_instruction_and_interest_lens(self):
        reel = draft._load_profile("reel")
        self.assertTrue(reel["instruction"])                 # production prompt present
        self.assertIn("DIRECTOR", reel["instruction"])
        self.assertTrue(reel["interest"])                    # selection lens present
        self.assertIn("30-second", reel["interest"])
        self.assertIsInstance(reel["temperature"], float)

    def test_social_parses_without_interest_lens(self):
        social = draft._load_profile("social")
        self.assertTrue(social["instruction"])
        self.assertEqual(social.get("interest", ""), "")     # no lens => plain relevance pick

    def test_unknown_profile_raises(self):
        with self.assertRaises(KeyError):
            draft._load_profile("does-not-exist")


if __name__ == "__main__":
    unittest.main()
