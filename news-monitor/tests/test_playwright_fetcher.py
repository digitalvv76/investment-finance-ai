"""Smoke tests for Playwright fetcher."""
import pytest
from collector.playwright_fetcher import PlaywrightFetcher
from storage.models import NewsItem


@pytest.fixture
def sample_bloomberg_source():
    return [{
        "name": "Bloomberg Markets",
        "url": "https://www.bloomberg.com/markets",
        "selectors": {
            "headline": ".story-list-story__info__headline, [data-component='headline']",
            "link": "a[href^='/news/articles/']",
        }
    }]


@pytest.mark.asyncio
async def test_playwright_startup_shutdown(sample_bloomberg_source):
    """Verify browser can start and stop without error."""
    fetcher = PlaywrightFetcher(sample_bloomberg_source)
    await fetcher.startup()
    assert fetcher._browser is not None
    await fetcher.shutdown()


def test_news_item_from_playwright():
    """Verify NewsItem creation with breaking flag."""
    item = NewsItem(
        title="BREAKING: Market drops 500 points",
        url="https://bloomberg.com/news/test",
        source="Bloomberg",
        is_breaking=True,
    )
    assert item.is_breaking
    assert item.source == "Bloomberg"


def test_playwright_fetcher_init(sample_bloomberg_source):
    """Verify PlaywrightFetcher initialization stores sources."""
    fetcher = PlaywrightFetcher(sample_bloomberg_source)
    assert fetcher.sources == sample_bloomberg_source
    assert fetcher._browser is None
    assert fetcher._playwright is None


def test_news_item_breaking_default():
    """Verify is_breaking defaults to False."""
    item = NewsItem(
        title="Normal headline",
        url="https://example.com/news",
        source="Test",
    )
    assert item.is_breaking is False
