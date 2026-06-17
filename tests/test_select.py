import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.lib import vectors
from ai_scout.repositories.knowledge import KnowledgeBase
from ai_scout.services.selector import Selector

def _kb():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    return KnowledgeBase.open(path)

def _add(kb, iid, source_id, title, relevance, vec=None):
    con = kb.con
    con.execute("INSERT OR IGNORE INTO source(id,title,category) VALUES(?,?,?)",
                (source_id, f"src{source_id}", f"cat{source_id}"))
    con.execute("INSERT INTO item(id,source_id,title,url,summary,published) VALUES(?,?,?,?,?,?)",
                (iid, source_id, title, f"http://x/{iid}", "", 1000 + iid))
    con.execute("INSERT INTO tag(item_id,topic) VALUES(?,?)", (iid, f"t{iid}"))
    con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)", (iid, "relevance", relevance, 0))
    if vec is not None:
        con.execute("INSERT INTO embedding(item_id,vec,ts) VALUES(?,?,?)", (iid, vectors.pack(vec), 0))
    con.commit()

class TestSelect(unittest.TestCase):
    def test_no_interest_is_relevance_pick_gated_by_min_score(self):
        kb = _kb()
        self.addCleanup(kb.close)
        _add(kb, 1, 10, "high relevance item", 90)
        _add(kb, 2, 11, "low relevance item", 40)
        out = Selector(kb).select("builder", top=5, min_score=60)
        self.assertEqual([d.id for d in out], [1])
        self.assertEqual(out[0].score, 90)

    def test_already_sent_excluded(self):
        kb = _kb()
        self.addCleanup(kb.close)
        _add(kb, 1, 10, "seen item", 90)
        kb.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'sent:builder',1,0)")
        kb.con.commit()
        self.assertEqual(Selector(kb).select("builder", top=5, min_score=0), [])

    def test_affinity_adds_to_score(self):
        kb = _kb()
        self.addCleanup(kb.close)
        _add(kb, 1, 10, "item", 50)
        kb.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'affinity:builder',12,0)")
        kb.con.commit()
        self.assertEqual(Selector(kb).select("builder", top=5, min_score=0)[0].score, 62)

    def test_interest_lifts_a_match_over_higher_relevance_nonmatch(self):
        kb = _kb()
        self.addCleanup(kb.close)
        _add(kb, 1, 10, "off interest", 70, vec=[0.0, 1.0] + [0.0] * 254)
        _add(kb, 2, 11, "on interest", 64, vec=[1.0, 0.0] + [0.0] * 254)
        interest = vectors.normalize([1.0] + [0.0] * 255)
        out = Selector(kb).select("builder", top=2, min_score=0, interest_vec=interest, weight=15)
        self.assertEqual(out[0].id, 2)

    def test_unembedded_scored_item_still_selectable_under_interest(self):
        kb = _kb()
        self.addCleanup(kb.close)
        _add(kb, 1, 10, "embedded on-interest", 60, vec=[1.0, 0.0] + [0.0] * 254)
        _add(kb, 2, 11, "scored but unembedded", 80)
        interest = vectors.normalize([1.0] + [0.0] * 255)
        out = Selector(kb).select("builder", top=5, min_score=0, interest_vec=interest, weight=15)
        self.assertIn(2, [d.id for d in out])

if __name__ == "__main__":
    unittest.main()
