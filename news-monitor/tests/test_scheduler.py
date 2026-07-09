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

    scheduler.calendar = MagicMock(spec=ExchangeCalendar)
    scheduler.calendar.is_weekend_mode.return_value = False

    return {
        "scheduler": scheduler,
        "config": config,
        "db": db,
        "dedup": dedup,
    }


# ---------------------------------------------------------------------------
# _notify_callbacks (Phase 3: raw items, no dedup/DB/vector in scheduler)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_callbacks_basic(scheduler_setup):
    """Callbacks receive raw items — IngestStage handles dedup/DB later."""
    s = scheduler_setup["scheduler"]
    callback = AsyncMock()
    s.on_news_batch(callback)

    from storage.models import NewsItem
    item = NewsItem(title="Test", url="https://t.com/1", source="T")
    await s._notify_callbacks([item])

    callback.assert_called_once_with([item])
    # Scheduler no longer handles dedup/DB
    scheduler_setup["db"].insert_news.assert_not_called()


@pytest.mark.asyncio
async def test_notify_callbacks_empty_list(scheduler_setup):
    s = scheduler_setup["scheduler"]
    await s._notify_callbacks([])
    scheduler_setup["db"].insert_news.assert_not_called()


@pytest.mark.asyncio
async def test_notify_callbacks_multiple(scheduler_setup):
    s = scheduler_setup["scheduler"]
    cb1 = AsyncMock()
    cb2 = AsyncMock()
    s.on_news_batch(cb1)
    s.on_news_batch(cb2)

    from storage.models import NewsItem
    items = [
        NewsItem(title="A", url="https://a.com", source="X"),
        NewsItem(title="B", url="https://b.com", source="Y"),
    ]
    await s._notify_callbacks(items)

    cb1.assert_called_once_with(items)
    cb2.assert_called_once_with(items)


# ---------------------------------------------------------------------------
# _load_watchlist
# ---------------------------------------------------------------------------

def test_load_watchlist_default(scheduler_setup):
    s = scheduler_setup["scheduler"]
    tickers = s._load_watchlist()
    assert "NVDA" in tickers
    assert "TSLA" in tickers
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
    """RSS and Chinese run on 1-min heartbeat tick (promoted from 15-min, then 5-min)."""
    s = scheduler_setup["scheduler"]
    callback = AsyncMock()
    s.on_news_batch(callback)

    from storage.models import NewsItem
    rss_items = [NewsItem(title="RSS News", url="https://n.com/1", source="CNBC")]
    cn_items = [NewsItem(title="中文新闻", url="https://n.com/2", source="新浪财经")]
    s.rss_fetcher.fetch_all.return_value = rss_items
    s.chinese_fetcher = MagicMock()
    s.chinese_fetcher.fetch_all = AsyncMock(return_value=cn_items)
    s.web_scraper = MagicMock()
    s.web_scraper.fetch_all = AsyncMock(return_value=[])

    await s._heartbeat_tick()

    s.rss_fetcher.fetch_all.assert_called_once()
    s.chinese_fetcher.fetch_all.assert_called_once()
    s.web_scraper.fetch_all.assert_called_once()
    # Phase 3: scheduler just notifies, no DB insert
    callback.assert_called_once()
    # Callback received all items (RSS + Chinese)
    called_with = callback.call_args[0][0]
    assert len(called_with) == 2


@pytest.mark.asyncio
async def test_tick_5min_fetches_twitter_and_finnhub(scheduler_setup):
    """5-min tick still runs Twitter + Finnhub (RSS/Chinese moved to heartbeat)."""
    s = scheduler_setup["scheduler"]
    callback = AsyncMock()
    s.on_news_batch(callback)

    from storage.models import NewsItem
    twitter_items = [NewsItem(title="Tweet", url="https://n.com/3", source="Twitter")]
    s.twitter_fetcher = MagicMock()
    s.twitter_fetcher.fetch_all = AsyncMock(return_value=twitter_items)
    s.finnhub_fetcher = MagicMock()
    s.finnhub_fetcher.fetch_all = AsyncMock(return_value=[])

    await s._tick_5min()

    s.twitter_fetcher.fetch_all.assert_called_once()
    # Phase 3: scheduler just notifies, no DB insert
    callback.assert_called_once_with(twitter_items)


