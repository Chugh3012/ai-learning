"""KnowledgeBase — the owned SQLite knowledge base (items, signals, embeddings, drafts, sources).

This is the ONLY module that issues SQL against the KB. Services receive a KnowledgeBase by
constructor injection and call its methods — no raw SQL leaks into the business logic. The
generic `signal(item_id, kind, value, ts)` table holds everything (relevance, affinity:<lens>,
sent:<lens>, fb_*:<lens>): new signal kinds need no migration.
"""
from __future__ import annotations

import sqlite3
import time

from ai_scout.lib.config import KB_DIR, KB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source(
  id INTEGER PRIMARY KEY, title TEXT, url TEXT UNIQUE, kind TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS item(
  id INTEGER PRIMARY KEY,
  source_id INTEGER REFERENCES source(id),
  title TEXT, url TEXT, summary TEXT,
  published INTEGER, fetched_at INTEGER, hash TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS tag(
  item_id INTEGER REFERENCES item(id), topic TEXT,
  PRIMARY KEY(item_id, topic));
CREATE TABLE IF NOT EXISTS signal(
  id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES item(id),
  kind TEXT, value REAL, ts INTEGER);
CREATE TABLE IF NOT EXISTS draft(
  id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES item(id) UNIQUE,
  status TEXT, body TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS embedding(
  item_id INTEGER PRIMARY KEY REFERENCES item(id), vec BLOB, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_item_published ON item(published);
"""


class KnowledgeBase:
    """Owns a sqlite connection to the KB and exposes every query the services need."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    @classmethod
    def open(cls, path=None) -> "KnowledgeBase":
        KB_DIR.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path or KB_PATH))
        con.executescript(_SCHEMA)
        return cls(con)

    def close(self) -> None:
        self.con.close()

    def commit(self) -> None:
        self.con.commit()

    # ---- ingest (sync) ----
    def upsert_source(self, s: dict) -> int:
        self.con.execute(
            "INSERT INTO source(title,url,kind,category) VALUES(?,?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET title=excluded.title, category=excluded.category",
            (s["title"], s["url"], "feed", s["category"]),
        )
        return self.con.execute("SELECT id FROM source WHERE url=?", (s["url"],)).fetchone()[0]

    def insert_item(self, source_id: int, title: str, url: str, summary: str,
                    published: int, now: int, h: str) -> int | None:
        """Insert one item if new (dedup by hash). Returns the new item id, or None if duplicate."""
        cur = self.con.execute(
            "INSERT OR IGNORE INTO item(source_id,title,url,summary,published,fetched_at,hash) "
            "VALUES(?,?,?,?,?,?,?)",
            (source_id, title, url, summary, published, now, h),
        )
        if not cur.rowcount:
            return None
        return self.con.execute("SELECT id FROM item WHERE hash=?", (h,)).fetchone()[0]

    def add_tag(self, item_id: int, topic: str) -> None:
        self.con.execute("INSERT OR IGNORE INTO tag(item_id,topic) VALUES(?,?)", (item_id, topic))

    def item_count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM item").fetchone()[0]

    # ---- ranking ----
    def unscored_recent(self, days: int, max_items: int) -> list[tuple]:
        cutoff = int(time.time()) - days * 86400
        return self.con.execute(
            "SELECT i.id, i.title, i.summary FROM item i "
            "WHERE i.published >= ? AND NOT EXISTS "
            "(SELECT 1 FROM signal s WHERE s.item_id=i.id AND s.kind='relevance') "
            "ORDER BY i.published DESC LIMIT ?",
            (cutoff, max_items),
        ).fetchall()

    def add_relevance(self, item_id: int, score: float, now: int) -> None:
        self.con.execute("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
                         (item_id, "relevance", float(score), now))

    # ---- embeddings ----
    def unembedded_ranked(self, max_items: int) -> list[tuple]:
        return self.con.execute(
            "SELECT i.id, i.title, i.summary FROM item i "
            "JOIN signal s ON s.item_id=i.id AND s.kind='relevance' "
            "WHERE NOT EXISTS (SELECT 1 FROM embedding e WHERE e.item_id=i.id) "
            "GROUP BY i.id ORDER BY i.published DESC LIMIT ?",
            (max_items,),
        ).fetchall()

    def add_embeddings(self, rows: list[tuple[int, bytes]], now: int) -> None:
        self.con.executemany(
            "INSERT OR REPLACE INTO embedding(item_id,vec,ts) VALUES(?,?,?)",
            [(iid, blob, now) for iid, blob in rows],
        )

    def embedding_of(self, item_id: int) -> bytes | None:
        row = self.con.execute("SELECT vec FROM embedding WHERE item_id=?", (item_id,)).fetchone()
        return row[0] if row and row[0] else None

    def sent_with_embeddings(self, lens: str, exclude: set[int]) -> list[tuple]:
        """(item_id, title, url, vec) for items this lens was sent that carry an embedding."""
        rows = self.con.execute(
            "SELECT e.item_id, i.title, i.url, e.vec FROM embedding e "
            "JOIN item i ON i.id=e.item_id "
            "JOIN signal s ON s.item_id=e.item_id AND s.kind=? ",
            (f"sent:{lens}",),
        ).fetchall()
        return [(pid, t, u, v) for pid, t, u, v in rows if pid not in exclude and v]

    # ---- selection ----
    def candidates(self, lens: str, limit: int) -> list[tuple]:
        """Rank-eligible items NOT yet sent to this lens, with relevance, this lens's affinity,
        embedding and category — ordered by (relevance + affinity)."""
        return self.con.execute(
            "SELECT i.id, i.title, i.url, i.summary, i.source_id, "
            "  (SELECT t.topic FROM tag t WHERE t.item_id=i.id LIMIT 1) AS topic, "
            "  s.value AS rel, "
            "  COALESCE((SELECT a.value FROM signal a WHERE a.item_id=i.id AND a.kind=?), 0) AS aff, "
            "  (SELECT e.vec FROM embedding e WHERE e.item_id=i.id) AS vec, "
            "  (SELECT src.category FROM source src WHERE src.id=i.source_id) AS category "
            "FROM item i "
            "JOIN signal s ON s.item_id=i.id AND s.kind='relevance' "
            "WHERE NOT EXISTS (SELECT 1 FROM signal e WHERE e.item_id=i.id AND e.kind=?) "
            "GROUP BY i.id "
            "ORDER BY (s.value + aff) DESC, i.published DESC LIMIT ?",
            (f"affinity:{lens}", f"sent:{lens}", limit),
        ).fetchall()

    def sent_titles(self, lens: str) -> list[str]:
        return [r[0] for r in self.con.execute(
            "SELECT i.title FROM item i JOIN signal s ON s.item_id=i.id AND s.kind=?",
            (f"sent:{lens}",)).fetchall()]

    def mark_sent(self, lens: str, item_ids: list[int]) -> None:
        now = int(time.time())
        self.con.executemany(
            "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
            [(i, f"sent:{lens}", 1.0, now) for i in item_ids])
        self.con.commit()

    def last_sent_ts(self, lens: str) -> int | None:
        row = self.con.execute("SELECT MAX(ts) FROM signal WHERE kind=?",
                               (f"sent:{lens}",)).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    # ---- feedback (signal CRUD; the math lives in FeedbackService) ----
    def delete_signals(self, kinds: list[str]) -> None:
        qs = ",".join("?" * len(kinds))
        self.con.execute(f"DELETE FROM signal WHERE kind IN ({qs})", tuple(kinds))

    def insert_signals(self, rows: list[tuple[int, str, float, int]]) -> None:
        self.con.executemany("INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)", rows)

    def sent_unactioned(self, lens: str, cutoff: int, action_kinds: list[str]) -> list[int]:
        qs = ",".join("?" * len(action_kinds))
        rows = self.con.execute(
            "SELECT DISTINCT s.item_id FROM signal s "
            "WHERE s.kind=? AND s.ts < ? "
            f"AND NOT EXISTS (SELECT 1 FROM signal a WHERE a.item_id=s.item_id AND a.kind IN ({qs}))",
            (f"sent:{lens}", cutoff, *action_kinds),
        ).fetchall()
        return [r[0] for r in rows]

    def gesture_scores(self, kinds: tuple[str, str, str, str]) -> list[tuple]:
        """Per-item (item_id, vote, save, click, skip) sums for one lens's fb_* kinds."""
        return self.con.execute(
            "SELECT item_id, "
            "SUM(CASE WHEN kind=? THEN value END), "
            "SUM(CASE WHEN kind=? THEN value END), "
            "SUM(CASE WHEN kind=? THEN value END), "
            "SUM(CASE WHEN kind=? THEN value END) "
            "FROM signal WHERE kind IN (?,?,?,?) GROUP BY item_id",
            (*kinds, *kinds),
        ).fetchall()

    def rank_eligible_with_tags(self) -> list[tuple]:
        """(item_id, source_id, comma-topics) for every item with a relevance score."""
        return self.con.execute(
            "SELECT i.id, i.source_id, GROUP_CONCAT(t.topic) FROM item i "
            "JOIN signal r ON r.item_id=i.id AND r.kind='relevance' "
            "LEFT JOIN tag t ON t.item_id=i.id GROUP BY i.id, i.source_id"
        ).fetchall()

    def items_meta(self, ids: list[int]) -> list[tuple]:
        """(item_id, source_id) for the given ids."""
        if not ids:
            return []
        qs = ",".join("?" * len(ids))
        return self.con.execute(f"SELECT id, source_id FROM item WHERE id IN ({qs})",
                                tuple(ids)).fetchall()

    def item_topics(self, ids: list[int]) -> list[tuple]:
        """(item_id, topic) rows for the given ids."""
        if not ids:
            return []
        qs = ",".join("?" * len(ids))
        return self.con.execute(f"SELECT item_id, topic FROM tag WHERE item_id IN ({qs})",
                                tuple(ids)).fetchall()

    # ---- drafts ----
    def drafted_ids(self) -> set[int]:
        return {r[0] for r in self.con.execute("SELECT item_id FROM draft").fetchall()}

    def add_draft(self, item_id: int, body_json: str, now: int) -> None:
        self.con.execute(
            "INSERT OR IGNORE INTO draft(item_id,status,body,created_at) VALUES(?,?,?,?)",
            (item_id, "pending", body_json, now))

    def pending_drafts(self) -> list[tuple]:
        return self.con.execute(
            "SELECT d.id, i.title, i.url, d.body FROM draft d JOIN item i ON i.id=d.item_id "
            "WHERE d.status='pending' ORDER BY d.created_at DESC"
        ).fetchall()

    # ---- discovery ----
    def existing_source_urls(self) -> set[str]:
        return {r[0] for r in self.con.execute("SELECT url FROM source").fetchall()}

    def item_links(self) -> list[str]:
        return [r[0] for r in self.con.execute(
            "SELECT url FROM item WHERE url LIKE 'http%'").fetchall()]
