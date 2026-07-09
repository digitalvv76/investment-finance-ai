"""Tests for news cluster."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from engine.cluster import NewsCluster
from storage.models import NewsItem


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = MagicMock()
    # Return empty recent news by default
    db.get_recent_news.return_value = []
    return db


@pytest.fixture
def cluster(mock_db):
    return NewsCluster(db=mock_db)


class TestNewsCluster:
    """News clustering tests."""

    def test_singleton_no_event_created(self, cluster, mock_db):
        """A single unique article should not create an event line."""
        mock_db.get_recent_news.return_value = []
        item = NewsItem(
            id=1, title="Unique breaking news", url="https://x.com/1", source="Test"
        )
        result = cluster.find_or_create_event(item)
        assert result is None

    def test_similar_titles_match(self, cluster, mock_db):
        """Two articles with highly similar titles should be clustered."""
        mock_db.get_recent_news.return_value = [
            {
                'id': 1,
                'title': 'Federal Reserve raises interest rates by 25 basis points',
                'event_line_id': 100,
                'news_ids': '1',
            }
        ]
        item = NewsItem(
            id=2,
            title='Federal Reserve raises interest rates by 25 basis points',
            url='https://x.com/2',
            source='Reuters',
            status='pending',
        )
        result = cluster.find_or_create_event(item)
        assert result == 100  # Should match existing event — identical titles

    def test_similar_titles_partial_match(self, cluster, mock_db):
        """Partially similar titles about the same event."""
        mock_db.get_recent_news.return_value = [
            {
                'id': 1,
                'title': 'Fed raises interest rates amid inflation fears',
                'event_line_id': 200,
                'news_ids': '1',
            }
        ]
        item = NewsItem(
            id=2,
            title='Fed raises interest rates amid persistent inflation',
            url='https://x.com/3',
            source='Bloomberg',
            status='pending',
        )
        result = cluster.find_or_create_event(item)
        # Should match with high similarity
        assert result == 200

    def test_different_topics_no_match(self, cluster, mock_db):
        """Unrelated articles should not be clustered together."""
        mock_db.get_recent_news.return_value = [
            {
                'id': 1,
                'title': 'Apple announces new iPhone model',
                'event_line_id': 100,
                'news_ids': '1',
            }
        ]
        item = NewsItem(
            id=2,
            title='Federal Reserve cuts interest rates',
            url='https://x.com/2',
            source='Reuters',
            status='pending',
        )
        result = cluster.find_or_create_event(item)
        assert result is None  # Should not match

    def test_empty_title_returns_none(self, cluster):
        """Item with empty title should not be clustered."""
        item = NewsItem(id=1, title='', url='https://x.com/1', source='Test')
        result = cluster.find_or_create_event(item)
        assert result is None

    def test_normalize_event_title(self):
        """Event titles should have breaking markers stripped from start."""
        result = NewsCluster._normalize_event_title(
            "BREAKING: Fed announces rate decision"
        )
        assert result == "Fed announces rate decision"

        # "URGENT" at start should be stripped
        result2 = NewsCluster._normalize_event_title(
            "URGENT: Market sell-off intensifies"
        )
        assert result2 == "Market sell-off intensifies"

        # "flash crash" in the middle should NOT be stripped
        result3 = NewsCluster._normalize_event_title(
            "Dow suffers flash crash amid volatility"
        )
        assert "flash crash" in result3

    def test_get_active_events(self, cluster, mock_db):
        """Should return only active events with minimum sources."""
        mock_db._get_conn.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [
            {'id': 1, 'title': 'Event A', 'news_ids': '1,2,3', 'source_count': 3,
             'first_seen': '2026-07-01T10:00:00', 'last_updated': '2026-07-01T10:30:00', 'is_active': 1},
            {'id': 2, 'title': 'Event B', 'news_ids': '4,5', 'source_count': 2,
             'first_seen': '2026-07-01T11:00:00', 'last_updated': '2026-07-01T11:15:00', 'is_active': 1},
        ]

        events = cluster.get_active_events(min_sources=2)
        assert len(events) == 2
        assert events[0]['source_count'] >= 2

    def test_merge_into_events(self, cluster, mock_db):
        """Batch merge handles empty items list without error."""
        events = cluster.merge_into_events([])
        assert isinstance(events, list)
        assert len(events) == 0

    def test_second_similar_article_creates_event(self, cluster, mock_db):
        """A second corroborating article about a lone singleton forms an event."""
        existing = {"id": 1, "title": "US strikes Iran nuclear sites", "event_line_id": None}
        mock_db.get_recent_news.return_value = [existing]
        item = NewsItem(id=2, title="US strikes Iran nuclear facilities")
        event_id = cluster.find_or_create_event(item)
        assert event_id is not None  # second corroborating article → event line
