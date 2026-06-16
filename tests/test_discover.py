"""discover — source-discovery logic (domain tally + proposals.yml merge). No network."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import discover  # noqa: E402


class TestCandidateDomains(unittest.TestCase):
    def _db(self, urls):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE item(id INTEGER PRIMARY KEY, url TEXT)")
        con.executemany("INSERT INTO item(url) VALUES(?)", [(u,) for u in urls])
        con.commit()
        return con

    def test_tallies_external_domains_over_threshold(self):
        con = self._db([
            "https://newblog.dev/a", "https://www.newblog.dev/b", "https://newblog.dev/c",
            "https://once.io/x",
        ])
        out = dict(discover._candidate_domains(con, skip=set(), min_seen=3))
        self.assertEqual(out.get("newblog.dev"), 3)   # www normalized, counted together
        self.assertNotIn("once.io", out)              # below threshold

    def test_skips_our_domains_and_aggregators(self):
        con = self._db([
            "https://mine.com/a", "https://mine.com/b", "https://mine.com/c",
            "https://arxiv.org/abs/1", "https://arxiv.org/abs/2", "https://arxiv.org/abs/3",
        ])
        out = dict(discover._candidate_domains(con, skip={"mine.com"}, min_seen=3))
        self.assertNotIn("mine.com", out)    # already a source
        self.assertNotIn("arxiv.org", out)   # hard-coded aggregator skip


class TestAppendProposals(unittest.TestCase):
    def test_replaces_placeholder_then_appends(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "proposals.yml"
            p.write_text("# header\nproposals: []\n", encoding="utf-8")
            orig = discover.PROPOSALS
            discover.PROPOSALS = p
            try:
                discover._append_proposals([
                    {"name": "newblog.dev", "url": "https://newblog.dev/feed", "seen": 4,
                     "reason": "linked by 4 KB items; feed auto-discovered"}])
                text = p.read_text(encoding="utf-8")
                self.assertIn("candidate_url: https://newblog.dev/feed", text)
                self.assertIn("status: proposed", text)
                self.assertNotIn("proposals: []", text)
                # already-proposed detection sees it
                discover.PROPOSALS = p
                self.assertIn("newblog.dev", discover._already_proposed())
            finally:
                discover.PROPOSALS = orig


if __name__ == "__main__":
    unittest.main()
