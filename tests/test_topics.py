import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.lib import topics
from prism.repositories.knowledge import KnowledgeBase

class TestTopicPacks(unittest.TestCase):
    def test_ai_pack_loads(self):
        p = topics.load_pack("ai")
        self.assertTrue(p.rubric.strip())
        self.assertTrue(p.golden.exists())
        self.assertIn("min", p.thresholds)

    def test_list_topics_includes_both(self):
        ts = topics.list_topics()
        self.assertIn("ai", ts)
        self.assertIn("politics", ts)

    def test_unknown_pack_is_graceful(self):
        p = topics.load_pack("does-not-exist")
        self.assertEqual(p.rubric, "")
        self.assertEqual(p.tags, {})
        self.assertFalse(p.golden.exists())
        self.assertEqual(p.settings, {})

class TestTopicFilter(unittest.TestCase):
    def _kb(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        kb = KnowledgeBase.open(path)
        self.addCleanup(kb.close)
        return kb

    def test_candidates_filter_by_topic(self):
        kb = self._kb()
        c = kb.con
        c.execute("INSERT INTO source(id,title,category,topic_id) VALUES(1,'s','c','ai')")
        c.execute("INSERT INTO source(id,title,category,topic_id) VALUES(2,'s2','c','politics')")
        for i, (t, sid) in enumerate([("ai", 1), ("politics", 2)], 1):
            c.execute("INSERT INTO item(id,source_id,title,url,summary,published,topic_id) "
                      "VALUES(?,?,?,?,?,?,?)", (i, sid, "t%d" % i, "http://x/%d" % i, "", 1000 + i, t))
            c.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                      (i, "relevance", 90, 0))
        c.commit()
        self.assertEqual([r[0] for r in kb.candidates("L", 50, "ai")], [1])
        self.assertEqual([r[0] for r in kb.candidates("L", 50, "politics")], [2])
        self.assertEqual(sorted(r[0] for r in kb.candidates("L", 50, None)), [1, 2])

    def test_backfill_sets_null_topic_to_ai(self):
        kb = self._kb()
        kb.con.execute("INSERT INTO source(id,title,topic_id) VALUES(1,'s',NULL)")
        kb.con.execute("INSERT INTO item(id,source_id,title,topic_id) VALUES(1,1,'t',NULL)")
        kb.con.commit()
        KnowledgeBase._backfill_topic(kb.con)
        self.assertEqual(kb.con.execute("SELECT topic_id FROM item WHERE id=1").fetchone()[0], "ai")

if __name__ == "__main__":
    unittest.main()
