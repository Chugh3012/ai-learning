"""draft._load_format — flat content-format parser (production recipes only, offline)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import draft  # noqa: E402


class TestLoadFormat(unittest.TestCase):
    def test_reel_format_has_production_instruction(self):
        reel = draft._load_format("reel")
        self.assertTrue(reel["instruction"])                 # production prompt present
        self.assertIn("DIRECTOR", reel["instruction"])
        self.assertIsInstance(reel["temperature"], float)

    def test_social_format_parses(self):
        social = draft._load_format("social")
        self.assertTrue(social["instruction"])
        self.assertIn("social media", social["instruction"].lower())

    def test_unknown_format_raises(self):
        with self.assertRaises(KeyError):
            draft._load_format("does-not-exist")


if __name__ == "__main__":
    unittest.main()
