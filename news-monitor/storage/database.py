"""SQLite database manager for news monitor."""
import sqlite3
import json
from datetime import datetime, date
from typing import List, Optional
from contextlib import contextmanager
from .models import NewsItem, EventLine, FeedbackRecord, UserPreference, \
    ImpactAssessment, ImpactOutcome, CalibrationState, HealthEvent


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

                CREATE TABLE IF NOT EXISTS impact_assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id INTEGER NOT NULL,
                    impact_score REAL DEFAULT 0.0,
                    confidence REAL DEFAULT 0.0,
                    event_category TEXT DEFAULT '',
                    surprise_level TEXT DEFAULT '',
                    breadth TEXT DEFAULT '',
                    urgency TEXT DEFAULT 'INFO',
                    sentiment TEXT DEFAULT '',
                    greed_index INTEGER DEFAULT 50,
                    reasoning_chain TEXT DEFAULT '',
                    similar_events TEXT DEFAULT '',
                    expected_moves TEXT DEFAULT '',
                    calibration_note TEXT DEFAULT '',
                    flash_note TEXT DEFAULT '',
                    analyst_note TEXT DEFAULT '',
                    key_points TEXT DEFAULT '',
                    risk_flags TEXT DEFAULT '',
                    low_confidence INTEGER DEFAULT 0,
                    prompt_version TEXT DEFAULT 'v1',
                    latency_ms INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_impact_news ON impact_assessments(news_id);
                CREATE INDEX IF NOT EXISTS idx_impact_score ON impact_assessments(impact_score);

                CREATE TABLE IF NOT EXISTS impact_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assessment_id INTEGER NOT NULL,
                    collection_window TEXT DEFAULT '',
                    spx_change_pct REAL DEFAULT 0.0,
                    vix_change_pct REAL DEFAULT 0.0,
                    sector_changes TEXT DEFAULT '',
                    actual_score REAL DEFAULT 0.0,
                    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (assessment_id) REFERENCES impact_assessments(id)
                );
                CREATE INDEX IF NOT EXISTS idx_outcome_assessment ON impact_outcomes(assessment_id);

                CREATE TABLE IF NOT EXISTS calibration_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT UNIQUE NOT NULL,
                    bias REAL DEFAULT 0.0,
                    sample_count INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS health_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT DEFAULT '',
                    news_id INTEGER DEFAULT 0,
                    detail TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_health_type ON health_events(event_type);
            """)
            # Migrations: add new columns to existing databases (idempotent)
            _migrations = [
                "ALTER TABLE impact_assessments ADD COLUMN analyst_note TEXT DEFAULT ''",
                "ALTER TABLE impact_assessments ADD COLUMN urgency TEXT DEFAULT 'INFO'",
                "ALTER TABLE impact_assessments ADD COLUMN sentiment TEXT DEFAULT ''",
                "ALTER TABLE impact_assessments ADD COLUMN greed_index INTEGER DEFAULT 50",
                "ALTER TABLE impact_assessments ADD COLUMN flash_note TEXT DEFAULT ''",
                "ALTER TABLE impact_assessments ADD COLUMN key_points TEXT DEFAULT ''",
                "ALTER TABLE impact_assessments ADD COLUMN risk_flags TEXT DEFAULT ''",
            ]
            for stmt in _migrations:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass  # column already exists

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
    # Impact Evaluator CRUD
    # ------------------------------------------------------------------

    def insert_assessment(self, a: ImpactAssessment) -> int:
        with self._get_conn() as conn:
            c = conn.execute("""
                INSERT INTO impact_assessments
                (news_id, impact_score, confidence, event_category, surprise_level,
                 breadth, urgency, sentiment, greed_index,
                 reasoning_chain, similar_events, expected_moves,
                 calibration_note, flash_note, analyst_note,
                 key_points, risk_flags,
                 low_confidence, prompt_version, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                a.news_id, a.impact_score, a.confidence, a.event_category,
                a.surprise_level, a.breadth, a.urgency, a.sentiment, a.greed_index,
                a.reasoning_chain, a.similar_events, a.expected_moves,
                a.calibration_note, a.flash_note, a.analyst_note,
                a.key_points, a.risk_flags,
                int(a.low_confidence), a.prompt_version, a.latency_ms
            ))
            a.id = c.lastrowid
            return c.lastrowid

    def get_assessments(self, limit: int = 20, min_score: float = 0.0) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM impact_assessments WHERE impact_score >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (min_score, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_assessment(self, assessment_id: int) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM impact_assessments WHERE id = ?", (assessment_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_assessments_without_outcomes(self, window: str, limit: int = 50) -> list[dict]:
        """Assessments that still need an outcome for a given window."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT a.* FROM impact_assessments a
                WHERE a.id NOT IN (
                    SELECT assessment_id FROM impact_outcomes
                    WHERE collection_window = ?
                )
                ORDER BY a.created_at DESC LIMIT ?
            """, (window, limit)).fetchall()
            return [dict(r) for r in rows]

    def insert_outcome(self, o: ImpactOutcome) -> int:
        with self._get_conn() as conn:
            c = conn.execute("""
                INSERT INTO impact_outcomes
                (assessment_id, collection_window, spx_change_pct, vix_change_pct,
                 sector_changes, actual_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (o.assessment_id, o.collection_window, o.spx_change_pct,
                  o.vix_change_pct, o.sector_changes, o.actual_score))
            o.id = c.lastrowid
            return c.lastrowid

    def get_outcomes_for_category(self, category: str, limit: int = 20) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT a.impact_score as predicted_score,
                       a.event_category,
                       MAX(o.actual_score) as actual_score
                FROM impact_assessments a
                JOIN impact_outcomes o ON o.assessment_id = a.id
                WHERE a.event_category = ?
                GROUP BY a.id
                ORDER BY a.created_at DESC LIMIT ?
            """, (category, limit)).fetchall()
            return [dict(r) for r in rows]

    def get_outcomes_for_assessment(self, assessment_id: int) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM impact_outcomes WHERE assessment_id = ? "
                "ORDER BY collected_at DESC",
                (assessment_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_calibration(self, category: str, bias: float, sample_count: int):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO calibration_state
                (category, bias, sample_count, last_updated)
                VALUES (?, ?, ?, datetime('now'))
            """, (category, bias, sample_count))

    def get_calibration(self, category: str = None) -> list[dict]:
        with self._get_conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM calibration_state WHERE category = ?", (category,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM calibration_state ORDER BY category"
                ).fetchall()
            return [dict(r) for r in rows]

    def insert_health_event(self, e: HealthEvent) -> int:
        with self._get_conn() as conn:
            c = conn.execute(
                "INSERT INTO health_events (event_type, news_id, detail) VALUES (?, ?, ?)",
                (e.event_type, e.news_id, e.detail)
            )
            return c.lastrowid

    def get_health_events(self, limit: int = 50, event_type: str = None) -> list[dict]:
        with self._get_conn() as conn:
            if event_type:
                rows = conn.execute(
                    "SELECT * FROM health_events WHERE event_type = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (event_type, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM health_events ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def get_health_stats(self, hours: int = 1) -> dict:
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM impact_assessments "
                "WHERE created_at > datetime('now', ?)",
                (f'-{hours} hours',)
            ).fetchone()["cnt"]
            errors = conn.execute(
                "SELECT COUNT(*) as cnt FROM health_events "
                "WHERE created_at > datetime('now', ?)",
                (f'-{hours} hours',)
            ).fetchone()["cnt"]
            return {"total_assessments_1h": total, "health_events_1h": errors,
                    "success_rate": round((total - errors) / max(total, 1) * 100, 1)}

    def get_impact_stats(self) -> dict:
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM impact_assessments").fetchone()["cnt"]
            with_outcomes = conn.execute(
                "SELECT COUNT(DISTINCT assessment_id) as cnt FROM impact_outcomes"
            ).fetchone()["cnt"]
            pending = total - with_outcomes
            return {"total": total, "with_outcomes": with_outcomes, "pending": pending}

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
            "impact_assessments_count": 0,
            "impact_outcomes_count": 0,
            "calibration_state_count": 0,
            "health_events_count": 0,
            "db_size_mb": 0,
        }
        try:
            stats["db_size_mb"] = round(os.path.getsize(self.db_path) / (1024 * 1024), 2)
        except OSError:
            pass

        with self._get_conn() as conn:
            for table in ["news", "feedback", "event_lines", "training_docs",
                           "impact_assessments", "impact_outcomes", "calibration_state", "health_events"]:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                if row:
                    key = f"{table if table != 'news' else 'news'}_count"
                    if table == "event_lines":
                        key = "event_count"
                    elif table == "training_docs":
                        key = "training_docs"
                    stats[key] = row["cnt"]
        return stats
