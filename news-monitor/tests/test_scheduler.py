"""Tests for the master scheduler."""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call


@pytest.fixture
def scheduler_setup():
    """Create a NewsScheduler with all mocked dependencies."""
    from collector.scheduler import NewsScheduler
    from collector.exchange_calendar import ExchangeCalendar

    config = MagicMock()
    config.load_settings.return_value = {
        "storage": {"sqlite_path": ":memory:"},
        "weekend_multiplier": 3,
    }
    config.load_sources.return_value = {
        "tier_1_rss": [
            {"name": "CNBC", "url": "https://cnbc.com/rss"},
            {"name": "Reuters", "url": "https://reuters.com/rss"},
        ],
        "tier_2_playwright": [
            {"name": "ZeroHedge", "url": "https://zerohedge.com", "frequency_tier": "heartbeat"},
        ],
    }

    db = MagicMock()
    dedup = MagicMock()
    dedup.filter_duplicates.side_effect = lambda items: items  # Pass-through by default

    scheduler = NewsScheduler(config, db, dedup)

    # Mock the fetchers
    scheduler.rss_fetcher = MagicMock()
    scheduler.rss_fetcher.fetch_all = AsyncMock(return_value=[])
    scheduler.rss_fetcher.close = AsyncMock()

    scheduler.playwright_fetcher = MagicMock()
    scheduler.playwright_fetcher.fetch_source = AsyncMock(return_value=[])
    scheduler.playwright_fetcher.startup = AsyncMock()
    scheduler.playwright_fetcher.shutdown = AsyncMock()

    scheduler.api_fetcher = MagicMock()
    scheduler.api_fetcher.check_all = AsyncMock(return_value=[])
    scheduler.api_fetcher.close = AsyncMock()

    scheduler.twitter_fetcher = MagicMock()
    scheduler.twitter_fetcher.fetch_all = AsyncMock(return_value=[])
    scheduler.twitter_fetcher.close = AsyncMock()
    scheduler.twitter_fetcher.shutdown = AsyncMock()
    scheduler.twitter_fetcher.startup = AsyncMock()

    scheduler.calendar = MagicMock(spec=ExchangeCalendar)
    scheduler.calendar.is_weekend_mode.return_value = False

    return {
        "scheduler": scheduler,
        "config": config,
        "db": db,
        "dedup": dedup,
    }


# ---------------------------------------------------------------------------
# _insert_and_notify
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_and_notify_basic(scheduler_setup):
    s = scheduler_setup["scheduler"]
    db = scheduler_setup["db"]
    dedup = scheduler_setup["dedup"]

    from storage.models import NewsItem
    item = NewsItem(title="Test", url="https://t.com/1", source="T")
    await s._insert_and_notify([item])

    db.insert_news.assert_called_once()
    # Should index item after insert
    dedup.index_item.assert_called_once()


@pytest.mark.asyncio
async def test_insert_and_notify_dedup_filters_all(scheduler_setup):
    s = scheduler_setup["scheduler"]
    dedup = scheduler_setup["dedup"]
    dedup.filter_duplicates.side_effect = lambda items: []  # Filter everything

    from storage.models import NewsItem
    item = NewsItem(title="Test", url="https://t.com/1", source="T")
    await s._insert_and_notify([item])

    # Nothing should be inserted
    scheduler_setup["db"].insert_news.assert_not_called()


@pytest.mark.asyncio
async def test_insert_and_notify_empty_list(scheduler_setup):
    s = scheduler_setup["scheduler"]
    await s._insert_and_notify([])
    scheduler_setup["db"].insert_news.assert_not_called()


@pytest.mark.asyncio
async def test_insert_and_notify_calls_callbacks(scheduler_setup):
    s = scheduler_setup["scheduler"]
    callback = AsyncMock()
    s.on_news_batch(callback)

    from storage.models import NewsItem
    item = NewsItem(title="Test", url="https://t.com/1", source="T")
    await s._insert_and_notify([item])

    callback.assert_called_once_with([item])


# ---------------------------------------------------------------------------
# _load_watchlist
# ---------------------------------------------------------------------------

def test_load_watchlist_default(scheduler_setup):
    s = scheduler_setup["scheduler"]
    tickers = s._load_watchlist()
    assert "AAPL" in tickers
    assert "NVDA" in tickers
    assert len(tickers) >= 7


def test_load_watchlist_from_file(tmp_path):
    """Load watchlist from a mock memory file."""
    from collector.scheduler import NewsScheduler

    watchlist_content = """---
name: watchlist-state
---

| AAPL | Apple |
| NVDA | NVIDIA |
| TSLA | Tesla |
"""
    watchlist_file = tmp_path / "watchlist-state.md"
    watchlist_file.write_text(watchlist_content)

    config = MagicMock()
    config.load_settings.return_value = {"storage": {"sqlite_path": ":memory:"}}
    config.load_sources.return_value = {"tier_1_rss": [], "tier_2_playwright": []}

    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=watchlist_content):
        s = NewsScheduler(config, MagicMock())
        # The path is relative, override it for testing
        tickers = s._load_watchlist()
        assert "AAPL" in tickers


