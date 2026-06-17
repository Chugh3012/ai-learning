import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.services import evaluator

class TestMedian(unittest.TestCase):
    def test_odd_count_picks_middle(self):
        self.assertEqual(evaluator._median([70, 90, 80]), 80)

    def test_even_count_averages_middle_pair(self):
        self.assertEqual(evaluator._median([70, 90]), 80)

    def test_single_sample(self):
        self.assertEqual(evaluator._median([42]), 42)

    def test_median_resists_one_outlier(self):
        self.assertEqual(evaluator._median([80, 81, 12]), 80)

class TestSpearman(unittest.TestCase):
    def test_perfect_monotonic_is_one(self):
        self.assertAlmostEqual(evaluator._spearman([(1, 1), (2, 2), (3, 3)]), 1.0, places=6)

    def test_inverted_is_minus_one(self):
        self.assertAlmostEqual(evaluator._spearman([(1, 3), (2, 2), (3, 1)]), -1.0, places=6)

class TestNdcg(unittest.TestCase):
    def test_ideal_ordering_is_one(self):
        scored = [{"score": 90, "tier": 2}, {"score": 80, "tier": 1}, {"score": 10, "tier": 0}]
        self.assertAlmostEqual(evaluator._ndcg_at(scored, 5), 1.0, places=6)

if __name__ == "__main__":
    unittest.main()
