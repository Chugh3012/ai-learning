import os
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.repositories.feedback import FeedbackStore
from ai_scout.repositories.knowledge import KnowledgeBase
from ai_scout.services.feedback_service import FeedbackService

LENS = "usr_x:prf_main"

def _kb():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    return KnowledgeBase.open(path)

def _svc(kb):
    return FeedbackService(kb, FeedbackStore(""))

class TestAgeSkips(unittest.TestCase):
    def setUp(self):
        self.kb = _kb()
        self.addCleanup(self.kb.close)
        self.now = int(time.time())
        self.old = self.now - 5 * 86400
        self.recent = self.now - 3600

    def _skips(self):
        return sorted(r[0] for r in self.kb.con.execute(
            f"SELECT item_id FROM signal WHERE kind='fb_skip:{LENS}'"))

    def test_stale_unactioned_becomes_skip(self):
        self.kb.con.execute(f"INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'sent:{LENS}',1,?)", (self.old,))
        self.kb.con.commit()
        _svc(self.kb)._age_skips(LENS, self.now)
        self.assertEqual(self._skips(), [1])

    def test_recent_delivery_not_yet_skipped(self):
        self.kb.con.execute(f"INSERT INTO signal(item_id,kind,value,ts) VALUES(3,'sent:{LENS}',1,?)", (self.recent,))
        self.kb.con.commit()
        _svc(self.kb)._age_skips(LENS, self.now)
        self.assertEqual(self._skips(), [])

    def test_actioned_item_not_skipped(self):
        self.kb.con.executemany("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                                [(2, f"sent:{LENS}", 1, self.old), (2, f"fb_vote:{LENS}", 1, self.now)])
        self.kb.con.commit()
        _svc(self.kb)._age_skips(LENS, self.now)
        self.assertEqual(self._skips(), [])

    def test_idempotent_and_self_healing(self):
        self.kb.con.execute(f"INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'sent:{LENS}',1,?)", (self.old,))
        self.kb.con.commit()
        svc = _svc(self.kb)
        svc._age_skips(LENS, self.now)
        svc._age_skips(LENS, self.now)
        self.assertEqual(self._skips(), [1])
        self.kb.con.execute(f"INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'fb_vote:{LENS}',1,?)", (self.now,))
        self.kb.con.commit()
        svc._age_skips(LENS, self.now)
        self.assertEqual(self._skips(), [])

class TestRecomputeAffinity(unittest.TestCase):
    def setUp(self):
        self.kb = _kb()
        self.addCleanup(self.kb.close)
        self.now = int(time.time())
        self.kb.con.executemany("INSERT INTO item(id,source_id) VALUES(?,?)",
                                [(1, 10), (2, 10), (3, 20), (4, 20)])
        self.kb.con.executemany("INSERT INTO tag(item_id,topic) VALUES(?,?)",
                                [(1, "agents"), (2, "agents"), (3, "vision"), (4, "vision")])
        self.kb.con.executemany("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                                [(i, "relevance", 50, self.now) for i in (1, 2, 3, 4)])

    def _aff(self):
        return {r[0]: r[1] for r in self.kb.con.execute(
            f"SELECT item_id, value FROM signal WHERE kind='affinity:{LENS}'")}

    def test_upvote_lifts_same_source_and_topic(self):
        self.kb.con.execute(f"INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'fb_vote:{LENS}',1,?)", (self.now,))
        self.kb.con.commit()
        _svc(self.kb)._recompute_affinity(LENS, self.now)
        aff = self._aff()
        self.assertGreater(aff.get(1, 0), 0)
        self.assertGreater(aff.get(2, 0), 0)
        self.assertEqual(aff.get(3, 0) or 0, 0)

    def test_skip_is_mild_negative(self):
        self.kb.con.execute(f"INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'fb_skip:{LENS}',1,?)", (self.now,))
        self.kb.con.commit()
        _svc(self.kb)._recompute_affinity(LENS, self.now)
        self.assertLess(self._aff().get(1, 0), 0)

    def test_affinity_is_bounded(self):
        self.kb.con.executemany("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                                [(1, f"fb_vote:{LENS}", 5, self.now)])
        self.kb.con.commit()
        _svc(self.kb)._recompute_affinity(LENS, self.now)
        self.assertLessEqual(abs(self._aff().get(1, 0)), 20.0001)

class _FakeTable:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def upsert_entity(self, entity, mode=None):
        self.rows[str(entity["RowKey"])] = dict(entity)

    def query_entities(self, query, parameters=None):
        cut = (parameters or {}).get("cut", 0)
        return [r for r in self.rows.values() if int(r.get("ts", 0)) < cut]

    def delete_entity(self, pk, rk):
        self.rows.pop(str(rk), None)

class TestTokenTTL(unittest.TestCase):
    def setUp(self):
        self.table = _FakeTable()
        self.store = FeedbackStore("acct")
        self.patch = mock.patch.object(self.store, "_table", return_value=self.table)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_minted_tokens_carry_expiry(self):
        self.store.mint_tokens(LENS, [(1, "t", "http://x")])
        self.assertTrue(self.table.rows)
        for row in self.table.rows.values():
            self.assertGreater(int(row["expiresTs"]), int(row["ts"]))

    def test_purge_removes_only_expired(self):
        now = int(time.time())
        self.table.rows = {
            "old": {"PartitionKey": "tok", "RowKey": "old", "ts": now - 200 * 86400},
            "fresh": {"PartitionKey": "tok", "RowKey": "fresh", "ts": now},
        }
        removed = self.store.purge_expired_tokens()
        self.assertEqual(removed, 1)
        self.assertIn("fresh", self.table.rows)
        self.assertNotIn("old", self.table.rows)

if __name__ == "__main__":
    unittest.main()
