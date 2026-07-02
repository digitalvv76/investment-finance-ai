"""Tests for fast lane rule engine."""
import pytest
from unittest.mock import MagicMock
from engine.fast_lane import FastLane
from storage.models import NewsItem


@pytest.fixture
def fast_lane():
    mock_config = MagicMock()
    mock_config.load_keywords.return_value = {
        'breaking_markers': ['BREAKING', 'URGENT', 'ALERT'],
        'macro_alerts': ['CPI', 'FOMC', 'Federal Reserve', 'inflation', 'rate hike', 'recession'],
        'key_people': ['Kevin Warsh', 'Jerome Powell', 'Elon Musk'],
    }
    mock_db = MagicMock()
    mock_db.get_recent_news.return_value = []

    return FastLane(mock_config, mock_db, watchlist_tickers=['NVDA', 'AAPL', 'MSFT', 'TSLA'])


def test_extract_tickers(fast_lane):
    """Ticker extraction now delegated to EntityExtractor — test via process()."""
    result = fast_lane._extractor.extract(
        "NVDA stock surges as AAPL announces new partnership"
    )
    assert 'NVDA' in result['tickers']
    assert 'AAPL' in result['tickers']


def test_detect_breaking(fast_lane):
    assert fast_lane._is_breaking("BREAKING: Fed announces emergency rate cut")
    assert fast_lane._is_breaking("URGENT: Market flash crash")
    assert not fast_lane._is_breaking("Market update for the day")


def test_extract_macro_tags(fast_lane):
    """Macro tag extraction now delegated to EntityExtractor."""
    result = fast_lane._extractor.extract(
        "CPI data beats expectations, Federal Reserve may consider rate hike"
    )
    assert 'CPI' in result['indicators']
    assert any('Federal Reserve' in i for i in result['indicators'])
    assert any('rate hike' in i for i in result['indicators'])


def test_detect_key_people(fast_lane):
    """Key people detection now delegated to EntityExtractor."""
    result1 = fast_lane._extractor.extract("Kevin Warsh signals policy shift")
    assert 'Kevin Warsh' in result1['people']

    result2 = fast_lane._extractor.extract("Elon Musk buys more Tesla shares")
    assert 'Elon Musk' in result2['people']

    result3 = fast_lane._extractor.extract("Market closes higher")
    assert 'Kevin Warsh' not in result3['people']


def test_breaking_news_high_priority(fast_lane):
    item = NewsItem(
        title="BREAKING: NVDA reports blowout earnings, beats by 40%",
        url="https://example.com/nvda",
        source="Bloomberg",
    )
    results = fast_lane.process([item])
    assert len(results) == 1
    assert results[0].is_breaking
    assert 'NVDA' in results[0].tickers_found
    assert results[0].priority_score >= 0.3


def test_macro_news_triggers(fast_lane):
    item = NewsItem(
        title="FOMC minutes reveal concerns about persistent inflation",
        url="https://example.com/fomc",
        source="Reuters",
    )
    results = fast_lane.process([item])
    assert len(results) >= 1
    assert 'FOMC' in results[0].macro_tags or 'inflation' in results[0].macro_tags


def test_irrelevant_news_filtered_out(fast_lane):
    item = NewsItem(
        title="Local bakery wins award for best croissant",
        url="https://example.com/bakery",
        source="Local News",
    )
    results = fast_lane.process([item])
    assert len(results) == 0


def test_multi_ticker_higher_score(fast_lane):
    single = NewsItem(title="NVDA up 5%", url="https://x.com/1", source="Test")
    multi = NewsItem(title="NVDA AAPL MSFT all rally on tech optimism", url="https://x.com/2", source="Test")

    fast_lane.process([single])
    fast_lane.process([multi])

    assert multi.priority_score > single.priority_score
