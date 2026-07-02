"""Tests for RSS fetcher."""
import pytest
from collector.rss_fetcher import RSSFetcher, NewsItem


@pytest.fixture
def sample_sources():
    return [
        {"name": "Test Feed 1", "url": "https://example.com/rss1", "category": "markets"},
        {"name": "Test Feed 2", "url": "https://example.com/rss2", "category": "macro"},
    ]


def test_news_item_creation():
    item = NewsItem(
        title="BREAKING: Fed raises rates",
        url="https://example.com/fed",
        source="Test Source",
        content_snippet="The Federal Reserve announced..."
    )
    assert item.title == "BREAKING: Fed raises rates"
    assert item.source == "Test Source"
    assert item.status == "pending"


@pytest.mark.asyncio
async def test_fetch_single_timeout_handled(sample_sources, mocker):
    """RSS fetcher handles timeout gracefully, returns empty list."""
    import aiohttp
    fetcher = RSSFetcher(sample_sources)

    # Mock session to raise timeout
    mock_session = mocker.AsyncMock()
    mock_session.get.side_effect = aiohttp.ClientTimeout(total=5)
    fetcher._session = mock_session

    items = await fetcher.fetch_single(sample_sources[0])
    assert items == []
