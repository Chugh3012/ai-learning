import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.services import producer

class TestLoadFormat(unittest.TestCase):
    def test_reel_format_has_production_instruction(self):
        reel = producer.load_format("reel")
        self.assertTrue(reel["instruction"])
        self.assertIn("DIRECTOR", reel["instruction"])
        self.assertIsInstance(reel["temperature"], float)

    def test_social_format_parses(self):
        social = producer.load_format("social")
        self.assertTrue(social["instruction"])
        self.assertIn("social media", social["instruction"].lower())

    def test_unknown_format_raises(self):
        with self.assertRaises(KeyError):
            producer.load_format("does-not-exist")

if __name__ == "__main__":
    unittest.main()
