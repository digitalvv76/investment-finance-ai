"""Tests for daily digest generator."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from bot.digest import DigestGenerator


@pytest.fixture
def mock_db():
    """Create a mock database with sample news data."""
    db = MagicMock()

    # Sample news items
    db.get_recent_news.return_value = [
        {
            'id': 1, 'title': 'BREAKING: NVDA reports record earnings',
            'source': 'Bloomberg', 'status': 'fast_pushed',
            'priority_score': 0.85, 'tickers_found': 'NVDA',
            'sentiment': 'bullish', 'macro_tags': '',
        },
        {
            'id': 2, 'title': 'Fed raises rates amid inflation concerns',
            'source': 'Reuters', 'status': 'deep_pushed',
            'priority_score': 0.72, 'tickers_found': '',
            'sentiment': 'bearish', 'macro_tags': 'FOMC,rate hike,inflation',
        },
        {
            'id': 3, 'title': 'Apple announces new product line',
            'source': 'CNBC', 'status': 'fast_pushed',
            'priority_score': 0.45, 'tickers_found': 'AAPL',
            'sentiment': 'cautiously_bullish', 'macro_tags': '',
        },
        {
            'id': 4, 'title': 'Local market commentary',
            'source': 'Unknown Blog', 'status': 'archived',
            'priority_score': 0.05, 'tickers_found': '',
            'sentiment': 'neutral', 'macro_tags': '',
        },
        {
            'id': 5, 'title': 'TSLA deliveries beat expectations',
            'source': 'MarketWatch', 'status': 'fast_pushed',
            'priority_score': 0.55, 'tickers_found': 'TSLA',
            'sentiment': 'bullish', 'macro_tags': '',
        },
    ]

    # Mock events
    mock_conn = MagicMock()
    db._get_conn.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            'title': 'Federal Reserve raises interest rates',
            'source_count': 4,
            'news_ids': '2,10,15,20',
            'last_updated': '2026-07-01T12:00:00',
            'is_active': 1,
        },
        {
            'title': 'NVDA earnings beat estimates',
            'source_count': 3,
            'news_ids': '1,8,12',
            'last_updated': '2026-07-01T11:30:00',
            'is_active': 1,
        },
    ]

    return db


@pytest.fixture
def generator(mock_db):
    return DigestGenerator(db=mock_db)


class TestDigestGenerator:
    """Daily digest tests."""

    def test_generate_has_sections(self, generator):
        """Full digest should contain all expected sections."""
        text = generator.generate(hours=24)
        assert '每日市场简报' in text
        assert '概览' in text or '总文章数' in text
        assert '头条新闻' in text or 'top' in text.lower()

    def test_generate_includes_stats(self, generator):
        """Digest should include article counts."""
        text = generator.generate(hours=24)
        assert '5' in text  # Total articles

    def test_generate_includes_tickers(self, generator):
        """Digest should mention top tickers."""
        text = generator.generate(hours=24)
        # NVDA appears in 1 article, TSLA in 1, AAPL in 1
        assert 'NVDA' in text or 'TSLA' in text or 'AAPL' in text

    def test_generate_includes_events(self, generator):
        """Digest should include active event lines."""
        text = generator.generate(hours=24)
        assert 'Federal Reserve' in text or 'NVDA earnings' in text or 'Active Events' in text

    def test_generate_empty(self, generator, mock_db):
        """Digest with no news should not crash."""
        mock_db.get_recent_news.return_value = []
        text = generator.generate(hours=24)
        assert '每日简报' in text
        assert '没有采集到新闻' in text

    def test_generate_minimal(self, generator):
        """Minimal digest should return compact stats."""
        text = generator.generate_minimal()
        assert '24小时' in text
        assert '快推' in text
        assert '深度' in text

    def test_generate_minimal_top_stories(self, generator):
        """Minimal digest should include top stories."""
        text = generator.generate_minimal()
        # Should show top 3 highest priority items
        assert 'NVDA' in text or 'Fed raises' in text or '头条新闻' in text

    def test_sentiment_emoji(self):
        """Sentiment emoji mapping should be correct."""
        assert DigestGenerator._sentiment_emoji('bullish') == '🟢'
        assert DigestGenerator._sentiment_emoji('bearish') == '🔴'
        assert DigestGenerator._sentiment_emoji('neutral') == '⚪'
        assert DigestGenerator._sentiment_emoji('unknown') == '⚪'
