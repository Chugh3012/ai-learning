import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.repositories.knowledge import KnowledgeBase
from prism.services.synthesis import WeeklySynthesis

def _kb():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    return KnowledgeBase.open(path)

class TestRecentSentTitles(unittest.TestCase):
    def test_window_filters_old(self):
        kb = _kb()
        self.addCleanup(kb.close)
        now = int(time.time())
        kb.con.execute("INSERT INTO item(id,title) VALUES(1,'recent'),(2,'old')")
        kb.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'sent:L',1,?)", (now,))
        kb.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(2,'sent:L',1,?)",
                       (now - 30 * 86400,))
        kb.con.commit()
        self.assertEqual(kb.recent_sent_titles("L", days=7), ["recent"])

class TestRecapGraceful(unittest.TestCase):
    def test_no_endpoint_returns_empty(self):
        kb = _kb()
        self.addCleanup(kb.close)
        self.assertEqual(WeeklySynthesis(kb, "", "m").recap("L"), "")

    def test_too_few_items_returns_empty_without_calling_model(self):
        kb = _kb()
        self.addCleanup(kb.close)
        kb.con.execute("INSERT INTO item(id,title) VALUES(1,'a')")
        kb.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(1,'sent:L',1,?)",
                       (int(time.time()),))
        kb.con.commit()
        # endpoint set but <3 items: returns "" before any client/network call
        self.assertEqual(WeeklySynthesis(kb, "https://example.invalid", "m").recap("L"), "")

if __name__ == "__main__":
    unittest.main()
