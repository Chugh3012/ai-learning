import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.domain.brief import Brief, Card
from ai_scout.domain.item import PickReason, ScoredItem
from ai_scout.lib import vectors
from ai_scout.repositories.knowledge import KnowledgeBase
from ai_scout.services.brief_builder import BriefBuilder

class TestRenderBrief(unittest.TestCase):
    def test_cards_throughline_and_connection_in_output(self):
        items = [ScoredItem(
            id=1,
            title="Drop your system prompt",
            url="http://x/1",
            reasons=(PickReason(code="relevance", text="Strong ranking signal"),
                     PickReason(code="interest", text="Matches your stated interests")),
        )]
        brief = Brief(theme="Less instruction, more reliability",
                      cards={1: Card(lesson="Deleting the system prompt improved reliability.",
                                     try_it="Remove your system message and compare 5 outputs.")},
                      connections={1: ("Last week: prompt-as-questions", "http://x/old")})
        plain, html_out = BriefBuilder.render(items, brief, feedback_url="", tokens={})
        self.assertIn("Less instruction, more reliability", plain)
        self.assertIn("Less instruction, more reliability", html_out)
        self.assertIn("Deleting the system prompt", plain)
        self.assertIn("Why: Strong ranking signal; Matches your stated interests", plain)
        self.assertIn("Try:", plain)
        self.assertIn("Related: Last week: prompt-as-questions", plain)
        self.assertIn("Try:", html_out)
        self.assertIn("<b>Why:</b> Strong ranking signal; Matches your stated interests", html_out)
        self.assertIn("Read the source", html_out)

    def test_unsubscribe_footer_rendered_when_url_given(self):
        items = [ScoredItem(id=1, title="A pick", url="http://x/1")]
        brief = Brief(theme="", cards={}, connections={})
        url = "https://fn.example.net/api/unsubscribe?t=abc123"
        pref = "https://fn.example.net/api/preferences?t=abc123&p=prf_daily"
        saved = "https://fn.example.net/api/saved?t=abc123&p=prf_daily"
        plain, html_out = BriefBuilder.render(items, brief, unsubscribe_url=url,
                                              preference_url=pref, saved_url=saved)
        self.assertIn(saved, plain)
        self.assertIn("Saved library", plain)
        self.assertIn(saved.replace("&", "&amp;"), html_out)
        self.assertIn(">saved<", html_out)
        self.assertIn(pref, plain)
        self.assertIn("Preferences", plain)
        self.assertIn(pref.replace("&", "&amp;"), html_out)
        self.assertIn(">preferences<", html_out)
        self.assertIn(url, plain)
        self.assertIn("Unsubscribe", plain)
        self.assertIn(url, html_out)
        self.assertIn(">unsubscribe<", html_out)

    def test_no_unsubscribe_footer_without_url(self):
        items = [ScoredItem(id=1, title="A pick", url="http://x/1")]
        brief = Brief(theme="", cards={}, connections={})
        plain, html_out = BriefBuilder.render(items, brief)
        self.assertNotIn("Unsubscribe", plain)
        self.assertNotIn("Preferences", plain)
        self.assertNotIn("Saved library", plain)
        self.assertNotIn(">unsubscribe<", html_out)
        self.assertNotIn(">preferences<", html_out)
        self.assertNotIn(">saved<", html_out)

class TestConnections(unittest.TestCase):
    def _kb(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        kb = KnowledgeBase.open(path)
        self.addCleanup(kb.close)
        return kb

    def test_links_today_to_a_similar_past_pick(self):
        kb = self._kb()
        kb.con.execute("INSERT INTO item(id,title,url) VALUES(1,'today','u1'),(2,'past prompt-as-questions','u2')")
        kb.con.execute("INSERT INTO embedding(item_id,vec,ts) VALUES(1,?,0),(2,?,0)",
                       (vectors.pack([1.0, 0.0] + [0.0] * 254), vectors.pack([1.0, 0.0] + [0.0] * 254)))
        kb.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(2,'sent:primary',1,0)")
        kb.con.commit()
        out = BriefBuilder(kb, "", "")._connections("primary", [ScoredItem(id=1)], min_cos=0.5)
        self.assertEqual(out.get(1), ("past prompt-as-questions", "u2"))

    def test_no_similar_past_means_no_connection(self):
        kb = self._kb()
        kb.con.execute("INSERT INTO item(id,title,url) VALUES(1,'today','u1'),(2,'orthogonal','u2')")
        kb.con.execute("INSERT INTO embedding(item_id,vec,ts) VALUES(1,?,0),(2,?,0)",
                       (vectors.pack([1.0, 0.0] + [0.0] * 254), vectors.pack([0.0, 1.0] + [0.0] * 254)))
        kb.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(2,'sent:primary',1,0)")
        kb.con.commit()
        out = BriefBuilder(kb, "", "")._connections("primary", [ScoredItem(id=1)], min_cos=0.5)
        self.assertEqual(out, {})

if __name__ == "__main__":
    unittest.main()
