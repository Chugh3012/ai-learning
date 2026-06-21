from __future__ import annotations

import sqlite3
import time

from sqlalchemy import create_engine
from sqlmodel import SQLModel, Session

from ai_scout.lib.config import KB_DIR, KB_PATH
from ai_scout.repositories import models

class KnowledgeBase:

    def __init__(self, engine, con: sqlite3.Connection):
        self.engine = engine
        self.con = con

    @classmethod
    def open(cls, path=None) -> "KnowledgeBase":
        path = str(path or KB_PATH)
        if path != ":memory:":
            KB_DIR.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{path}")
        SQLModel.metadata.create_all(engine)
        con = sqlite3.connect(path)
        cls._reconcile_columns(engine, con)
        return cls(engine, con)

    @staticmethod
    def _reconcile_columns(engine, con: sqlite3.Connection) -> None:
        for table in SQLModel.metadata.sorted_tables:
            have = {row[1] for row in con.execute(f"PRAGMA table_info({table.name})").fetchall()}
            if not have:
                continue
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                try:
                    con.execute(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}')
                    print(f"kb: migrated {table.name}.{col.name} ({ddl})")
                except sqlite3.OperationalError as e:
                    print(f"kb: could not add {table.name}.{col.name} ({e})")
        con.commit()

    def session(self) -> Session:
        return Session(self.engine)

    def close(self) -> None:
        self.con.close()
        self.engine.dispose()

    def commit(self) -> None:
        self.con.commit()

    def upsert_source(self, s: dict) -> int:
        self.con.execute(
            "INSERT INTO source(title,url,kind,category) VALUES(?,?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET title=excluded.title, category=excluded.category",
            (s["title"], s["url"], "feed", s["category"]),
        )
        return self.con.execute("SELECT id FROM source WHERE url=?", (s["url"],)).fetchone()[0]

    def insert_item(self, source_id: int, title: str, url: str, summary: str,
                    published: int, now: int, h: str) -> int | None:
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
        rows = self.con.execute(
            "SELECT e.item_id, i.title, i.url, e.vec FROM embedding e "
            "JOIN item i ON i.id=e.item_id "
            "JOIN signal s ON s.item_id=e.item_id AND s.kind=? ",
            (f"sent:{lens}",),
        ).fetchall()
        return [(pid, t, u, v) for pid, t, u, v in rows if pid not in exclude and v]

    def candidates(self, lens: str, limit: int) -> list[tuple]:
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
        return self.con.execute(
            "SELECT i.id, i.source_id, GROUP_CONCAT(t.topic) FROM item i "
            "JOIN signal r ON r.item_id=i.id AND r.kind='relevance' "
            "LEFT JOIN tag t ON t.item_id=i.id GROUP BY i.id, i.source_id"
        ).fetchall()

    def items_meta(self, ids: list[int]) -> list[tuple]:
        if not ids:
            return []
        qs = ",".join("?" * len(ids))
        return self.con.execute(f"SELECT id, source_id FROM item WHERE id IN ({qs})",
                                tuple(ids)).fetchall()

    def item_topics(self, ids: list[int]) -> list[tuple]:
        if not ids:
            return []
        qs = ",".join("?" * len(ids))
        return self.con.execute(f"SELECT item_id, topic FROM tag WHERE item_id IN ({qs})",
                                tuple(ids)).fetchall()

    def existing_source_urls(self) -> set[str]:
        return {r[0] for r in self.con.execute("SELECT url FROM source").fetchall()}

    def item_links(self) -> list[str]:
        return [r[0] for r in self.con.execute(
            "SELECT url FROM item WHERE url LIKE 'http%'").fetchall()]

    def metrics_snapshot(self) -> dict:
        one = lambda q: self.con.execute(q).fetchone()[0]
        return {
            "items_total": one("SELECT COUNT(*) FROM item"),
            "sources_total": one("SELECT COUNT(*) FROM source"),
            "ranked_total": one("SELECT COUNT(DISTINCT item_id) FROM signal WHERE kind='relevance'"),
            "embedded_total": one("SELECT COUNT(*) FROM embedding"),
            "topics_total": one("SELECT COUNT(DISTINCT topic) FROM tag"),
        }

    def engagement(self, lens: str) -> dict:
        def c(kind: str) -> int:
            return self.con.execute(
                "SELECT COUNT(*) FROM signal WHERE kind=?", (kind,)).fetchone()[0]
        return {
            "sent": c(f"sent:{lens}"),
            "votes": c(f"fb_vote:{lens}"),
            "saves": c(f"fb_save:{lens}"),
            "clicks": c(f"fb_click:{lens}"),
            "skips": c(f"fb_skip:{lens}"),
        }

    def source_quality(self, quality_floor: float = 65.0) -> list[dict]:
        rows = self.con.execute(
            "WITH rel AS ("
            "  SELECT item_id, MAX(value) AS value FROM signal "
            "  WHERE kind='relevance' GROUP BY item_id"
            ") "
            "SELECT src.id, COALESCE(src.title, ''), COALESCE(src.url, ''), "
            "  COALESCE(src.category, ''), "
            "  COUNT(i.id) AS items_total, "
            "  COUNT(rel.item_id) AS ranked_total, "
            "  SUM(CASE WHEN rel.value >= ? THEN 1 ELSE 0 END) AS quality_ranked_total, "
            "  (SELECT COUNT(*) FROM signal s JOIN item ii ON ii.id=s.item_id "
            "   WHERE ii.source_id=src.id AND s.kind LIKE 'sent:%') AS delivered_total, "
            "  (SELECT COUNT(*) FROM signal s JOIN item ii ON ii.id=s.item_id "
            "   WHERE ii.source_id=src.id AND s.kind LIKE 'fb_save:%') AS saves_total, "
            "  (SELECT COUNT(*) FROM signal s JOIN item ii ON ii.id=s.item_id "
            "   WHERE ii.source_id=src.id AND s.kind LIKE 'fb_click:%') AS clicks_total, "
            "  (SELECT COUNT(*) FROM signal s JOIN item ii ON ii.id=s.item_id "
            "   WHERE ii.source_id=src.id AND s.kind LIKE 'fb_vote:%' AND s.value > 0) "
            "   AS positive_votes_total, "
            "  (SELECT COUNT(*) FROM signal s JOIN item ii ON ii.id=s.item_id "
            "   WHERE ii.source_id=src.id AND s.kind LIKE 'fb_skip:%') AS skips_total "
            "FROM source src "
            "LEFT JOIN item i ON i.source_id=src.id "
            "LEFT JOIN rel ON rel.item_id=i.id "
            "GROUP BY src.id "
            "ORDER BY src.title",
            (quality_floor,),
        ).fetchall()
        keys = (
            "source_id", "title", "url", "category", "items_total", "ranked_total",
            "quality_ranked_total", "delivered_total", "saves_total", "clicks_total",
            "positive_votes_total", "skips_total",
        )
        return [dict(zip(keys, row)) for row in rows]