# ---------------------------------------------------------------------------
# _get_frequency (weekend multiplier)
# ---------------------------------------------------------------------------

def test_get_frequency_weekday(scheduler_setup):
    s = scheduler_setup["scheduler"]
    s.calendar.is_weekend_mode.return_value = False
    assert s._get_frequency(60) == 60
    assert s._get_frequency(300) == 300


def test_get_frequency_weekend(scheduler_setup):
    s = scheduler_setup["scheduler"]
    s.calendar.is_weekend_mode.return_value = True
    assert s._get_frequency(60) == 180  # 60 * 3
    assert s._get_frequency(900) == 2700  # 900 * 3


# ---------------------------------------------------------------------------
# Tick methods
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_fetches_rss_and_chinese(scheduler_setup):
    """RSS + Chinese + API + Playwright run on heartbeat tick. Web scraper moved to 60s _scraper_tick."""
    s = scheduler_setup["scheduler"]

    from storage.models import NewsItem
    rss_items = [NewsItem(title="RSS News", url="https://n.com/1", source="CNBC")]
    cn_items = [NewsItem(title="中文新闻", url="https://n.com/2", source="新浪财经")]
    s.rss_fetcher.fetch_all.return_value = rss_items
    s.chinese_fetcher = MagicMock()
    s.chinese_fetcher.fetch_all = AsyncMock(return_value=cn_items)

    await s._heartbeat_tick()

    s.rss_fetcher.fetch_all.assert_called_once()
    s.chinese_fetcher.fetch_all.assert_called_once()
    scheduler_setup["db"].insert_news.assert_called()


@pytest.mark.asyncio
async def test_scraper_tick(scheduler_setup):
    """Web scraper runs in its own 60s tick, independent of heartbeat."""
    s = scheduler_setup["scheduler"]

    from storage.models import NewsItem
    scrape_items = [NewsItem(title="CNBC Homepage", url="https://cnbc.com/1", source="CNBC")]
    s.web_scraper = MagicMock()
    s.web_scraper.fetch_all = AsyncMock(return_value=scrape_items)

    await s._scraper_tick()

    s.web_scraper.fetch_all.assert_called_once()
    scheduler_setup["db"].insert_news.assert_called()


@pytest.mark.asyncio
async def test_tick_5min_fetches_finnhub_only(scheduler_setup):
    """5-min tick runs Finnhub + Playwright. Twitter moved to 15-min to reduce load."""
    s = scheduler_setup["scheduler"]

    s.twitter_fetcher = MagicMock()
    s.twitter_fetcher.fetch_all = AsyncMock(return_value=[])
    s.finnhub_fetcher = MagicMock()
    s.finnhub_fetcher.fetch_all = AsyncMock(return_value=[])

    await s._tick_5min()

    # Twitter should NOT be called in 5-min tick anymore
    s.twitter_fetcher.fetch_all.assert_not_called()
    s.finnhub_fetcher.fetch_all.assert_called_once()


@pytest.mark.asyncio
async def test_tick_15min_is_noop(scheduler_setup):
    """15-min tick is a no-op — Twitter disabled for resource conservation."""
    s = scheduler_setup["scheduler"]

    s.twitter_fetcher = MagicMock()
    s.twitter_fetcher.fetch_all = AsyncMock()
    s.twitter_fetcher.close = AsyncMock()

    await s._tick_15min()

    s.twitter_fetcher.fetch_all.assert_not_called()
    scheduler_setup["db"].insert_news.assert_not_called()


@pytest.mark.asyncio
async def test_tick_30min_runs_cleanup(scheduler_setup):
    """_tick_30min should run without error (currently a pass)."""
    s = scheduler_setup["scheduler"]
    await s._tick_30min()  # Should not raise


@pytest.mark.asyncio
async def test_heartbeat_tick(scheduler_setup):
    s = scheduler_setup["scheduler"]

    from storage.models import NewsItem
    pw_items = [NewsItem(title="ZH Headline", url="https://zh.com/1", source="ZeroHedge")]
    s.playwright_fetcher.fetch_source.return_value = pw_items
    s.api_fetcher.check_all.return_value = []

    await s._heartbeat_tick()

    s.playwright_fetcher.fetch_source.assert_called()
    scheduler_setup["db"].insert_news.assert_called()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_stop(scheduler_setup):
    s = scheduler_setup["scheduler"]

    await s.start()
    assert s._running is True

    # Let one loop iteration fire, then stop
    await s.stop()
    assert s._running is False

    s.rss_fetcher.close.assert_called_once()
    s.playwright_fetcher.shutdown.assert_called_once()
    s.api_fetcher.close.assert_called_once()


# ---------------------------------------------------------------------------
# Callback error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_error_isolation(scheduler_setup):
    """If one callback raises, others should still fire."""
    s = scheduler_setup["scheduler"]
    good = AsyncMock()
    bad = AsyncMock(side_effect=RuntimeError("boom"))
    s.on_news_batch(bad)
    s.on_news_batch(good)

    from storage.models import NewsItem
    item = NewsItem(title="T", url="https://x.com/1", source="X")
    await s._notify_callbacks([item])

    good.assert_called_once()
