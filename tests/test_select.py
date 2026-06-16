"""notify._select_for_user — two-stage personalization selection (offline, sqlite :memory:).

Guards the backward-compat contract (no interest vector => relevance+affinity pick, gated by
min_score) and that an interest vector reorders toward semantically-matching items."""
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import embed  # noqa: E402
import notify  # noqa: E402


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE item(id INTEGER PRIMARY KEY, source_id INTEGER, title TEXT, url TEXT,"
        "  summary TEXT, published INTEGER);"
        "CREATE TABLE tag(item_id INTEGER, topic TEXT);"
        "CREATE TABLE signal(id INTEGER PRIMARY KEY, item_id INTEGER, kind TEXT, value REAL, ts INTEGER);"
        "CREATE TABLE embedding(item_id INTEGER PRIMARY KEY, vec BLOB, ts INTEGER);"
    )
    return con


def _add(con, iid, source_id, title, relevance, vec=None):
    con.execute("INSERT INTO item(id,source_id,title,url,summary,published) VALUES(?,?,?,?,?,?)",
                (iid, source_id, title, f"http://x/{iid}", "", 1000 + iid))
    con.execute("INSERT INTO tag(item_id,topic) VALUES(?,?)", (iid, f"t{iid}"))
    con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                (iid, "relevance", relevance, 0))
    if vec is not None:
        con.execute("INSERT INTO embedding(item_id,vec,ts) VALUES(?,?,?)", (iid, embed.pack(vec), 0))
    con.commit()


class TestSelectForUser(unittest.TestCase):
    def test_no_interest_is_relevance_pick_gated_by_min_score(self):
        con = _db()
        self.addCleanup(con.close)
        _add(con, 1, 10, "high relevance item", 90)
        _add(con, 2, 11, "low relevance item", 40)
        out = notify._select_for_user(con, "builder", top=5, min_score=60,
                                      interest_vec=None, interest_weight=0)
        ids = [d["id"] for d in out]
        self.assertEqual(ids, [1])               # only the 90 clears min_score 60
        self.assertEqual(out[0]["score"], 90)    # score == relevance when no interest/affinity

    def test_already_sent_items_excluded(self):
        con = _db()
        self.addCleanup(con.close)
        _add(con, 1, 10, "seen item", 90)
        con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'sent:builder',1,0)")
        con.commit()
        out = notify._select_for_user(con, "builder", top=5, min_score=0,
                                      interest_vec=None, interest_weight=0)
        self.assertEqual(out, [])

    def test_affinity_adds_to_score(self):
        con = _db()
        self.addCleanup(con.close)
        _add(con, 1, 10, "item", 50)
        con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'affinity:builder',12,0)")
        con.commit()
        out = notify._select_for_user(con, "builder", top=5, min_score=0,
                                      interest_vec=None, interest_weight=0)
        self.assertEqual(out[0]["score"], 62)

    def test_interest_can_lift_a_match_over_a_higher_relevance_nonmatch(self):
        con = _db()
        self.addCleanup(con.close)
        # item 1: higher relevance, off-interest vector. item 2: lower relevance, on-interest.
        _add(con, 1, 10, "off interest", 70, vec=[0.0, 1.0] + [0.0] * 254)
        _add(con, 2, 11, "on interest", 64, vec=[1.0, 0.0] + [0.0] * 254)
        interest = embed._normalize([1.0] + [0.0] * 255)
        out = notify._select_for_user(con, "builder", top=2, min_score=0,
                                      interest_vec=interest, interest_weight=15)
        # with a 15-pt z-scored spread, the on-interest item 2 should rank first.
        self.assertEqual(out[0]["id"], 2)

    def test_unembedded_scored_item_still_selectable_under_interest(self):
        # Regression (the 'Ponytail' bug): a high-relevance, unsent item with NO embedding must
        # not vanish when interest steering is on — it should still be a candidate.
        con = _db()
        self.addCleanup(con.close)
        _add(con, 1, 10, "embedded on-interest", 60, vec=[1.0, 0.0] + [0.0] * 254)
        _add(con, 2, 11, "scored but unembedded", 80)  # no vec
        interest = embed._normalize([1.0] + [0.0] * 255)
        out = notify._select_for_user(con, "builder", top=5, min_score=0,
                                      interest_vec=interest, interest_weight=15)
        self.assertIn(2, [d["id"] for d in out])


if __name__ == "__main__":
    unittest.main()
