"""Standalone test runner — validates database module without pytest dependency.
Mirrors the 7 test cases from test_database.py using built-in unittest.
Run with: python tests/run_tests.py
"""
import os
import sys
import tempfile
import unittest

# Ensure the news-monitor package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.database import Database
from storage.models import NewsItem, FeedbackRecord


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.db = Database(self.db_path)
        self.db.init_db()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_01_init_db_creates_tables(self):
        """Test 1: init_db is idempotent and creates tables without error."""
        self.db.init_db()  # idempotent — should not raise

    def test_02_insert_and_retrieve_news(self):
        """Test 2: Insert a NewsItem and retrieve it by ID."""
        item = NewsItem(
            title="Test breaking news",
            url="https://example.com/test1",
            source="Bloomberg",
            content_snippet="Test content",
            tickers_found="NVDA",
            is_breaking=True,
            priority_score=0.85,
            status="fast_pushed",
        )
        news_id = self.db.insert_news(item)
        self.assertGreater(news_id, 0)

        result = self.db.get_news_by_id(news_id)
        self.assertEqual(result["title"], "Test breaking news")
        self.assertEqual(result["source"], "Bloomberg")
        self.assertEqual(result["tickers_found"], "NVDA")
        self.assertEqual(result["priority_score"], 0.85)

    def test_03_insert_duplicate_url_ignored(self):
        """Test 3: Duplicate URL is ignored due to unique constraint."""
        item1 = NewsItem(title="First", url="https://example.com/dup", source="CNBC")
        item2 = NewsItem(title="Second", url="https://example.com/dup", source="Reuters")

        id1 = self.db.insert_news(item1)
        id2 = self.db.insert_news(item2)

        self.assertGreater(id1, 0)
        self.assertEqual(id2, 0)  # IGNORE due to unique constraint

    def test_04_update_news_status(self):
        """Test 4: Update news status and additional fields."""
        item = NewsItem(title="Test", url="https://example.com/upd", source="Test")
        news_id = self.db.insert_news(item)
        self.assertGreater(news_id, 0)

        self.db.update_news_status(news_id, "deep_pushed", sentiment="bullish", sentiment_score=0.75)

        result = self.db.get_news_by_id(news_id)
        self.assertEqual(result["status"], "deep_pushed")
        self.assertEqual(result["sentiment"], "bullish")
        self.assertEqual(float(result["sentiment_score"]), 0.75)

    def test_05_feedback_crud(self):
        """Test 5: Insert and retrieve feedback records."""
        item = NewsItem(title="Test", url="https://example.com/fb", source="Test")
        news_id = self.db.insert_news(item)

        fb = FeedbackRecord(news_id=news_id, reaction="thumbs_up")
        fb_id = self.db.insert_feedback(fb)
        self.assertGreater(fb_id, 0)

        feedbacks = self.db.get_feedback_for_news(news_id)
        self.assertEqual(len(feedbacks), 1)
        self.assertEqual(feedbacks[0]["reaction"], "thumbs_up")

    def test_06_preferences_crud(self):
        """Test 6: Set and get user preferences."""
        self.db.set_preference("source_weight:bloomberg", "0.85")
        val = self.db.get_preference("source_weight:bloomberg")
        self.assertEqual(val, "0.85")

        # Overwrite
        self.db.set_preference("source_weight:bloomberg", "0.90")
        val = self.db.get_preference("source_weight:bloomberg")
        self.assertEqual(val, "0.90")

    def test_07_get_recent_news(self):
        """Test 7: Retrieve recent news within time window."""
        items = [
            NewsItem(title=f"News {i}", url=f"https://example.com/{i}", source="Test")
            for i in range(5)
        ]
        for item in items:
            news_id = self.db.insert_news(item)
            self.assertGreater(news_id, 0)

        recent = self.db.get_recent_news(hours=24)
        self.assertEqual(len(recent), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
