import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.repositories.knowledge import KnowledgeBase

class TestSchemaReconcile(unittest.TestCase):
    def test_adds_missing_columns_to_a_preexisting_table(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE embedding (item_id INTEGER PRIMARY KEY)")
            con.commit()
            con.close()

            kb = KnowledgeBase.open(path)
            cols = {r[1] for r in kb.con.execute("PRAGMA table_info(embedding)").fetchall()}
            kb.close()

            self.assertIn("vec", cols)
            self.assertIn("ts", cols)
        finally:
            os.unlink(path)

    def test_fresh_db_creates_full_schema(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            kb = KnowledgeBase.open(path)
            tables = {r[0] for r in kb.con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            kb.close()
            self.assertTrue({"source", "item", "tag", "signal", "embedding"}.issubset(tables))
        finally:
            os.unlink(path)

if __name__ == "__main__":
    unittest.main()
