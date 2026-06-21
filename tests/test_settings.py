import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.lib.settings import Settings

class TestSettingsUrls(unittest.TestCase):
    def test_function_route_urls_derive_from_feedback_url(self):
        s = Settings(feedback_url="https://fn.example.net/api/f")
        self.assertEqual(s.unsubscribe_url, "https://fn.example.net/api/unsubscribe")
        self.assertEqual(s.preference_url, "https://fn.example.net/api/preferences")
        self.assertEqual(s.saved_url, "https://fn.example.net/api/saved")

    def test_function_route_urls_blank_without_feedback(self):
        s = Settings(feedback_url="")
        self.assertEqual(s.unsubscribe_url, "")
        self.assertEqual(s.preference_url, "")
        self.assertEqual(s.saved_url, "")

if __name__ == "__main__":
    unittest.main()
