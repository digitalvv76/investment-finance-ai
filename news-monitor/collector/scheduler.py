"""Master scheduler with 4-tier frequency and exchange calendar awareness."""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Callable, Awaitable, List, Dict

from collector.exchange_calendar import ExchangeCalendar
from collector.rss_fetcher import RSSFetcher
from collector.playwright_fetcher import PlaywrightFetcher
from collector.api_fetcher import APIFetcher
from config.loader import ConfigLoader
from storage.database import Database
from storage.models import NewsItem

logger = logging.getLogger(__name__)

NewsCallback = Callable[[List[NewsItem]], Awaitable[None]]


class NewsScheduler:
    def __init__(self, config: ConfigLoader, db: Database, dedup=None):
        self.config = config
        self.db = db
        self.dedup = dedup
        self.calendar = ExchangeCalendar()

        self.settings = config.load_settings()
        self.sources = config.load_sources()

        self._callbacks: List[NewsCallback] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []

        # Initialize fetchers
        self.rss_fetcher = RSSFetcher(self.sources.get('tier_1_rss', []))
        self.playwright_fetcher = PlaywrightFetcher(
            self.sources.get('tier_2_playwright', [])
        )
        self.api_fetcher = APIFetcher(
            watchlist=self._load_watchlist()
        )

        # Track last fetch times for adaptive throttling
        self._last_heartbeat_results: Dict[str, int] = {}  # source -> consecutive empty count

    def _load_watchlist(self) -> list:
        """Load watchlist from .claude/memory/watchlist-state.md."""
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
        try:
            from pathlib import Path
            watchlist_path = Path("../../.claude/memory/watchlist-state.md")
            if watchlist_path.exists():
                content = watchlist_path.read_text()
                import re
                found = re.findall(r'\|\s*([A-Z]{1,5})\s*\|', content)
                if found:
                    tickers = [t for t in found if t.isalpha() and len(t) <= 5]
        except Exception:
            pass
        return tickers

    def on_news_batch(self, callback: NewsCallback):
        """Register a callback to be called when new news items arrive."""
        self._callbacks.append(callback)

    async def _notify_callbacks(self, items: List[NewsItem]):
        for cb in self._callbacks:
            try:
                await cb(items)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def _insert_and_notify(self, items: List[NewsItem]):
        """Dedup, insert, and notify callbacks for a batch of items."""
        if not items:
            return

        # Dedup filtering (Tier 1-3)
        if self.dedup:
            items = self.dedup.filter_duplicates(items)
            if not items:
                return

        for item in items:
            self.db.insert_news(item)
            # Index into vector store AFTER insert (needs item.id)
            if self.dedup:
                self.dedup.index_item(item)

        await self._notify_callbacks(items)

    async def _heartbeat_tick(self):
        """1-minute heartbeat: check Tier 2 breaking sources + API triggers."""
        items = []

        # Only heartbeat sources
        heartbeat_sources = [
            s for s in self.sources.get('tier_2_playwright', [])
            if s.get('frequency_tier') == 'heartbeat'
        ]

        for source in heartbeat_sources:
            src_items = await self.playwright_fetcher.fetch_source(source)
            items.extend(src_items)

        # API triggers
        api_items = await self.api_fetcher.check_all()
        items.extend(api_items)

        if items:
            logger.info(f"Heartbeat: {len(items)} items")
            await self._insert_and_notify(items)
        else:
            logger.debug("Heartbeat: no new items")

    async def _tick_5min(self):
        """5-minute tick: remaining Playwright sources + fast RSS."""
        sources = [
            s for s in self.sources.get('tier_2_playwright', [])
            if s.get('frequency_tier') != 'heartbeat'
        ]
        items = []
        for source in sources:
            src_items = await self.playwright_fetcher.fetch_source(source)
            items.extend(src_items)

        if items:
            await self._insert_and_notify(items)

    async def _tick_15min(self):
        """15-minute tick: all RSS sources."""
        items = await self.rss_fetcher.fetch_all()
        if items:
            await self._insert_and_notify(items)

    async def _tick_30min(self):
        """30-minute tick: low-priority background tasks.

        - Purge news older than 90 days
        - Reclaim disk space (every 6 hours)
        - Log database stats
        """
        try:
            deleted = self.db.purge_old_news(days=90)
            if deleted:
                logger.info("Retention: purged %d old news items", deleted)

            # Vacuum every 12 ticks (6 hours at 30-min intervals)
            if not hasattr(self, '_tick_30min_counter'):
                self._tick_30min_counter = 0
            self._tick_30min_counter += 1
            if self._tick_30min_counter % 12 == 0:
                self.db.vacuum()

            # Log stats every 30 min for monitoring
            stats = self.db.get_db_stats()
            logger.debug(
                "DB stats: %d news, %d feedback, %d events, %.1f MB",
                stats["news_count"], stats["feedback_count"],
                stats["event_count"], stats["db_size_mb"],
            )
        except Exception as e:
            logger.warning("Retention/cleanup failed: %s", e)

    def _get_frequency(self, base_seconds: int) -> int:
        """Apply weekend multiplier if market is closed."""
        if self.calendar.is_weekend_mode():
            multiplier = self.settings.get('weekend_multiplier', 3)
            return base_seconds * multiplier
        return base_seconds

    async def _run_loop(self):
        """Main scheduling loop."""
        last_1min = last_5min = last_15min = last_30min = 0

        # Startup Playwright
        try:
            await self.playwright_fetcher.startup()
        except Exception as e:
            logger.error(f"Playwright startup failed: {e}")

        while self._running:
            now = time.time()

            try:
                if now - last_1min >= self._get_frequency(60):
                    await self._heartbeat_tick()
                    last_1min = now

                if now - last_5min >= self._get_frequency(300):
                    await self._tick_5min()
                    last_5min = now

                if now - last_15min >= self._get_frequency(900):
                    await self._tick_15min()
                    last_15min = now

                if now - last_30min >= self._get_frequency(1800):
                    await self._tick_30min()
                    last_30min = now
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}")

            await asyncio.sleep(10)  # Check every 10 seconds

    async def start(self):
        """Start the scheduler."""
        logger.info("Scheduler starting...")
        self._running = True
        self._tasks.append(asyncio.create_task(self._run_loop()))

    async def stop(self):
        """Stop the scheduler gracefully."""
        logger.info("Scheduler stopping...")
        self._running = False
        for task in self._tasks:
            task.cancel()
        await self.rss_fetcher.close()
        await self.playwright_fetcher.shutdown()
        await self.api_fetcher.close()
