import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.domain.item import ScoredItem
from prism.services import curation

def _it(id=0, title="", score=0.0, source_id=None, topic=None, category=None):
    return ScoredItem(id=id, title=title, score=score, source_id=source_id,
                      topic=topic, category=category)

class TestDedup(unittest.TestCase):
    def test_collapses_near_duplicate_titles_keeping_first(self):
        items = [
            _it(1, "OpenAI launches GPT-6 model today", 90),
            _it(2, "OpenAI launches GPT-6 model", 70),
            _it(3, "Rust 2.0 release notes published", 60),
        ]
        out = curation.dedup(items)
        titles = [d.title for d in out]
        self.assertEqual(len(out), 2)
        self.assertIn("OpenAI launches GPT-6 model today", titles)
        self.assertIn("Rust 2.0 release notes published", titles)

    def test_distinct_titles_all_survive(self):
        items = [_it(1, "Apples and oranges"), _it(2, "Quantum networking advances")]
        self.assertEqual(len(curation.dedup(items)), 2)

    def test_empty_and_missing_titles_dont_crash(self):
        items = [_it(1, ""), _it(2, ""), _it(3, "Real headline here now")]
        self.assertEqual(len(curation.dedup(items)), 3)

class TestDropSeen(unittest.TestCase):
    def test_drops_resurfaced_story_from_other_source(self):
        items = [_it(5, "OpenAI launches GPT-6 model today"),
                 _it(6, "A totally unrelated breakthrough in batteries")]
        seen = ["OpenAI launches GPT-6 model"]
        out = curation.drop_seen(items, seen)
        self.assertEqual([d.id for d in out], [6])

    def test_no_seen_titles_is_passthrough(self):
        items = [_it(1, "Anything")]
        self.assertEqual(curation.drop_seen(items, []), items)

    def test_distinct_titles_survive_past_deliveries(self):
        items = [_it(1, "Brand new agent framework released")]
        seen = ["Old news about prompt caching", "Something about vector databases"]
        self.assertEqual(len(curation.drop_seen(items, seen)), 1)

class TestDiversify(unittest.TestCase):
    def test_caps_per_source(self):
        items = [_it(i, f"t{i}", source_id=1, topic=f"t{i}") for i in range(5)]
        out = curation.diversify(items, limit=5)
        self.assertEqual(len(out), 5)

    def test_respects_limit(self):
        items = [_it(i, f"t{i}", source_id=i, topic=f"t{i}") for i in range(10)]
        self.assertEqual(len(curation.diversify(items, limit=3)), 3)

    def test_diversity_prefers_spread_before_backfill(self):
        items = [_it(1, source_id=1, topic="a"), _it(2, source_id=1, topic="b"),
                 _it(3, source_id=1, topic="c"), _it(4, source_id=2, topic="d")]
        out = curation.diversify(items, limit=3)
        self.assertEqual([d.source_id for d in out], [1, 1, 2])

    def test_category_cap_groups_multifeed_firehose(self):
        research = [_it(10 + i, source_id=10 + i, category="Research (arXiv)", topic=f"r{i}")
                    for i in range(4)]
        applied = [_it(20 + i, source_id=20 + i, category=None, topic=f"a{i}") for i in range(4)]
        out = curation.diversify(research + applied, limit=5)
        n_research = sum(1 for d in out if d.category == "Research (arXiv)")
        self.assertEqual(len(out), 5)
        self.assertEqual(n_research, 2)

if __name__ == "__main__":
    unittest.main()
