"""notify learning-brief rendering + connect-the-dots (offline, no Azure/model)."""
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import embed  # noqa: E402
import notify  # noqa: E402


class TestRenderBrief(unittest.TestCase):
    def test_cards_throughline_and_connection_in_output(self):
        items = [(1, "Drop your system prompt", "http://x/1")]
        cards = {1: {"lesson": "Deleting the system prompt improved reliability.",
                     "try": "Remove your system message and compare 5 outputs.",
                     "what": "A practitioner's writeup."}}
        conn = {1: ("Last week: prompt-as-questions", "http://x/old")}
        plain, html_out = notify._render(items, "Less instruction, more reliability", cards,
                                         conn, feedback_url="", tokens={})
        # throughline present in both
        self.assertIn("Less instruction, more reliability", plain)
        self.assertIn("Less instruction, more reliability", html_out)
        # the three card fields + connection render in plain text
        self.assertIn("Deleting the system prompt", plain)
        self.assertIn("Try:", plain)
        self.assertIn("Builds on: Last week: prompt-as-questions", plain)
        # html escapes + includes the try-box and source link
        self.assertIn("Try:", html_out)
        self.assertIn("Read the source", html_out)

    def test_empty_fields_degrade_gracefully(self):
        items = [(2, "Just a release", "http://x/2")]
        cards = {2: {"lesson": "", "try": "", "what": ""}}
        plain, html_out = notify._render(items, "", cards, {}, "", {})
        self.assertIn("Just a release", plain)        # title still shown
        self.assertIn("http://x/2", plain)            # link still shown
        self.assertNotIn("Try:", plain)               # no empty try line
        self.assertNotIn("Builds on:", plain)         # no connection

    def test_feedback_links_render_when_configured(self):
        items = [(3, "Item", "http://x/3")]
        cards = {3: {"lesson": "L", "try": "", "what": ""}}
        tokens = {3: {"up": "U", "down": "D", "save": "S", "click": "C"}}
        plain, html_out = notify._render(items, "", cards, {}, "https://fb", tokens)
        self.assertIn("https://fb?t=U", plain)
        self.assertIn("https://fb?t=C", html_out)     # click-tracked source


class TestConnections(unittest.TestCase):
    def _db(self):
        con = sqlite3.connect(":memory:")
        self.addCleanup(con.close)
        con.executescript(
            "CREATE TABLE item(id INTEGER PRIMARY KEY, title TEXT, url TEXT);"
            "CREATE TABLE signal(id INTEGER PRIMARY KEY, item_id INTEGER, kind TEXT, value REAL, ts INTEGER);"
            "CREATE TABLE embedding(item_id INTEGER PRIMARY KEY, vec BLOB, ts INTEGER);")
        return con

    def _add(self, con, iid, title, vec, sent=False):
        con.execute("INSERT INTO item(id,title,url) VALUES(?,?,?)", (iid, title, f"http://x/{iid}"))
        con.execute("INSERT INTO embedding(item_id,vec,ts) VALUES(?,?,0)", (iid, embed.pack(vec)))
        if sent:
            con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,1,0)", (iid, "sent:primary"))
        con.commit()

    def test_links_today_pick_to_nearest_past_sent_item(self):
        con = self._db()
        # past item 10 (sent) close to today's item 1; past item 11 (sent) orthogonal
        self._add(con, 10, "Past close", embed._normalize([1.0, 0.05] + [0.0] * 254), sent=True)
        self._add(con, 11, "Past far", embed._normalize([0.0, 0.0, 1.0] + [0.0] * 253), sent=True)
        self._add(con, 1, "Today", embed._normalize([1.0, 0.0] + [0.0] * 254), sent=False)
        out = notify._connections(con, "primary", [{"id": 1}], min_cos=0.5)
        self.assertIn(1, out)
        self.assertEqual(out[1][0], "Past close")     # nearest neighbour, not the far one

    def test_no_link_below_threshold(self):
        con = self._db()
        self._add(con, 10, "Past orthogonal", embed._normalize([0.0, 1.0] + [0.0] * 254), sent=True)
        self._add(con, 1, "Today", embed._normalize([1.0, 0.0] + [0.0] * 254), sent=False)
        out = notify._connections(con, "primary", [{"id": 1}], min_cos=0.5)
        self.assertEqual(out, {})                     # cosine 0 < 0.5 -> no spurious link

    def test_ignores_unsent_history(self):
        con = self._db()
        self._add(con, 10, "Embedded but never sent", embed._normalize([1.0, 0.0] + [0.0] * 254), sent=False)
        self._add(con, 1, "Today", embed._normalize([1.0, 0.0] + [0.0] * 254), sent=False)
        out = notify._connections(con, "primary", [{"id": 1}], min_cos=0.5)
        self.assertEqual(out, {})                     # only previously-SENT items can be linked


if __name__ == "__main__":
    unittest.main()
