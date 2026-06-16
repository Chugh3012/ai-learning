"""curate.dedup + diversify — near-duplicate clustering and source/topic caps."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import curate  # noqa: E402


class TestDedup(unittest.TestCase):
    def test_collapses_near_duplicate_titles_keeping_first(self):
        items = [
            {"title": "OpenAI launches GPT-6 model today", "score": 90},
            {"title": "OpenAI launches GPT-6 model", "score": 70},   # near-dup of #1
            {"title": "Rust 2.0 release notes published", "score": 60},
        ]
        out = curate.dedup(items)
        titles = [d["title"] for d in out]
        self.assertEqual(len(out), 2)
        self.assertIn("OpenAI launches GPT-6 model today", titles)  # higher-ranked kept
        self.assertIn("Rust 2.0 release notes published", titles)

    def test_distinct_titles_all_survive(self):
        items = [{"title": "Apples and oranges"}, {"title": "Quantum networking advances"}]
        self.assertEqual(len(curate.dedup(items)), 2)

    def test_empty_and_missing_titles_dont_crash(self):
        items = [{"title": ""}, {"score": 1}, {"title": "Real headline here now"}]
        # empty/missing token-sets are treated as non-similar; all pass through
        self.assertEqual(len(curate.dedup(items)), 3)


class TestDiversify(unittest.TestCase):
    def test_caps_per_source(self):
        items = [{"source_id": 1, "topic": f"t{i}"} for i in range(5)]
        out = curate.diversify(items, limit=5)
        # default max_per_source=2 -> only 2 from source 1 fit the caps, rest deferred but
        # backfilled only if slots remain; here limit 5 > 2 so backfill fills to 5.
        self.assertLessEqual(sum(1 for d in out if d["source_id"] == 1), 5)
        self.assertEqual(len(out), 5)  # backfill reaches the limit

    def test_respects_limit(self):
        items = [{"source_id": i, "topic": f"t{i}"} for i in range(10)]
        self.assertEqual(len(curate.diversify(items, limit=3)), 3)

    def test_diversity_prefers_spread_before_backfill(self):
        # 3 from source 1, then 1 from source 2; limit 3, cap 2/source -> first two of src1,
        # then src2 (not the third src1) is chosen before any backfill.
        items = [
            {"source_id": 1, "topic": "a"},
            {"source_id": 1, "topic": "b"},
            {"source_id": 1, "topic": "c"},
            {"source_id": 2, "topic": "d"},
        ]
        out = curate.diversify(items, limit=3)
        self.assertEqual([d["source_id"] for d in out], [1, 1, 2])

    def test_category_cap_groups_multifeed_firehose(self):
        # arXiv ships 3 feeds (distinct source_ids) under one 'Research' category; the per-source
        # cap alone would let 2*3=6 through. max_per_category=2 (config) caps the whole bucket,
        # so applied content fills the remaining slots instead of an academic flood.
        research = [{"source_id": 10 + i, "category": "Research (arXiv)", "topic": f"r{i}"}
                    for i in range(4)]                       # 4 distinct arXiv feeds
        applied = [{"source_id": 20 + i, "category": None, "topic": f"a{i}"}
                   for i in range(4)]                        # applied sources, no shared category
        out = curate.diversify(research + applied, limit=5)  # research listed first (higher rank)
        n_research = sum(1 for d in out if d.get("category") == "Research (arXiv)")
        self.assertEqual(len(out), 5)
        self.assertEqual(n_research, 2)                      # capped at 2 despite 4 available
        self.assertEqual(5 - n_research, 3)                  # applied took the freed slots


if __name__ == "__main__":
    unittest.main()
