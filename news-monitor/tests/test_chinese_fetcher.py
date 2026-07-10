"""Tests for Chinese financial news fetcher."""
import pytest
from datetime import datetime
from collector.chinese_fetcher import ChineseNewsFetcher, NewsItem, _clean_html, _ts_to_datetime


@pytest.fixture
def sample_config():
    return {
        "max_items_per_source": 5,
        "request_delay_seconds": 0.0,
        "sina_channels": [
            {"name": "7x24综合", "lid": 2509, "category": "macro"},
        ],
        "wallstreetcn_channels": [
            {"channel": "global", "name": "全球"},
        ],
    }


def test_clean_html():
    """HTML cleaner strips all tags."""
    assert _clean_html("<p>Hello</p>") == "Hello"
    assert _clean_html('<a href="x">link</a> text') == "link text"
    assert _clean_html("No HTML here") == "No HTML here"
    assert _clean_html("") == ""


def test_ts_to_datetime():
    """Unix timestamp conversion."""
    dt = _ts_to_datetime(1783052118)
    assert isinstance(dt, datetime)
    assert dt.year == 2026

    # Invalid timestamp falls back to now
    dt = _ts_to_datetime(0)
    assert isinstance(dt, datetime)


def test_news_item_creation():
    """Chinese fetcher creates valid NewsItem objects."""
    item = NewsItem(
        title="央行宣布降准0.5个百分点",
        url="https://example.com/news/1",
        source="新浪财经·7x24综合",
        content_snippet="中国人民银行决定于2026年7月15日下调存款准备金率...",
    )
    assert item.source == "新浪财经·7x24综合"
    assert "降准" in item.title
    assert item.status == "pending"


@pytest.mark.asyncio
async def test_fetch_sina_channel_http_error(mocker):
    """Handles HTTP error gracefully, returns empty list."""
    import aiohttp

    fetcher = ChineseNewsFetcher({
        "sina_channels": [{"name": "test", "lid": 9999, "category": "macro"}],
        "max_items_per_source": 5,
        "request_delay_seconds": 0,
    })

    mock_session = mocker.AsyncMock()
    mock_resp = mocker.AsyncMock()
    mock_resp.status = 500
    mock_session.get.return_value.__aenter__.return_value = mock_resp
    fetcher._session = mock_session

    items = await fetcher.fetch_sina_channel({"name": "test", "lid": 9999})
    assert items == []


@pytest.mark.asyncio
async def test_fetch_sina_channel_timeout(mocker):
    """Handles timeout gracefully, returns empty list."""
    import asyncio

    fetcher = ChineseNewsFetcher({
        "sina_channels": [{"name": "test", "lid": 9999, "category": "macro"}],
        "max_items_per_source": 5,
        "request_delay_seconds": 0,
    })

    mock_session = mocker.AsyncMock()
    mock_session.get.side_effect = asyncio.TimeoutError()
    fetcher._session = mock_session

    items = await fetcher.fetch_sina_channel({"name": "test", "lid": 9999})
    assert items == []


@pytest.mark.asyncio
async def test_fetch_wallstreetcn_channel_http_error(mocker):
    """Handles WSCN HTTP error gracefully."""
    fetcher = ChineseNewsFetcher({
        "wallstreetcn_channels": [{"channel": "global", "name": "test"}],
        "max_items_per_source": 5,
        "request_delay_seconds": 0,
    })

    mock_session = mocker.AsyncMock()
    mock_resp = mocker.AsyncMock()
    mock_resp.status = 404
    mock_session.get.return_value.__aenter__.return_value = mock_resp
    fetcher._session = mock_session

    items = await fetcher.fetch_wallstreetcn_channel({"channel": "global", "name": "test"})
    assert items == []


@pytest.mark.asyncio
async def test_fetch_wallstreetcn_api_error(mocker):
    """Handles WSCN API error code gracefully."""
    fetcher = ChineseNewsFetcher({
        "wallstreetcn_channels": [{"channel": "global", "name": "test"}],
        "max_items_per_source": 5,
        "request_delay_seconds": 0,
    })

    mock_session = mocker.AsyncMock()
    mock_resp = mocker.AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"code": 50000, "message": "Error"}

    mock_session.get.return_value.__aenter__.return_value = mock_resp
    fetcher._session = mock_session

    items = await fetcher.fetch_wallstreetcn_channel({"channel": "global", "name": "test"})
    assert items == []


@pytest.mark.asyncio
async def test_fetch_all_empty_config():
    """Empty config returns empty result."""
    fetcher = ChineseNewsFetcher({})
    items = await fetcher.fetch_all()
    assert items == []


def test_parse_zhibo_feed_extracts_headline_and_url():
    """New Sina 7x24 zhibo feed: rich_text -> title(from 【】)+content, docurl -> url."""
    fetcher = ChineseNewsFetcher({"max_items_per_source": 5})
    data = {"result": {"status": {"code": 0}, "data": {"feed": {"list": [
        {"rich_text": "【英伟达公布自研AI芯片进展 盘后涨5%】英伟达在财报电话会上宣布新一代自研AI芯片。",
         "create_time": "2026-07-10 11:09:33",
         "docurl": "https://finance.sina.cn/7x24/2026-07-10/detail-a.d.html"},
        {"rich_text": "白银连续主力合约日内涨4%，现报14805.00元。",
         "create_time": "2026-07-10 11:09:09",
         "docurl": "https://finance.sina.cn/7x24/2026-07-10/detail-b.d.html"},
    ]}}}}
    items = fetcher._parse_zhibo_feed(data, "7x24")
    assert len(items) == 2
    assert items[0].title == "英伟达公布自研AI芯片进展 盘后涨5%"          # from 【】
    assert "财报电话会" in items[0].content_snippet
    assert items[0].url.startswith("https://finance.sina.cn/7x24")
    assert items[0].source == "新浪财经·7x24"
    assert isinstance(items[0].published_at, datetime)
    assert items[1].title.startswith("白银连续主力合约")               # no bracket → text itself


def test_parse_zhibo_feed_empty_and_malformed():
    fetcher = ChineseNewsFetcher({"max_items_per_source": 5})
    assert fetcher._parse_zhibo_feed({}, "x") == []
    assert fetcher._parse_zhibo_feed({"result": {"data": {"feed": {"list": []}}}}, "x") == []
