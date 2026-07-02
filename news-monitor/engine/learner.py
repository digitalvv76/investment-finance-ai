"""Continuous learning engine — adapts from user feedback.

Four dimensions of adaptation:
1. Source weights — boost/demote sources based on 👍/👎 ratio
2. Topic weights — track which macro topics/sectors user cares about
3. Threshold adjustment — lower/raise push threshold by engagement
4. Personal dictionary — user-defined keywords for custom alerts
"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from storage.database import Database

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_SOURCE_WEIGHT = 0.05
MIN_SOURCE_WEIGHT = 0.01
MAX_SOURCE_WEIGHT = 0.15
BOOST_FACTOR = 1.5
DEMOTE_FACTOR = 0.7
THRESHOLD_STEP = 0.02
MIN_THRESHOLD = 0.15
MAX_THRESHOLD = 0.50


class Learner:
    """Feedback-driven learning engine.

    Processes user feedback (👍/👎) to adapt source trust, topic relevance,
    personal push threshold, and custom keyword dictionaries.
    """

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Dimension 1: Source weights
    # ------------------------------------------------------------------

    def update_source_weights(self, feedback_window_days: int = 7) -> Dict[str, float]:
        """Recalculate source authority weights from recent feedback.

        Sources with high 👍 ratio get boosted; high 👎 ratio get demoted.

        Returns:
            Dict mapping source_name -> new weight.
        """
        cutoff = datetime.now() - timedelta(days=feedback_window_days)

        # Collect recent feedback by source
        source_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"thumbs_up": 0, "thumbs_down": 0, "total": 0}
        )

        with self.db._get_conn() as conn:
            rows = conn.execute(
                """SELECT n.source, f.reaction
                   FROM feedback f
                   JOIN news n ON f.news_id = n.id
                   WHERE f.timestamp > ?
                   AND f.reaction IN ('thumbs_up', 'thumbs_down')""",
                (cutoff.isoformat(),),
            ).fetchall()

        for row in rows:
            source = row["source"] or "unknown"
            reaction = row["reaction"]
            source_stats[source][reaction] += 1
            source_stats[source]["total"] += 1

        # Calculate new weights
        new_weights = {}
        for source, stats in source_stats.items():
            if stats["total"] < 3:
                continue  # Not enough data to adjust

            up_ratio = stats["thumbs_up"] / stats["total"]
            current = self._get_source_weight(source)

            if up_ratio >= 0.8:
                new_weight = min(current * BOOST_FACTOR, MAX_SOURCE_WEIGHT)
            elif up_ratio <= 0.3:
                new_weight = max(current * DEMOTE_FACTOR, MIN_SOURCE_WEIGHT)
            else:
                # Move toward neutral based on ratio
                new_weight = current + (up_ratio - 0.5) * 0.05
                new_weight = max(MIN_SOURCE_WEIGHT, min(MAX_SOURCE_WEIGHT, new_weight))

            new_weights[source] = round(new_weight, 4)
            logger.info(
                "Learner(source): %s %.4f→%.4f (%d samples, %.0f%% up)",
                source, current, new_weight, stats["total"], up_ratio * 100,
            )

        # Persist updated weights
        self._save_source_weights(new_weights)
        return new_weights

    def get_source_weights(self) -> Dict[str, float]:
        """Get current learned source weights."""
        raw = self.db.get_preference("learner_source_weights")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return {}

    # ------------------------------------------------------------------
    # Dimension 2: Topic weights
    # ------------------------------------------------------------------

    def update_topic_weights(self, feedback_window_days: int = 14) -> Dict[str, float]:
        """Track which macro topics and sectors the user engages with.

        Returns:
            Dict mapping topic_name -> relevance score (0.0 - 1.0).
        """
        cutoff = datetime.now() - timedelta(days=feedback_window_days)

        topic_engagement: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"seen": 0, "engaged": 0}
        )

        with self.db._get_conn() as conn:
            # Get all news with macro tags that received feedback
            rows = conn.execute(
                """SELECT n.macro_tags, f.reaction
                   FROM feedback f
                   JOIN news n ON f.news_id = n.id
                   WHERE f.timestamp > ?
                   AND n.macro_tags != ''""",
                (cutoff.isoformat(),),
            ).fetchall()

        for row in rows:
            tags = row["macro_tags"].split(",") if row["macro_tags"] else []
            for tag in tags:
                tag = tag.strip()
                if not tag:
                    continue
                topic_engagement[tag]["seen"] += 1
                if row["reaction"] in ("thumbs_up", "analyze"):
                    topic_engagement[tag]["engaged"] += 1

        # Calculate relevance scores
        topic_scores = {}
        for topic, stats in topic_engagement.items():
            if stats["seen"] >= 2:
                topic_scores[topic] = round(stats["engaged"] / stats["seen"], 4)

        self._save_topic_scores(topic_scores)
        logger.info("Learner(topics): %d topics scored", len(topic_scores))
        return topic_scores

    def get_topic_scores(self) -> Dict[str, float]:
        """Get current learned topic relevance scores."""
        raw = self.db.get_preference("learner_topic_scores")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return {}

    # ------------------------------------------------------------------
    # Dimension 3: Threshold adjustment
    # ------------------------------------------------------------------

    def adjust_threshold(self) -> float:
        """Adjust push threshold based on engagement rate.

        High engagement → lower threshold (user wants more).
        Low engagement / ignores → raise threshold (user wants less).

        Returns:
            New threshold value.
        """
        current = self._get_threshold()

        # Count recent activity
        with self.db._get_conn() as conn:
            # Recent alerts pushed
            pushed = conn.execute(
                """SELECT COUNT(*) as cnt FROM news
                   WHERE status IN ('fast_pushed', 'deep_pushed')
                   AND captured_at > datetime('now', '-3 days')"""
            ).fetchone()
            total_pushed = pushed["cnt"] if pushed else 0

            # User engagement (any feedback)
            engaged = conn.execute(
                """SELECT COUNT(*) as cnt FROM feedback
                   WHERE timestamp > datetime('now', '-3 days')"""
            ).fetchone()
            total_engaged = engaged["cnt"] if engaged else 0

        if total_pushed == 0:
            return current

        engagement_rate = total_engaged / total_pushed

        if engagement_rate >= 0.5:
            # High engagement: lower threshold to get more alerts
            new_threshold = max(current - THRESHOLD_STEP, MIN_THRESHOLD)
        elif engagement_rate <= 0.1:
            # Low engagement: raise threshold to reduce noise
            new_threshold = min(current + THRESHOLD_STEP, MAX_THRESHOLD)
        else:
            new_threshold = current  # Stay

        self._save_threshold(new_threshold)
        logger.info(
            "Learner(threshold): %.2f→%.2f (%.0f%% engagement, %d pushed)",
            current, new_threshold, engagement_rate * 100, total_pushed,
        )
        return new_threshold

    # ------------------------------------------------------------------
    # Dimension 4: Personal dictionary
    # ------------------------------------------------------------------

    def update_personal_dict(self, keyword: str, action: str) -> List[str]:
        """Add or remove a keyword from the user's personal alert dictionary.

        Args:
            keyword: The keyword to add/remove.
            action: 'add' or 'remove'.

        Returns:
            Current list of personal keywords.
        """
        keywords = self.get_personal_dict()

        if action == "add" and keyword not in keywords:
            keywords.append(keyword)
            logger.info("Learner(dict): added '%s'", keyword)
        elif action == "remove" and keyword in keywords:
            keywords.remove(keyword)
            logger.info("Learner(dict): removed '%s'", keyword)

        self.db.set_preference("learner_personal_dict", json.dumps(keywords))
        return keywords

    def get_personal_dict(self) -> List[str]:
        """Get the user's personal keyword dictionary."""
        raw = self.db.get_preference("learner_personal_dict")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return []

    # ------------------------------------------------------------------
    # Batch update — run all adaptations
    # ------------------------------------------------------------------

    def run_adaptation_cycle(self) -> dict:
        """Run all four learning dimensions and return the changes."""
        return {
            "source_weights": self.update_source_weights(),
            "topic_scores": self.update_topic_weights(),
            "threshold": self.adjust_threshold(),
            "personal_dict": self.get_personal_dict(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_source_weight(self, source: str) -> float:
        weights = self.get_source_weights()
        return weights.get(source.lower(), DEFAULT_SOURCE_WEIGHT)

    def _save_source_weights(self, weights: Dict[str, float]):
        self.db.set_preference("learner_source_weights", json.dumps(weights))

    def _save_topic_scores(self, scores: Dict[str, float]):
        self.db.set_preference("learner_topic_scores", json.dumps(scores))

    def _get_threshold(self) -> float:
        raw = self.db.get_preference("learner_threshold")
        if raw:
            try:
                return float(raw)
            except (ValueError, TypeError):
                pass
        return 0.30  # Default fast lane threshold

    def _save_threshold(self, threshold: float):
        self.db.set_preference("learner_threshold", str(round(threshold, 4)))
