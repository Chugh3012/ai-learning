import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.domain.item import ScoredItem
from prism.services.selector import Selector

SEL = Selector(None)

def _items(scores):
    return [ScoredItem(id=i, title=f"item {i}", score=s, source_id=i, topic=f"t{i}")
            for i, s in enumerate(scores)]

class TestExploreExploit(unittest.TestCase):
    def test_pure_exploit_when_ratio_zero(self):
        out = SEL._explore_exploit(_items([90, 85, 80, 70, 60, 50, 40]), top=5, ratio=0.0)
        self.assertEqual([d.id for d in out], [0, 1, 2, 3, 4])

    def test_reserves_an_explore_slot(self):
        out = SEL._explore_exploit(_items([90, 85, 80, 70, 60, 50, 40, 30]), top=5, ratio=0.2,
                                   rng=random.Random(7))
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
            out = SEL._explore_exploit(_items([90, 85, 80, 70, 60, 50, 40, 30, 20]), top=5,
                                       ratio=0.2, rng=random.Random(seed))
            picks.add(tuple(sorted(d.id for d in out)))
        self.assertGreater(len(picks), 1)

    def test_no_spare_items_falls_back_to_exploit(self):
        out = SEL._explore_exploit(_items([90, 85, 80]), top=5, ratio=0.2)
        self.assertEqual([d.id for d in out], [0, 1, 2])

    def test_result_is_score_sorted(self):
        out = SEL._explore_exploit(_items([90, 85, 80, 70, 60, 50]), top=5, ratio=0.2,
                                   rng=random.Random(1))
        scores = [d.score for d in out]
        self.assertEqual(scores, sorted(scores, reverse=True))

class TestWeightedSample(unittest.TestCase):
    def test_favors_higher_score_on_average(self):
        items = _items([100, 1, 1, 1])
        hits = sum(_w[0].id == 0 for _w in
                   (SEL._weighted_sample(items, 1, random.Random(s)) for s in range(40)))
        self.assertGreater(hits, 20)

    def test_without_replacement(self):
        out = SEL._weighted_sample(_items([10, 9, 8]), 3, random.Random(0))
        self.assertEqual(sorted(d.id for d in out), [0, 1, 2])

if __name__ == "__main__":
    unittest.main()
