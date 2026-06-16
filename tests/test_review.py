"""agent/review — builder reacts to its delivered digest file (no KB, no engine)."""
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
import review  # noqa: E402

DIGEST = """# ai-scout — builder digest

_3 items from the shared ranking._

1. Agentic Programming for reliable LLM control flow
   Deterministic logic governs control flow; the LLM is invoked only for reasoning.
   https://arxiv.org/abs/2606.15874

   feedback: 👍 x  |  👎 y  |  ⭐ z

2. A cute robot dog video
   It does a backflip. Not relevant to building pipelines.
   https://news.ycombinator.com/item?id=1

   feedback: 👍 x  |  👎 y  |  ⭐ z

3. DPO for chatbot fine-tuning
   Empirical study applying Direct Preference Optimization to fine-tune LLMs.
   https://arxiv.org/abs/2606.12881

   feedback: 👍 x  |  👎 y  |  ⭐ z


<!-- items: 874,12,881 -->
"""


def _today_digest(dirpath: Path, user: str = "builder") -> Path:
    p = dirpath / f"{user}-{datetime.now(timezone.utc):%Y-%m-%d}.md"
    p.write_text(DIGEST, encoding="utf-8")
    return p


class TestParseDigest(unittest.TestCase):
    def test_pairs_ids_with_titles_in_order(self):
        items = review.parse_digest(DIGEST)
        self.assertEqual([i for i, _t, _s in items], [874, 12, 881])
        self.assertEqual(items[0][1], "Agentic Programming for reliable LLM control flow")
        self.assertIn("Direct Preference Optimization", items[2][2])

    def test_no_footer_means_no_items(self):
        self.assertEqual(review.parse_digest("# digest\n1. Title\n   summary\n"), [])


class TestReview(unittest.TestCase):
    def test_reads_digest_and_votes(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            _today_digest(Path(d))
            with mock.patch.object(review, "DIGESTS", Path(d)), \
                 mock.patch.object(review, "judge", return_value={874: True, 12: False, 881: True}), \
                 mock.patch.object(review, "_interest", return_value="x"), \
                 mock.patch("outcome.record_votes",
                            side_effect=lambda a, u, items, v: calls.append((sorted(items), v)) or len(items)):
                n = review.review("builder", "ep", "mini", "acct")
        self.assertEqual(n, 3)
        self.assertIn(([874, 881], 1.0), calls)   # keeps -> 👍
        self.assertIn(([12], -1.0), calls)        # skip  -> 👎

    def test_missing_digest_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(review, "DIGESTS", Path(d)):  # empty dir, no digest
                self.assertEqual(review.review("builder", "ep", "mini", "acct"), 0)

    def test_empty_verdict_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            _today_digest(Path(d))
            with mock.patch.object(review, "DIGESTS", Path(d)), \
                 mock.patch.object(review, "judge", return_value={}) as j:
                n = review.review("builder", "", "mini", "acct")
        self.assertEqual(n, 0)
        j.assert_called_once()


if __name__ == "__main__":
    unittest.main()
