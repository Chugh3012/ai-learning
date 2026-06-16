"""self_review — builder auto-votes keep/skip on delivered items (no PR / no human needed)."""
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import self_review  # noqa: E402


def _db(sent_ids, reviewed_ids=()):
    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE item(id INTEGER PRIMARY KEY, title TEXT, summary TEXT);"
        "CREATE TABLE signal(id INTEGER PRIMARY KEY, item_id INTEGER, kind TEXT, value REAL, ts INTEGER);")
    for i in set(sent_ids) | set(reviewed_ids):
        con.execute("INSERT INTO item(id,title,summary) VALUES(?,?,?)", (i, f"title {i}", "s"))
    for i in sent_ids:
        con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,1,0)", (i, "sent:builder"))
    for i in reviewed_ids:
        con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,1,0)", (i, "reviewed:builder"))
    con.commit()
    return con


class TestUnreviewed(unittest.TestCase):
    def test_only_unreviewed_delivered_items(self):
        con = _db(sent_ids=[1, 2, 3], reviewed_ids=[2])
        ids = sorted(r[0] for r in self_review._unreviewed(con, "builder"))
        self.assertEqual(ids, [1, 3])  # 2 already reviewed, others not sent


class TestSelfReview(unittest.TestCase):
    def test_votes_and_marks_reviewed(self):
        con = _db(sent_ids=[1, 2, 3])
        users = [{"id": "builder", "self_review": True, "interest": "x"}]
        env = {"FEEDBACK_STORAGE": "acct"}
        calls = []
        with mock.patch.object(self_review, "_judge", return_value={1: True, 2: False, 3: True}), \
             mock.patch("outcome_feedback.record_votes",
                        side_effect=lambda a, u, items, v: calls.append((sorted(items), v)) or len(items)):
            n = self_review.self_review(con, users, env, "ep", "mini")
        self.assertEqual(n, 3)
        self.assertIn(([1, 3], 1.0), calls)    # keeps -> 👍
        self.assertIn(([2], -1.0), calls)      # skip -> 👎
        marked = sorted(r[0] for r in con.execute("SELECT item_id FROM signal WHERE kind='reviewed:builder'"))
        self.assertEqual(marked, [1, 2, 3])    # all marked so re-runs don't re-vote

    def test_idempotent_second_run_noop(self):
        con = _db(sent_ids=[1, 2], reviewed_ids=[1, 2])
        users = [{"id": "builder", "self_review": True}]
        with mock.patch.object(self_review, "_judge", return_value={}) as j:
            n = self_review.self_review(con, users, {"FEEDBACK_STORAGE": "a"}, "ep", "m")
        self.assertEqual(n, 0)
        j.assert_not_called()  # nothing unreviewed -> LLM never invoked

    def test_skips_users_without_flag(self):
        con = _db(sent_ids=[1])
        users = [{"id": "primary"}]  # no self_review
        with mock.patch.object(self_review, "_judge") as j:
            n = self_review.self_review(con, users, {"FEEDBACK_STORAGE": "a"}, "ep", "m")
        self.assertEqual(n, 0)
        j.assert_not_called()


if __name__ == "__main__":
    unittest.main()
