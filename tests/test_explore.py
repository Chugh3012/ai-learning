"""select explore/exploit — reserve slots for stochastic exploration (offline)."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import selection as selector  # noqa: E402


def _items(scores):
    # best-first, each a distinct source so diversity caps don't interfere
    return [{"id": i, "title": f"item {i}", "score": s, "source_id": i, "topic": f"t{i}"}
            for i, s in enumerate(scores)]


class TestExploreExploit(unittest.TestCase):
    def test_pure_exploit_when_ratio_zero(self):
        items = _items([90, 85, 80, 70, 60, 50, 40])
        out = selector._explore_exploit(items, top=5, ratio=0.0)
        self.assertEqual([d["id"] for d in out], [0, 1, 2, 3, 4])   # strict top-5

    def test_reserves_an_explore_slot(self):
        items = _items([90, 85, 80, 70, 60, 50, 40, 30])
        rng = random.Random(7)
        out = selector._explore_exploit(items, top=5, ratio=0.2, rng=rng)
        ids = [d["id"] for d in out]
        self.assertEqual(len(out), 5)
        # top-4 (exploit) always present; the 5th is sampled from below the cut (id >= 4)
        for keep in (0, 1, 2, 3):
            self.assertIn(keep, ids)
        explore_pick = [i for i in ids if i not in (0, 1, 2, 3)]
        self.assertEqual(len(explore_pick), 1)
        self.assertGreaterEqual(explore_pick[0], 4)            # came from the explore pool

    def test_exploration_actually_varies(self):
        items = _items([90, 85, 80, 70, 60, 50, 40, 30, 20])
        picks = set()
        for seed in range(20):
            out = selector._explore_exploit(items, top=5, ratio=0.2, rng=random.Random(seed))
            picks.add(tuple(sorted(d["id"] for d in out)))
        self.assertGreater(len(picks), 1)                      # not deterministic = genuinely exploring

    def test_no_spare_items_falls_back_to_exploit(self):
        items = _items([90, 85, 80])                            # fewer than top
        out = selector._explore_exploit(items, top=5, ratio=0.2)
        self.assertEqual([d["id"] for d in out], [0, 1, 2])

    def test_result_is_score_sorted(self):
        items = _items([90, 85, 80, 70, 60, 50])
        out = selector._explore_exploit(items, top=5, ratio=0.2, rng=random.Random(1))
        scores = [d["score"] for d in out]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestWeightedSample(unittest.TestCase):
    def test_favors_higher_score_on_average(self):
        items = _items([100, 1, 1, 1])  # id 0 has huge weight
        rng = random.Random(0)
        hits = sum(_w[0]["id"] == 0 for _w in
                   (selector._weighted_sample(items, 1, random.Random(s)) for s in range(40)))
        self.assertGreater(hits, 20)    # the high-score item is picked > half the time

    def test_without_replacement(self):
        items = _items([10, 9, 8])
        out = selector._weighted_sample(items, 3, random.Random(0))
        self.assertEqual(sorted(d["id"] for d in out), [0, 1, 2])   # all distinct


if __name__ == "__main__":
    unittest.main()
