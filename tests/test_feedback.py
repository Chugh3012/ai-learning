"""feedback_ingest — implicit 'skip' aging + affinity recompute (the additive-feedback core).

Uses sqlite :memory: with the minimal schema these functions touch. No Azure/network."""
import sqlite3
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import feedback_ingest as fi  # noqa: E402


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE item(id INTEGER PRIMARY KEY, source_id INTEGER);"
        "CREATE TABLE tag(item_id INTEGER, topic TEXT);"
        "CREATE TABLE signal(id INTEGER PRIMARY KEY, item_id INTEGER, kind TEXT, value REAL, ts INTEGER);"
    )
    return con


class TestAgeOutSkips(unittest.TestCase):
    def setUp(self):
        self.con = _db()
        self.addCleanup(self.con.close)
        self.now = int(time.time())
        self.old = self.now - 5 * 86400      # older than skip_days (default 2)
        self.recent = self.now - 3600        # within skip_days

    def _skips(self):
        return sorted(r[0] for r in self.con.execute(
            "SELECT item_id FROM signal WHERE kind='fb_skip:builder'"))

    def test_stale_unactioned_becomes_skip(self):
        self.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'sent:builder',1,?)", (self.old,))
        self.con.commit()
        fi._age_out_skips(self.con, "builder", self.now)
        self.assertEqual(self._skips(), [1])

    def test_recent_delivery_not_yet_skipped(self):
        self.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(3,'sent:builder',1,?)", (self.recent,))
        self.con.commit()
        fi._age_out_skips(self.con, "builder", self.now)
        self.assertEqual(self._skips(), [])

    def test_actioned_item_not_skipped(self):
        self.con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
            [(2, "sent:builder", 1, self.old), (2, "fb_vote:builder", 1, self.now)])
        self.con.commit()
        fi._age_out_skips(self.con, "builder", self.now)
        self.assertEqual(self._skips(), [])

    def test_idempotent_and_self_healing(self):
        # stale -> skip; running twice doesn't duplicate; a later vote removes the skip.
        self.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'sent:builder',1,?)", (self.old,))
        self.con.commit()
        fi._age_out_skips(self.con, "builder", self.now)
        fi._age_out_skips(self.con, "builder", self.now)
        self.assertEqual(self._skips(), [1])  # no duplicate
        self.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'fb_vote:builder',1,?)", (self.now,))
        self.con.commit()
        fi._age_out_skips(self.con, "builder", self.now)
        self.assertEqual(self._skips(), [])

    def test_users_are_isolated(self):
        self.con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
            [(1, "sent:builder", 1, self.old), (2, "sent:primary", 1, self.old)])
        self.con.commit()
        fi._age_out_skips(self.con, "builder", self.now)
        self.assertEqual(self._skips(), [1])  # primary's item 2 untouched


class TestRecomputeAffinity(unittest.TestCase):
    def setUp(self):
        self.con = _db()
        self.addCleanup(self.con.close)
        self.now = int(time.time())
        # two sources, two items each w/ a topic + relevance (rank-eligible)
        self.con.executemany("INSERT INTO item(id,source_id) VALUES(?,?)",
                             [(1, 10), (2, 10), (3, 20), (4, 20)])
        self.con.executemany("INSERT INTO tag(item_id,topic) VALUES(?,?)",
                             [(1, "agents"), (2, "agents"), (3, "vision"), (4, "vision")])
        self.con.executemany("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                             [(i, "relevance", 50, self.now) for i in (1, 2, 3, 4)])

    def _aff(self):
        return {r[0]: r[1] for r in self.con.execute(
            "SELECT item_id, value FROM signal WHERE kind='affinity:builder'")}

    def test_upvote_lifts_same_source_and_topic(self):
        # 👍 item 1 -> source 10 and topic 'agents' get positive affinity -> item 2 also lifted.
        self.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'fb_vote:builder',1,?)", (self.now,))
        self.con.commit()
        fi._recompute_affinity(self.con, "builder", self.now)
        aff = self._aff()
        self.assertGreater(aff.get(1, 0), 0)
        self.assertGreater(aff.get(2, 0), 0)   # sibling via shared source+topic
        self.assertEqual(aff.get(3, 0) or 0, 0)  # unrelated source/topic unaffected

    def test_skip_is_mild_negative(self):
        self.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'fb_skip:builder',1,?)", (self.now,))
        self.con.commit()
        fi._recompute_affinity(self.con, "builder", self.now)
        self.assertLess(self._aff().get(1, 0), 0)

    def test_affinity_is_bounded(self):
        # piling votes can't blow past the influence budget (source 12 + topic 8 = 20 max).
        self.con.executemany("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                             [(1, "fb_vote:builder", 5, self.now)])
        self.con.commit()
        fi._recompute_affinity(self.con, "builder", self.now)
        self.assertLessEqual(abs(self._aff().get(1, 0)), 20.0001)


if __name__ == "__main__":
    unittest.main()
