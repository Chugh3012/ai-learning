import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.lib import vectors
from prism.repositories.knowledge import KnowledgeBase
from prism.services.personalization.taste import TasteModel, recency_weight
from prism.services.personalization.novelty import novelty_penalties

LENS = "u:p"

class TestDecay(unittest.TestCase):
    def test_zero_age_is_full_weight(self):
        self.assertAlmostEqual(recency_weight(0, 30), 1.0, places=6)

    def test_one_half_life_halves(self):
        self.assertAlmostEqual(recency_weight(30 * 86400, 30), 0.5, places=6)

    def test_two_half_lives_quarter(self):
        self.assertAlmostEqual(recency_weight(60 * 86400, 30), 0.25, places=6)

    def test_disabled_when_half_life_non_positive(self):
        self.assertEqual(recency_weight(10 ** 9, 0), 1.0)

class TestTaste(unittest.TestCase):
    def _kb(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        kb = KnowledgeBase.open(path)
        self.addCleanup(kb.close)
        kb.con.execute("INSERT INTO source(id,title,topic_id) VALUES(1,'s','ai')")
        kb.con.commit()
        return kb

    def _engage(self, kb, iid, vec, sent_ts, gesture="fb_save", value=1.0):
        c = kb.con
        c.execute("INSERT INTO item(id,source_id,title,topic_id) VALUES(?,?,?,?)",
                  (iid, 1, "t%d" % iid, "ai"))
        c.execute("INSERT INTO embedding(item_id,vec,ts) VALUES(?,?,?)",
                  (iid, vectors.pack(vec), 0))
        c.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                  (iid, f"{gesture}:{LENS}", value, sent_ts))
        c.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                  (iid, f"sent:{LENS}", 1.0, sent_ts))
        c.commit()

    def test_cold_start_falls_back_to_interest(self):
        kb = self._kb()
        interest = vectors.normalize([0.0, 1.0, 0.0, 0.0])
        self.assertEqual(TasteModel(kb).user_vector(LENS, interest), interest)

    def test_no_interest_no_engagement_is_none(self):
        kb = self._kb()
        self.assertIsNone(TasteModel(kb).user_vector(LENS, None))

    def test_learned_vector_points_at_liked_item(self):
        kb = self._kb()
        self._engage(kb, 1, [1.0, 0.0, 0.0, 0.0], int(time.time()))
        vec = TasteModel(kb, blend=1.0).user_vector(LENS, None)
        self.assertIsNotNone(vec)
        self.assertGreater(vectors.dot(vec, [1.0, 0.0, 0.0, 0.0]), 0.99)

    def test_recent_like_dominates_old_like(self):
        kb = self._kb()
        now = int(time.time())
        self._engage(kb, 1, [1.0, 0.0, 0.0, 0.0], now)                 # recent
        self._engage(kb, 2, [0.0, 1.0, 0.0, 0.0], now - 200 * 86400)   # old
        vec = TasteModel(kb, half_life_days=30, blend=1.0).user_vector(LENS, None)
        self.assertGreater(vectors.dot(vec, [1.0, 0.0, 0.0, 0.0]),
                           vectors.dot(vec, [0.0, 1.0, 0.0, 0.0]))

    def test_blend_moves_between_learned_and_interest(self):
        kb = self._kb()
        self._engage(kb, 1, [1.0, 0.0, 0.0, 0.0], int(time.time()))
        interest = vectors.normalize([0.0, 1.0, 0.0, 0.0])
        learned_heavy = TasteModel(kb, blend=1.0).user_vector(LENS, interest)
        interest_heavy = TasteModel(kb, blend=0.0).user_vector(LENS, interest)
        liked = [1.0, 0.0, 0.0, 0.0]
        self.assertGreater(vectors.dot(learned_heavy, liked), vectors.dot(interest_heavy, liked))

class TestNovelty(unittest.TestCase):
    def test_penalizes_items_close_to_history(self):
        hist = [vectors.pack([1.0, 0.0, 0.0, 0.0])]
        cands = {1: vectors.pack([1.0, 0.0, 0.0, 0.0]),
                 2: vectors.pack([0.0, 1.0, 0.0, 0.0])}
        pen = novelty_penalties(hist, cands, weight=6.0)
        self.assertAlmostEqual(pen[1], 6.0, places=4)
        self.assertGreater(pen[1], pen.get(2, 0.0))

    def test_disabled_and_empty_cases(self):
        one = {1: vectors.pack([1.0, 0.0])}
        self.assertEqual(novelty_penalties([vectors.pack([1.0, 0.0])], one, 0.0), {})
        self.assertEqual(novelty_penalties([], one, 6.0), {})

if __name__ == "__main__":
    unittest.main()
