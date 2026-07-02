"""Tests for AI curator engine."""
import json
import pytest
from unittest.mock import MagicMock, patch
from engine.curator import Curator, DEFAULT_PROFILE


@pytest.fixture
def mock_db():
    db = MagicMock()
    prefs = {}
    def get_pref(key):
        return prefs.get(key)
    def set_pref(key, value):
        prefs[key] = value
    db.get_preference.side_effect = get_pref
    db.set_preference.side_effect = set_pref
    return db


@pytest.fixture
def curator(mock_db):
    return Curator(db=mock_db)


class TestCurator:
    """AI curator tests."""

    def test_default_profile(self, curator):
        """New curator should return default profile."""
        p = curator.get_profile()
        assert 'description' in p
        assert 'examples' in p
        assert len(p['examples']) >= 2

    def test_set_description(self, curator):
        """Setting description should persist."""
        curator.set_description("我关注AI和半导体行业")
        p = curator.get_profile()
        assert "AI" in p['description']

    def test_add_example(self, curator):
        """Adding examples should accumulate."""
        curator.add_example("NVDA发布新GPU")
        curator.add_example("美联储加息")
        p = curator.get_profile()
        assert len(p['examples']) >= 2  # includes defaults + new

    def test_add_anti_example(self, curator):
        """Anti-examples should be stored."""
        curator.add_anti_example("比特币价格波动")
        p = curator.get_profile()
        assert any("比特币" in e for e in p.get('anti_examples', []))

    def test_add_focus_ticker(self, curator):
        """Focus tickers should be added."""
        curator.add_focus_ticker("nvda")
        curator.add_focus_ticker("AMD")
        p = curator.get_profile()
        assert "NVDA" in p['focus_tickers']
        assert "AMD" in p['focus_tickers']

    def test_reset_profile(self, curator):
        """Reset should restore defaults."""
        curator.set_description("custom")
        curator.add_example("custom example")
        curator.reset_profile()
        p = curator.get_profile()
        assert p['description'] == DEFAULT_PROFILE['description']

    def test_keyword_score_ticker_match(self, curator):
        """Keyword scoring should boost score for focus ticker hits."""
        from storage.models import NewsItem
        curator.add_focus_ticker("NVDA")
        item = NewsItem(
            title="NVDA reports record earnings",
            tickers_found="NVDA",
            source="Test",
            url="x",
        )
        results = curator._keyword_score([item], curator.get_profile())
        assert results[0].relevance_score >= 7  # 5 base + 3 ticker

    def test_keyword_score_sector_match(self, curator):
        """Keyword scoring should boost for focus sector mentions."""
        from storage.models import NewsItem
        profile = curator.get_profile()
        profile['focus_sectors'] = ['半导体', 'AI']
        item = NewsItem(
            title="半导体行业迎来新一轮增长周期",
            source="Test",
            url="x",
        )
        results = curator._keyword_score([item], profile)
        assert results[0].relevance_score >= 7  # 5 base + 2 sector

    def test_keyword_score_ignore_sector(self, curator):
        """Keyword scoring should penalize ignored sectors."""
        from storage.models import NewsItem
        profile = curator.get_profile()
        profile['ignore_sectors'] = ['加密货币']
        item = NewsItem(
            title="比特币价格大幅波动，加密货币市场震荡",
            source="Test",
            url="x",
        )
        results = curator._keyword_score([item], profile)
        assert results[0].relevance_score <= 3  # 5 base - 3 penalty

    def test_keyword_score_anti_example_penalty(self, curator):
        """Anti-example keywords should penalize score when many words overlap."""
        from storage.models import NewsItem
        # Anti-example has many overlapping words with the test headline
        curator.add_anti_example("比特币 跌破 关键 支撑位 市场 恐慌 加剧 抛售 暴跌")
        item = NewsItem(
            title="比特币跌破关键支撑位 市场恐慌 抛售加剧 暴跌",
            source="Test",
            url="x",
        )
        results = curator._keyword_score([item], curator.get_profile())
        # Should be penalized due to heavy keyword overlap
        assert results[0].relevance_score <= 5
