"""SQLite database manager for news monitor."""
import sqlite3
import json
from datetime import datetime, date
from typing import List, Optional
from contextlib import contextmanager
from .models import NewsItem, EventLine, FeedbackRecord, UserPreference


def _adapt_datetime(val):
    """Adapt datetime objects to ISO format strings for SQLite."""
    return val.isoformat()


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_adapter(date, _adapt_datetime)


class Database:
    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = db_path

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self):
        with self._get_conn() as conn:
            # Enable WAL mode for better concurrent read performance.
            # WAL allows simultaneous reads and writes without blocking.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

            conn.executescript("""
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    content_snippet TEXT DEFAULT '',
                    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tickers_found TEXT DEFAULT '',
                    macro_tags TEXT DEFAULT '',
                    is_breaking INTEGER DEFAULT 0,
                    priority_score REAL DEFAULT 0.0,
                    entities TEXT DEFAULT '',
                    sentiment TEXT DEFAULT NULL,
                    sentiment_score REAL DEFAULT 0.0,
                    market_impact TEXT DEFAULT '',
                    llm_analysis TEXT DEFAULT '',
                    event_line_id INTEGER DEFAULT NULL,
                    status TEXT DEFAULT 'pending'
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_news_url ON news(url);
                CREATE INDEX IF NOT EXISTS idx_news_captured ON news(captured_at);
                CREATE INDEX IF NOT EXISTS idx_news_status ON news(status);
                CREATE INDEX IF NOT EXISTS idx_news_tickers ON news(tickers_found);

                CREATE TABLE IF NOT EXISTS event_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL DEFAULT '',
                    news_ids TEXT DEFAULT '',
                    source_count INTEGER DEFAULT 0,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id INTEGER NOT NULL,
                    reaction TEXT NOT NULL DEFAULT '',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (news_id) REFERENCES news(id)
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_news ON feedback(news_id);

                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS training_docs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL DEFAULT 'text',
                    source TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_training_type ON training_docs(type);
            """)

    def insert_news(self, item: NewsItem) -> int:
        with self._get_conn() as conn:
            c = conn.execute("""
                INSERT OR IGNORE INTO news
                (title, url, source, content_snippet, published_at, captured_at,
                 tickers_found, macro_tags, is_breaking, priority_score,
                 entities, sentiment, sentiment_score, market_impact, llm_analysis,
                 event_line_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.title, item.url, item.source, item.content_snippet,
                item.published_at, item.captured_at,
                item.tickers_found, item.macro_tags, int(item.is_breaking), item.priority_score,
                item.entities, item.sentiment, item.sentiment_score, item.market_impact,
                item.llm_analysis, item.event_line_id, item.status
            ))
            if c.lastrowid:
                item.id = c.lastrowid
            return c.lastrowid if c.lastrowid else 0

    def get_news_by_status(self, status: str, limit: int = 100) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM news WHERE status = ? ORDER BY captured_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_news_by_id(self, news_id: int) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM news WHERE id = ?", (news_id,)).fetchone()
            return dict(row) if row else None

    def update_news_status(self, news_id: int, status: str, **kwargs):
        updates = ["status = ?"]
        params = [status]
        for k, v in kwargs.items():
            updates.append(f"{k} = ?")
            params.append(v)
        params.append(news_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE news SET {', '.join(updates)} WHERE id = ?", params)

    def insert_feedback(self, fb: FeedbackRecord) -> int:
        with self._get_conn() as conn:
            c = conn.execute(
                "INSERT INTO feedback (news_id, reaction, timestamp) VALUES (?, ?, ?)",
                (fb.news_id, fb.reaction, fb.timestamp)
            )
            return c.lastrowid

    def get_feedback_for_news(self, news_id: int) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE news_id = ? ORDER BY timestamp DESC",
                (news_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_preference(self, key: str) -> Optional[str]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_preference(self, key: str, value: str):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO preferences (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, datetime.now()))

    def get_recent_news(self, hours: int = 24, limit: int = 500) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM news WHERE captured_at > datetime('now', ?) ORDER BY captured_at DESC LIMIT ?",
                (f'-{hours} hours', limit)
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Training Docs CRUD
    # ------------------------------------------------------------------

    def add_training_doc(self, doc_type: str, source: str, title: str = "",
                         content: str = "", summary: str = "") -> int:
        """Add a training document. Returns its id."""
        with self._get_conn() as conn:
            c = conn.execute(
                """INSERT INTO training_docs (type, source, title, content, summary)
                   VALUES (?, ?, ?, ?, ?)""",
                (doc_type, source, title, content, summary),
            )
            return c.lastrowid

    def get_training_docs(self, doc_type: str = None, limit: int = 50) -> List[dict]:
        """Get training documents, optionally filtered by type."""
        with self._get_conn() as conn:
            if doc_type:
                rows = conn.execute(
                    "SELECT * FROM training_docs WHERE type = ? ORDER BY created_at DESC LIMIT ?",
                    (doc_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM training_docs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def delete_training_doc(self, doc_id: int):
        """Delete a training document."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM training_docs WHERE id = ?", (doc_id,))

    def get_training_context(self, max_chars: int = 3000) -> str:
        """Get concatenated training summaries for AI context."""
        docs = self.get_training_docs(limit=20)
        parts = []
        total = 0
        for doc in docs:
            text = doc.get("summary") or doc.get("content", "")[:200]
            if text:
                parts.append(f"- [{doc['type']}] {text}")
                total += len(text)
                if total >= max_chars:
                    break
        return "\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Retention / maintenance
    # ------------------------------------------------------------------

    def purge_old_news(self, days: int = 90) -> int:
        """Delete news and feedback older than `days`. Returns deleted count."""
        with self._get_conn() as conn:
            c = conn.execute(
                "DELETE FROM news WHERE captured_at < datetime('now', ?)",
                (f'-{days} days',),
            )
            deleted = c.rowcount
            # Delete orphaned feedback
            conn.execute(
                "DELETE FROM feedback WHERE news_id NOT IN (SELECT id FROM news)"
            )
            if deleted:
                logger.info("Retention: purged %d old news items (>%d days)", deleted, days)
            return deleted

    def vacuum(self):
        """Reclaim disk space from deleted rows."""
        with self._get_conn() as conn:
            conn.execute("PRAGMA optimize")
            conn.execute("VACUUM")
            logger.info("Database vacuumed")

    def get_db_stats(self) -> dict:
        """Return database size and record counts."""
        import os
        stats = {
            "news_count": 0,
            "feedback_count": 0,
            "event_count": 0,
            "training_docs": 0,
            "db_size_mb": 0,
        }
        try:
            stats["db_size_mb"] = round(os.path.getsize(self.db_path) / (1024 * 1024), 2)
        except OSError:
            pass

        with self._get_conn() as conn:
            for table in ["news", "feedback", "event_lines", "training_docs"]:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                if row:
                    key = f"{table if table != 'news' else 'news'}_count"
                    if table == "event_lines":
                        key = "event_count"
                    elif table == "training_docs":
                        key = "training_docs"
                    stats[key] = row["cnt"]
        return stats
