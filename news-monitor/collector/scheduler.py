"""Master scheduler with 4-tier frequency and exchange calendar awareness."""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Callable, Awaitable, List

from collector.exchange_calendar import ExchangeCalendar
from collector.rss_fetcher import RSSFetcher
from collector.playwright_fetcher import PlaywrightFetcher
from collector.api_fetcher import APIFetcher
from collector.twitter_fetcher import TwitterFetcher
from collector.chinese_fetcher import ChineseNewsFetcher
from collector.finnhub_fetcher import FinnhubNewsFetcher
from collector.web_scraper import WebScraper
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
        self.twitter_fetcher = TwitterFetcher(
            self.sources.get('twitter', {})
        )
        self.chinese_fetcher = ChineseNewsFetcher(
            self.sources.get('chinese_sources', {})
        )
        # Web scraper is optional — toggle via sources.yaml: web_scraper.enabled
        scraper_cfg = self.sources.get('web_scraper', {})
        self.web_scraper = WebScraper() if scraper_cfg.get('enabled', False) else None
        self.finnhub_fetcher = FinnhubNewsFetcher(
            watchlist=self._load_watchlist()
        )

    def _load_watchlist(self) -> list:
        """Load watchlist from .claude/memory/watchlist-state.md.

        Tries multiple parent levels because the repo root differs between
        Windows (D:/class1 = parents[3]) and Docker (/app = parents[2]).
        """
        tickers = ["NVDA", "TSLA", "SPCX", "PLTR", "SOXX", "SOXL", "RKLB",
                   "KTOS", "BOT", "LRCX", "MRAAY", "CBRS", "ARM", "MRVL",
                   "ASTS", "RGTI", "TEM", "NBIS", "OKLO", "SMR", "ARKK"]
        try:
            from pathlib import Path
            import re
            module_file = Path(__file__).resolve()
            # Try parents[2] (Docker: /app) and parents[3] (Windows: D:/class1)
            for offset in (2, 3):
                candidate = module_file.parents[offset] / ".claude" / "memory" / "watchlist-state.md"
                if candidate.exists():
                    content = candidate.read_text()
                    found = re.findall(r'\|\s*([A-Z]{1,5})\s*\|', content)
                    if found:
                        tickers = [t for t in found if t.isalpha() and len(t) <= 5]
                    break
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
        """1-minute heartbeat: all collectors run concurrently via asyncio.gather.

        Chinese + RSS + Playwright(hb) + API + WebScraper fire simultaneously.
        Old serial: ~85s.  New concurrent: ~32s (bottleneck = slowest collector).
        """
        # ---- Launch all collectors concurrently ----
        cn_task = self._safe_fetch(
            self.chinese_fetcher.fetch_all(), "chinese"
        )
        rss_task = self._safe_fetch(
            self.rss_fetcher.fetch_all(), "rss"
        )

        # Heartbeat-only Playwright sources (ZeroHedge)
        hb_sources = [
            s for s in self.sources.get('tier_2_playwright', [])
            if s.get('frequency_tier') == 'heartbeat'
        ]
        pw_task = self._safe_fetch(
            self._fetch_playwright_sources(hb_sources), "playwright(hb)"
        )

        api_task = self._safe_fetch(
            self.api_fetcher.check_all(), "api"
        )

        scrape_task = self._safe_fetch(
            self.web_scraper.fetch_all() if self.web_scraper is not None else [],
            "web_scraper",
        )

        results = await asyncio.gather(
            cn_task, rss_task, pw_task, api_task, scrape_task,
        )

        # ---- Merge all results ----
        items = []
        for result in results:
            if result:
                items.extend(result)

        if items:
            logger.info(f"Heartbeat: {len(items)} items (cn+rss+pw+api+scrape)")
            await self._insert_and_notify(items)

    async def _safe_fetch(self, coro_or_items, label: str) -> list:
        """Await a coroutine or return a list, catching and logging errors.

        Used by concurrent ticks — one collector failing must not drop the
        results from the other collectors running in the same gather().
        """
        import inspect as _inspect
        if _inspect.iscoroutine(coro_or_items):
            try:
                return await coro_or_items
            except Exception as e:
                logger.warning("%s fetch failed: %s", label, e)
                return []
        # Already a list (e.g. empty list for disabled scraper)
        return coro_or_items or []

    async def _fetch_playwright_sources(self, sources: list) -> list:
        """Fetch a list of Playwright sources (serial within this group).

        Kept serial because all sources share one browser instance;
        parallel page access inside one browser is fragile.
        """
        items = []
        for source in sources:
            try:
                src_items = await self.playwright_fetcher.fetch_source(source)
                items.extend(src_items)
            except Exception as e:
                logger.warning("Playwright source %s failed: %s",
                               source.get('name', '?'), e)
        return items

    async def _tick_5min(self):
        """5-minute tick: Finnhub + remaining Playwright concurrent.

        Twitter moved to 15-min tick to reduce Chromium CPU/memory pressure.
        """
        sources = [
            s for s in self.sources.get('tier_2_playwright', [])
            if s.get('frequency_tier') != 'heartbeat'
        ]

        pw_task = self._safe_fetch(
            self._fetch_playwright_sources(sources), "playwright(5min)"
        )
        finnhub_task = self._safe_fetch(
            self.finnhub_fetcher.fetch_all(), "finnhub"
        )

        results = await asyncio.gather(pw_task, finnhub_task)
        items = []
        for result in results:
            if result:
                items.extend(result)

        if items:
            await self._insert_and_notify(items)

    async def _tick_15min(self):
        """15-minute tick: currently no-op (Twitter disabled for resource conservation).

        To re-enable Twitter: uncomment the Twitter fetch + browser close below,
        and uncomment twitter_fetcher.startup() in _run_loop().
        """
        # Twitter disabled — too heavy for 2C4G ECS (3 Chromium instances = 180% CPU)
        # twitter_task = self._safe_fetch(
        #     self.twitter_fetcher.fetch_all(), "twitter"
        # )
        # results = await asyncio.gather(twitter_task)
        # items = []
        # for result in results:
        #     if result:
        #         items.extend(result)
        # if items:
        #     await self._insert_and_notify(items)
        # try:
        #     await self.twitter_fetcher.close()
        # except Exception as e:
        #     logger.warning("Twitter browser close failed: %s", e)
        pass

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

        # Startup Twitter browser (DISABLED — too heavy for 2C4G ECS)
        # To re-enable: uncomment below + restore _tick_15min Twitter fetch
        # try:
        #     await self.twitter_fetcher.startup()
        # except Exception as e:
        #     logger.warning(f"Twitter fetcher startup failed (non-fatal): {e}")
        logger.info("Twitter: disabled (resource conservation)")

        while self._running:
            now = time.monotonic()

            try:
                if now - last_1min >= self._get_frequency(120):
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

            await asyncio.sleep(5)  # Check every 5 seconds (was 10s)

    async def start(self):
        """Start the scheduler."""
        logger.info("Scheduler starting...")
        self._running = True
        if self.web_scraper is not None:
            await self.web_scraper.startup()
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
        await self.twitter_fetcher.shutdown()
        await self.chinese_fetcher.close()
        if self.web_scraper is not None:
            await self.web_scraper.shutdown()
        await self.finnhub_fetcher.close()
