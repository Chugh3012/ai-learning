import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.lib.metrics import Metrics

class TestMetrics(unittest.TestCase):
    def test_add_accumulates_rows_with_dimensions(self):
        m = Metrics()
        m.add("ingested", 5)
        m.add("delivered", 3, lens="usr_a:prf_main", channel="email")
        self.assertEqual(len(m.rows), 2)
        self.assertEqual(m.rows[0]["Metric"], "ingested")
        self.assertEqual(m.rows[0]["Value"], 5.0)
        self.assertEqual(m.rows[1]["Lens"], "usr_a:prf_main")
        self.assertEqual(m.rows[1]["Channel"], "email")
        self.assertTrue(all(r["Run"] == m.run for r in m.rows))

    def test_disabled_when_unconfigured(self):
        self.assertFalse(Metrics().enabled)
        self.assertTrue(Metrics("https://dce", "dcr-1", "Custom-X").enabled)

    def test_flush_is_graceful_noop_when_unconfigured(self):
        m = Metrics()
        m.add("ranked", 9)
        m.flush()
        self.assertEqual(m.rows, [])

if __name__ == "__main__":
    unittest.main()
