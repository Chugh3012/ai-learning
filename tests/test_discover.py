"""services.SourceDiscoverer — domain tally + proposals.yml merge (offline, no network)."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.repositories.knowledge import KnowledgeBase  # noqa: E402
from ai_scout.services import discoverer as disc  # noqa: E402


def _kb(urls):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE item(id INTEGER PRIMARY KEY, url TEXT)")
    con.executemany("INSERT INTO item(url) VALUES(?)", [(u,) for u in urls])
    con.commit()
    return KnowledgeBase(con)


class TestCandidateDomains(unittest.TestCase):
    def test_tallies_external_domains_over_threshold(self):
        kb = _kb(["https://newblog.dev/a", "https://www.newblog.dev/b", "https://newblog.dev/c",
                  "https://once.io/x"])
        self.addCleanup(kb.close)
        out = dict(disc.SourceDiscoverer(kb)._candidate_domains(skip=set(), min_seen=3))
        self.assertEqual(out.get("newblog.dev"), 3)
        self.assertNotIn("once.io", out)

    def test_skips_our_domains_and_aggregators(self):
        kb = _kb(["https://mine.com/a", "https://mine.com/b", "https://mine.com/c",
                  "https://arxiv.org/abs/1", "https://arxiv.org/abs/2", "https://arxiv.org/abs/3"])
        self.addCleanup(kb.close)
        out = dict(disc.SourceDiscoverer(kb)._candidate_domains(skip={"mine.com"}, min_seen=3))
        self.assertNotIn("mine.com", out)
        self.assertNotIn("arxiv.org", out)


class TestAppendProposals(unittest.TestCase):
    def test_replaces_placeholder_then_appends(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "proposals.yml"
            p.write_text("# header\nproposals: []\n", encoding="utf-8")
            orig = disc._PROPOSALS
            disc._PROPOSALS = p
            try:
                disc._append_proposals([
                    {"name": "newblog.dev", "url": "https://newblog.dev/feed", "seen": 4,
                     "reason": "linked by 4 KB items; feed auto-discovered"}])
                text = p.read_text(encoding="utf-8")
                self.assertIn("candidate_url: https://newblog.dev/feed", text)
                self.assertIn("status: proposed", text)
                self.assertNotIn("proposals: []", text)
                self.assertIn("newblog.dev", disc._already_proposed())
            finally:
                disc._PROPOSALS = orig


if __name__ == "__main__":
    unittest.main()
