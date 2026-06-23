import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.domain.item import ScoredItem
from prism.lib import vectors
from prism.repositories.knowledge import KnowledgeBase
from prism.services.selector import Selector
from prism.services.personalization.explorer import EpsilonExplorer

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
        out = Selector(kb).select("builder", top=5, min_score=0)
        self.assertEqual(out[0].score, 62)
        self.assertIn("affinity", [r.code for r in out[0].reasons])

    def test_interest_lifts_a_match_over_higher_relevance_nonmatch(self):
        kb = _kb()
        self.addCleanup(kb.close)
        _add(kb, 1, 10, "off interest", 70, vec=[0.0, 1.0] + [0.0] * 254)
        _add(kb, 2, 11, "on interest", 64, vec=[1.0, 0.0] + [0.0] * 254)
        interest = vectors.normalize([1.0] + [0.0] * 255)
        out = Selector(kb).select("builder", top=2, min_score=0, interest_vec=interest, weight=15)
        self.assertEqual(out[0].id, 2)
        self.assertIn("interest", [r.code for r in out[0].reasons])

    def test_unembedded_scored_item_still_selectable_under_interest(self):
        kb = _kb()
        self.addCleanup(kb.close)
        _add(kb, 1, 10, "embedded on-interest", 60, vec=[1.0, 0.0] + [0.0] * 254)
        _add(kb, 2, 11, "scored but unembedded", 80)
        interest = vectors.normalize([1.0] + [0.0] * 255)
        out = Selector(kb).select("builder", top=5, min_score=0, interest_vec=interest, weight=15)
        self.assertIn(2, [d.id for d in out])

    def test_explore_slot_gets_reason(self):
        items = [ScoredItem(id=i, score=float(100 - i)) for i in range(1, 6)]
        out = EpsilonExplorer(0.34, random.Random(0)).choose(items, top=3)
        codes = [r.code for it in out for r in it.reasons]
        self.assertIn("exploration", codes)

class _EmbKB:
    def __init__(self, emb):
        self._emb = emb

    def embedded_candidates(self, lens, limit, topic_id=None):
        return self._emb

class TestInterestRetrieval(unittest.TestCase):
    @staticmethod
    def _row(iid, vec, rel=20.0):
        return (iid, f"t{iid}", "u", "", iid, None, rel, 0.0, vectors.pack(vec), "c")

    def test_interest_pulls_matching_item_into_pool(self):
        # item 3 is not in the relevance pool but matches the interest -> retrieval adds it.
        rel_rows = [self._row(1, [1.0, 0.0, 0.0, 0.0], rel=90)]
        pool = [self._row(2, [1.0, 0.0, 0.0, 0.0]), self._row(3, [0.0, 1.0, 0.0, 0.0])]
        out = Selector(_EmbKB(pool))._add_interest_candidates(
            rel_rows, "L", vectors.normalize([0.0, 1.0, 0.0, 0.0]), 50, None)
        self.assertIn(3, [r[0] for r in out])

    def test_different_interests_pull_different_items(self):
        pool = [self._row(2, [1.0, 0.0, 0.0, 0.0]), self._row(3, [0.0, 1.0, 0.0, 0.0])]
        sel = Selector(_EmbKB(pool))
        a = sel._add_interest_candidates([], "L", vectors.normalize([1.0, 0.0, 0.0, 0.0]), 1, None)
        b = sel._add_interest_candidates([], "L", vectors.normalize([0.0, 1.0, 0.0, 0.0]), 1, None)
        self.assertEqual([r[0] for r in a], [2])
        self.assertEqual([r[0] for r in b], [3])

    def test_no_interest_is_a_noop(self):
        pool = [self._row(2, [1.0, 0.0, 0.0, 0.0])]
        self.assertEqual(Selector(_EmbKB(pool))._add_interest_candidates([], "L", None, 5, None), [])


if __name__ == "__main__":
    unittest.main()
