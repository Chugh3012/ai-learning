import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.domain.item import ScoredItem
from prism.services.personalization.explorer import EpsilonExplorer, ThompsonExplorer

def _items(scores, sources=None):
    return [ScoredItem(id=i, title=f"item {i}", score=s, topic=f"t{i}",
                       source_id=(sources[i] if sources else i))
            for i, s in enumerate(scores)]

class TestEpsilonExplorer(unittest.TestCase):
    def test_pure_exploit_when_ratio_zero(self):
        out = EpsilonExplorer(0.0).choose(_items([90, 85, 80, 70, 60, 50, 40]), top=5)
        self.assertEqual([d.id for d in out], [0, 1, 2, 3, 4])

    def test_reserves_an_explore_slot(self):
        out = EpsilonExplorer(0.2, random.Random(7)).choose(
            _items([90, 85, 80, 70, 60, 50, 40, 30]), top=5)
        ids = [d.id for d in out]
        self.assertEqual(len(out), 5)
        for keep in (0, 1, 2, 3):
            self.assertIn(keep, ids)
        explore_pick = [i for i in ids if i not in (0, 1, 2, 3)]
        self.assertEqual(len(explore_pick), 1)
        self.assertGreaterEqual(explore_pick[0], 4)

    def test_exploration_actually_varies(self):
        picks = set()
        for seed in range(20):
            out = EpsilonExplorer(0.2, random.Random(seed)).choose(
                _items([90, 85, 80, 70, 60, 50, 40, 30, 20]), top=5)
            picks.add(tuple(sorted(d.id for d in out)))
        self.assertGreater(len(picks), 1)

    def test_no_spare_items_falls_back_to_exploit(self):
        out = EpsilonExplorer(0.2).choose(_items([90, 85, 80]), top=5)
        self.assertEqual([d.id for d in out], [0, 1, 2])

    def test_result_is_score_sorted(self):
        out = EpsilonExplorer(0.2, random.Random(1)).choose(
            _items([90, 85, 80, 70, 60, 50]), top=5)
        scores = [d.score for d in out]
        self.assertEqual(scores, sorted(scores, reverse=True))

class TestWeightedSample(unittest.TestCase):
    def test_favors_higher_score_on_average(self):
        items = _items([100, 1, 1, 1])
        hits = sum(_w[0].id == 0 for _w in
                   (EpsilonExplorer._weighted_sample(items, 1, random.Random(s)) for s in range(40)))
        self.assertGreater(hits, 20)

    def test_without_replacement(self):
        out = EpsilonExplorer._weighted_sample(_items([10, 9, 8]), 3, random.Random(0))
        self.assertEqual(sorted(d.id for d in out), [0, 1, 2])

class _FakeKB:
    def __init__(self, counts):
        self._counts = counts

    def source_feedback_counts(self, lens):
        return self._counts

class TestThompsonExplorer(unittest.TestCase):
    def test_keeps_exploit_head_and_one_explore(self):
        kb = _FakeKB({})
        out = ThompsonExplorer(kb, 0.2, random.Random(0)).choose(
            _items([90, 85, 80, 70, 60, 50, 40]), top=5, lens="L")
        ids = [d.id for d in out]
        self.assertEqual(len(out), 5)
        for keep in (0, 1, 2, 3):
            self.assertIn(keep, ids)

    def test_favors_source_with_stronger_posterior(self):
        # item 4,5,6 are the explore candidates; source 20 has overwhelming keeps, 10 has skips.
        kb = _FakeKB({10: (0.0, 100.0), 20: (100.0, 0.0)})
        out = ThompsonExplorer(kb, 0.2, random.Random(3)).choose(
            _items([90, 85, 80, 70, 60, 55, 50], sources=[0, 1, 2, 3, 10, 20, 10]),
            top=5, lens="L")
        ids = [d.id for d in out]
        self.assertIn(5, ids)  # the high-posterior source's item gets the explore slot

    def test_pure_exploit_when_ratio_zero(self):
        out = ThompsonExplorer(_FakeKB({}), 0.0).choose(
            _items([90, 85, 80, 70, 60, 50]), top=5, lens="L")
        self.assertEqual([d.id for d in out], [0, 1, 2, 3, 4])

if __name__ == "__main__":
    unittest.main()
