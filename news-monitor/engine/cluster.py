"""News clustering — group related articles into event lines."""
import logging
import re
from datetime import datetime, timedelta
from typing import List, Optional

from collector.dedup import DedupManager
from storage.database import Database
from storage.models import NewsItem, EventLine

logger = logging.getLogger(__name__)

# Default time window for clustering (seconds)
DEFAULT_CLUSTER_WINDOW = 1800  # 30 minutes
SIMILARITY_THRESHOLD = 0.45    # Title similarity threshold for same event


class NewsCluster:
    """Group related news items into event lines.

    When multiple sources report on the same event, they are clustered
    together into an EventLine for multi-source tracking.

    Uses VectorStore semantic similarity for matching when available;
    falls back to Jaccard title similarity otherwise.
    """

    def __init__(self, db: Database, window_seconds: int = DEFAULT_CLUSTER_WINDOW, vector_store=None):
        self.db = db
        self.window = timedelta(seconds=window_seconds)
        self._dedup = DedupManager()
        self._vector_store = vector_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_or_create_event(self, item: NewsItem) -> Optional[int]:
        """Find an existing event line for this item, or create a new one.

        Args:
            item: The news item to cluster.

        Returns:
            event_line_id if clustered, None if it's a singleton.
        """
        if not item.title:
            return None

        # Get recent news within the clustering window
        recent = self.db.get_recent_news(
            hours=self.window.total_seconds() / 3600
        )

        # Find the best matching event line
        best_match = self._find_best_match(item, recent)

        if best_match:
            self._add_to_event(item, best_match)
            return best_match

        # No existing event line — check for a similar *singleton* to seed a new event.
        seed = self._find_similar_singleton(item, recent)
        if seed:
            # Seed the event from the pre-existing singleton, then add the new item,
            # so BOTH articles are attached (news_ids has both, source_count = 2).
            seed_item = NewsItem(
                id=seed["id"],
                title=seed.get("title", ""),
                status=seed.get("status", "pending"),
            )
            event_id = self._create_event(seed_item)   # news_ids=seed, count=1
            self._add_to_event(item, event_id)          # adds new item, count=2
            return event_id
        return None

    def merge_into_events(self, items: List[NewsItem]) -> List[EventLine]:
        """Process a batch of items, clustering them into event lines.

        Returns list of updated event lines.
        """
        updated_events: dict[int, EventLine] = {}

        for item in items:
            event_id = self.find_or_create_event(item)
            if event_id:
                if event_id not in updated_events:
                    # Load the event
                    updated_events[event_id] = self._load_event(event_id)

        return list(updated_events.values())

    def get_active_events(self, min_sources: int = 2) -> List[dict]:
        """Get currently active event lines with multiple sources."""
        with self.db._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM event_lines
                   WHERE is_active = 1 AND source_count >= ?
                   ORDER BY last_updated DESC""",
                (min_sources,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_best_match(self, item: NewsItem, recent: List[dict]) -> Optional[int]:
        """Find the best matching event line ID for a news item.

        Uses VectorStore semantic search when available; falls back to
        Jaccard title similarity when ChromaDB is not configured.

        Returns the event_line_id of the best match, if any.
        """
        # Primary: semantic similarity via VectorStore
        if self._vector_store and self._vector_store.is_ready:
            try:
                text = f"{item.title or ''} {item.content_snippet or ''}"
                similar_ids = self._vector_store.find_similar(
                    text, threshold=0.75, max_results=5
                )
                if similar_ids:
                    # Find which event line these similar items belong to
                    for recent_item in recent:
                        if recent_item.get('id') in similar_ids:
                            event_id = recent_item.get('event_line_id')
                            if event_id:
                                logger.debug(
                                    "Cluster: semantic match — %s → event #%d",
                                    (item.title or '')[:50], event_id,
                                )
                                return event_id
            except Exception as e:
                logger.debug("VectorStore cluster match failed: %s", e)

        # Fallback: Jaccard title similarity
        best_score = 0.0
        best_event_id = None

        for recent_item in recent:
            event_id = recent_item.get('event_line_id')
            if not event_id:
                continue

            recent_title = recent_item.get('title', '')
            score = DedupManager.title_similarity(item.title, recent_title)

            if score > best_score and score >= SIMILARITY_THRESHOLD:
                best_score = score
                best_event_id = event_id

        return best_event_id

    def _find_similar_singleton(self, item: NewsItem, recent: List[dict]) -> Optional[dict]:
        """Find a recent article with no event_line_id that is similar enough.

        Returns the matching singleton row (dict), or None.
        """
        best_score, best = 0.0, None
        for r in recent:
            if r.get("event_line_id"):
                continue
            if r.get("id") == item.id:
                continue
            score = DedupManager.title_similarity(item.title, r.get("title", ""))
            if score > best_score and score >= SIMILARITY_THRESHOLD:
                best_score, best = score, r
        return best

    def _add_to_event(self, item: NewsItem, event_id: int):
        """Add a news item to an existing event line."""
        # Update the item's event_line_id
        self.db.update_news_status(item.id, item.status, event_line_id=event_id)

        # Update the event line metadata
        with self.db._get_conn() as conn:
            event = conn.execute(
                "SELECT * FROM event_lines WHERE id = ?", (event_id,)
            ).fetchone()
            if event:
                existing_ids = event['news_ids'].split(',') if event['news_ids'] else []
                existing_ids = [x for x in existing_ids if x]  # filter empty
                if str(item.id) not in existing_ids:
                    existing_ids.append(str(item.id))
                conn.execute(
                    """UPDATE event_lines
                       SET news_ids = ?, source_count = source_count + 1,
                           last_updated = ?
                       WHERE id = ?""",
                    (','.join(existing_ids), datetime.now(), event_id),
                )
                logger.debug(
                    "Added item %d to event line %d", item.id, event_id
                )

    def _create_event(self, item: NewsItem) -> int:
        """Create a new event line from a news item."""
        title = self._normalize_event_title(item.title)
        with self.db._get_conn() as conn:
            c = conn.execute(
                """INSERT INTO event_lines
                   (title, news_ids, source_count, first_seen, last_updated, is_active)
                   VALUES (?, ?, 1, ?, ?, 1)""",
                (title, str(item.id or ''), datetime.now(), datetime.now()),
            )
            event_id = c.lastrowid
            logger.info("Created event line %d: %s", event_id, title)
            return event_id

    @staticmethod
    def _normalize_event_title(title: str) -> str:
        """Create a normalized event title by removing breaking markers."""
        # Match breaking markers only when they appear at the start of the title
        # or are followed by a colon/dash (avoid partial word matches like "flash crash")
        cleaned = re.sub(
            r'^(BREAKING|URGENT|ALERT|JUST IN|FLASH|DEVELOPING|EXCLUSIVE)\s*[:-]?\s*',
            '', title, flags=re.IGNORECASE
        )
        return cleaned.strip()

    def _load_event(self, event_id: int) -> Optional[EventLine]:
        """Load an EventLine from the database."""
        with self.db._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM event_lines WHERE id = ?", (event_id,)
            ).fetchone()
            if row:
                d = dict(row)
                return EventLine(
                    id=d['id'],
                    title=d['title'],
                    news_ids=d['news_ids'],
                    source_count=d['source_count'],
                    first_seen=datetime.fromisoformat(d['first_seen']) if isinstance(d['first_seen'], str) else d['first_seen'],
                    last_updated=datetime.fromisoformat(d['last_updated']) if isinstance(d['last_updated'], str) else d['last_updated'],
                    is_active=bool(d['is_active']),
                )
        return None
