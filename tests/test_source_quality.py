import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.repositories.knowledge import KnowledgeBase
from prism.services.source_quality import SourceQualityDashboard

def _kb():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    return KnowledgeBase.open(path)

class TestSourceQuality(unittest.TestCase):
    def setUp(self):
        self.kb = _kb()
        self.addCleanup(self.kb.close)
        self.kb.con.executemany(
            "INSERT INTO source(id,title,url,category) VALUES(?,?,?,?)",
            [(1, "Useful Feed", "https://useful.example/feed", "Applied"),
             (2, "Noisy Feed", "https://noisy.example/feed", "News")],
        )
        self.kb.con.executemany(
            "INSERT INTO item(id,source_id,title,url,published) VALUES(?,?,?,?,?)",
            [(1, 1, "Good one", "https://useful.example/1", 1),
             (2, 1, "Good two", "https://useful.example/2", 2),
             (3, 2, "Weak one", "https://noisy.example/1", 3),
             (4, 2, "Weak two", "https://noisy.example/2", 4),
             (5, 2, "Weak three", "https://noisy.example/3", 5)],
        )
        self.kb.con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,0)",
            [(1, "relevance", 80), (2, "relevance", 70),
             (3, "relevance", 20), (4, "relevance", 40), (5, "relevance", 30),
             (1, "sent:usr_a:prf_main", 1), (2, "sent:usr_a:prf_main", 1),
             (3, "sent:usr_a:prf_main", 1), (4, "sent:usr_a:prf_main", 1),
             (1, "fb_save:usr_a:prf_main", 1), (1, "fb_click:usr_a:prf_main", 1),
             (2, "fb_vote:usr_a:prf_main", 1), (3, "fb_skip:usr_a:prf_main", 1),
             (4, "fb_skip:usr_a:prf_main", 1)],
        )
        self.kb.con.commit()

    def test_source_quality_counts_engagement(self):
        rows = {r["title"]: r for r in self.kb.source_quality()}
        self.assertEqual(rows["Useful Feed"]["quality_ranked_total"], 2)
        self.assertEqual(rows["Useful Feed"]["delivered_total"], 2)
        self.assertEqual(rows["Useful Feed"]["saves_total"], 1)
        self.assertEqual(rows["Useful Feed"]["clicks_total"], 1)
        self.assertEqual(rows["Useful Feed"]["positive_votes_total"], 1)
        self.assertEqual(rows["Noisy Feed"]["skips_total"], 2)

    def test_dashboard_ranks_sources_and_writes_markdown(self):
        dashboard = SourceQualityDashboard(self.kb)
        rows = dashboard.rows()
        by_title = {r.title: r for r in rows}
        self.assertGreater(by_title["Useful Feed"].score, by_title["Noisy Feed"].score)
        text = dashboard.render(rows)
        self.assertIn("Useful Feed", text)
        self.assertIn("Noisy Feed", text)
        self.assertIn("## Watchlist", text)
        with tempfile.TemporaryDirectory() as d:
            path = dashboard.write(Path(d) / "source-quality.md")
            self.assertIn("Source Quality Dashboard", path.read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