@pytest.mark.asyncio
async def test_tick_15min_is_noop(scheduler_setup):
    """_tick_15min is now a no-op — all content moved to heartbeat + 5-min."""
    s = scheduler_setup["scheduler"]
    await s._tick_15min()
    scheduler_setup["db"].insert_news.assert_not_called()


@pytest.mark.asyncio
async def test_tick_30min_runs_cleanup(scheduler_setup):
    """_tick_30min should run without error (currently a pass)."""
    s = scheduler_setup["scheduler"]
    await s._tick_30min()  # Should not raise


@pytest.mark.asyncio
async def test_heartbeat_tick(scheduler_setup):
    s = scheduler_setup["scheduler"]
    callback = AsyncMock()
    s.on_news_batch(callback)

    from storage.models import NewsItem
    pw_items = [NewsItem(title="ZH Headline", url="https://zh.com/1", source="ZeroHedge")]
    s.playwright_fetcher.fetch_source.return_value = pw_items
    s.api_fetcher.check_all.return_value = []

    await s._heartbeat_tick()

    s.playwright_fetcher.fetch_source.assert_called()
    # Phase 3: scheduler just notifies, no DB insert
    callback.assert_called_once()
    called_with = callback.call_args[0][0]
    assert len(called_with) >= 1


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


# ---------------------------------------------------------------------------
# Phase 4a: parallelized tick — exception isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_parallel_exception_isolation(scheduler_setup):
    """If one collector raises, others still produce results (gather isolation)."""
    s = scheduler_setup["scheduler"]
    callback = AsyncMock()
    s.on_news_batch(callback)

    from storage.models import NewsItem

    # Chinese fetcher fails, RSS succeeds
    s.chinese_fetcher.fetch_all = AsyncMock(side_effect=RuntimeError("chinese boom"))
    rss_items = [NewsItem(title="RSS OK", url="https://x.com/1", source="CNBC")]
    s.rss_fetcher.fetch_all = AsyncMock(return_value=rss_items)
    s.playwright_fetcher.fetch_source = AsyncMock(return_value=[])
    s.api_fetcher.check_all = AsyncMock(return_value=[])
    s.web_scraper.fetch_all = AsyncMock(return_value=[])

    await s._heartbeat_tick()

    # Callback should still receive RSS items despite Chinese failure
    callback.assert_called_once()
    called_with = callback.call_args[0][0]
    titles = [item.title for item in called_with]
    assert "RSS OK" in titles


@pytest.mark.asyncio
async def test_tick_5min_parallel_exception_isolation(scheduler_setup):
    """If one 5-min collector fails, others still produce results."""
    s = scheduler_setup["scheduler"]
    callback = AsyncMock()
    s.on_news_batch(callback)

    from storage.models import NewsItem

    # Twitter fails, Finnhub succeeds
    s.playwright_fetcher.fetch_source = AsyncMock(return_value=[])
    s.twitter_fetcher.fetch_all = AsyncMock(side_effect=RuntimeError("twitter boom"))
    finnhub_items = [NewsItem(title="Finn OK", url="https://x.com/2", source="Finnhub")]
    s.finnhub_fetcher.fetch_all = AsyncMock(return_value=finnhub_items)

    await s._tick_5min()

    callback.assert_called_once()
    called_with = callback.call_args[0][0]
    titles = [item.title for item in called_with]
    assert "Finn OK" in titles


@pytest.mark.asyncio
async def test_heartbeat_parallel_all_collectors_called(scheduler_setup):
    """All 5 collectors are invoked (not just the first one)."""
    s = scheduler_setup["scheduler"]
    callback = AsyncMock()
    s.on_news_batch(callback)

    # Mock all fetchers to return empty lists
    s.chinese_fetcher.fetch_all = AsyncMock(return_value=[])
    s.rss_fetcher.fetch_all = AsyncMock(return_value=[])
    s.playwright_fetcher.fetch_source = AsyncMock(return_value=[])
    s.api_fetcher.check_all = AsyncMock(return_value=[])
    s.web_scraper.fetch_all = AsyncMock(return_value=[])

    await s._heartbeat_tick()

    s.chinese_fetcher.fetch_all.assert_called_once()
    s.rss_fetcher.fetch_all.assert_called_once()
    s.playwright_fetcher.fetch_source.assert_called()
    s.api_fetcher.check_all.assert_called_once()
    s.web_scraper.fetch_all.assert_called_once()
