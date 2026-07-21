"""Master scheduler with 4-tier frequency and exchange calendar awareness."""
import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Callable, Awaitable, List

from collector.exchange_calendar import ExchangeCalendar
from collector.rss_fetcher import RSSFetcher
from collector.playwright_fetcher import PlaywrightFetcher
from collector.api_fetcher import APIFetcher
from collector.twitter_fetcher import TwitterFetcher
from collector.chinese_fetcher import ChineseNewsFetcher
from collector.futu_news_fetcher import FutuNewsFetcher
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
        self.web_scraper = WebScraper()
        self.finnhub_fetcher = FinnhubNewsFetcher(
            watchlist=self._load_watchlist()
        )
        futu_host = os.environ.get("FUTU_OPEND_HOST", "172.18.0.1")
        futu_port = int(os.environ.get("FUTU_OPEND_PORT", "11111"))
        self.futu_news_fetcher = FutuNewsFetcher(
            host=futu_host, port=futu_port,
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
        """Notify all callbacks with a hard timeout to prevent scheduler stall.

        Each callback gets CALLBACK_TIMEOUT seconds. If it hangs (e.g. LLM API
        TCP stall that bypasses SDK timeout), we cancel it and keep the
        scheduler alive.  This is the LAST LINE OF DEFENSE — individual stages
        have their own tighter timeouts.
        """
        CALLBACK_TIMEOUT = 120  # generous: pipeline has own per-stage timeouts
        for cb in self._callbacks:
            try:
                await asyncio.wait_for(cb(items), timeout=CALLBACK_TIMEOUT)
            except asyncio.TimeoutError:
                logger.error(
                    "Callback %s timed out after %ds — scheduler continuing",
                    getattr(cb, '__name__', str(cb)), CALLBACK_TIMEOUT,
                )
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def _heartbeat_tick(self):
        """1-minute heartbeat: Chinese + RSS + Playwright + API + Web scraper + Futu + Finnhub.

        All seven collectors run concurrently via asyncio.gather. Each
        collector is independently exception-isolated (return_exceptions=True)
        AND timeout-protected (asyncio.wait_for).

        Combined tick ~15s, well under 60s limit.
        """
        heartbeat_sources = [
            s for s in self.sources.get('tier_2_playwright', [])
            if s.get('frequency_tier') == 'heartbeat'
        ]

        async def _fetch_chinese():
            try:
                return await asyncio.wait_for(
                    self.chinese_fetcher.fetch_all(), timeout=45,
                )
            except asyncio.TimeoutError:
                logger.warning("Chinese news fetch timed out after 45s")
                return []
            except Exception as e:
                logger.warning("Chinese news fetch failed: %s", e)
                return []

        async def _fetch_rss():
            try:
                return await asyncio.wait_for(
                    self.rss_fetcher.fetch_all(), timeout=45,
                )
            except asyncio.TimeoutError:
                logger.warning("RSS fetch timed out after 45s")
                return []
            except Exception as e:
                logger.warning("RSS fetch failed: %s", e)
                return []

        async def _fetch_playwright_heartbeat():
            try:
                return await asyncio.wait_for(
                    self._run_playwright_heartbeat(heartbeat_sources), timeout=50,
                )
            except asyncio.TimeoutError:
                logger.warning("PW heartbeat timed out after 50s")
                return []
            except Exception as e:
                logger.warning("PW heartbeat failed: %s", e)
                return []

        async def _fetch_api():
            try:
                return await asyncio.wait_for(
                    self.api_fetcher.check_all(), timeout=30,
                )
            except asyncio.TimeoutError:
                logger.warning("API check timed out after 30s")
                return []
            except Exception as e:
                logger.warning("API check failed: %s", e)
                return []

        async def _fetch_futu_news():
            try:
                return await asyncio.wait_for(
                    self.futu_news_fetcher.fetch(), timeout=30,
                )
            except asyncio.TimeoutError:
                logger.warning("Futu news fetch timed out after 30s")
                return []
            except Exception as e:
                logger.warning("Futu news fetch failed: %s", e)
                return []

        async def _fetch_finnhub():
            try:
                return await asyncio.wait_for(
                    self.finnhub_fetcher.fetch_all(), timeout=45,
                )
            except asyncio.TimeoutError:
                logger.warning("Finnhub fetch timed out after 45s")
                return []
            except Exception as e:
                logger.warning("Finnhub fetch failed: %s", e)
                return []

        async def _fetch_web_scraper():
            try:
                return await asyncio.wait_for(
                    self.web_scraper.fetch_all(), timeout=45,
                )
            except asyncio.TimeoutError:
                logger.warning("Web scraper timed out after 45s")
                return []
            except Exception as e:
                logger.warning("Web scraper failed: %s", e)
                return []

        # Defense-in-depth: gather timeout as last line of defense
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    _fetch_chinese(),
                    _fetch_rss(),
                    _fetch_playwright_heartbeat(),
                    _fetch_api(),
                    _fetch_web_scraper(),
                    _fetch_futu_news(),
                    _fetch_finnhub(),
                    return_exceptions=True,
                ),
                timeout=55,  # heartbeat fires every 60s, leave 5s margin
            )
        except asyncio.TimeoutError:
            logger.error(
                "Heartbeat gather timed out after 55s — one or more fetchers hung"
            )
            return

        items = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Heartbeat collector failed: %s", result)
            elif result:
                items.extend(result)

        if items:
            logger.info(f"Heartbeat: {len(items)} items (cn+rss+pw+api+scrape+futu+finnhub)")
            await self._notify_callbacks(items)

    async def _run_playwright_heartbeat(self, sources):
        """Run Playwright heartbeat fetches sequentially (shared browser)."""
        items = []
        for source in sources:
            try:
                src_items = await self.playwright_fetcher.fetch_source(source)
                items.extend(src_items)
            except Exception as e:
                logger.warning("PW heartbeat %s failed: %s",
                               source.get('name', '?'), e)
        return items

    async def _tick_5min(self):
        """5-minute tick: Playwright 5min + Twitter.

        Both run concurrently via asyncio.gather. Each collector
        is independently exception-isolated AND timeout-protected.

        Combined tick ~25s, well under 300s.
        """
        sources = [
            s for s in self.sources.get('tier_2_playwright', [])
            if s.get('frequency_tier') != 'heartbeat'
        ]

        async def _fetch_playwright_5min():
            try:
                return await asyncio.wait_for(
                    self._run_playwright_5min(sources), timeout=120,
                )
            except asyncio.TimeoutError:
                logger.warning("PW 5min timed out after 120s")
                return []
            except Exception as e:
                logger.warning("PW 5min failed: %s", e)
                return []

        async def _fetch_twitter():
            try:
                return await asyncio.wait_for(
                    self.twitter_fetcher.fetch_all(), timeout=60,
                )
            except asyncio.TimeoutError:
                logger.warning("Twitter fetch timed out after 60s")
                return []
            except Exception as e:
                logger.warning("Twitter fetch failed: %s", e)
                return []

        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    _fetch_playwright_5min(),
                    _fetch_twitter(),
                    return_exceptions=True,
                ),
                timeout=150,
            )
        except asyncio.TimeoutError:
            logger.error(
                "5min gather timed out after 150s — one or more fetchers hung"
            )
            return

        items = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("5min collector failed: %s", result)
            elif result:
                items.extend(result)

        if items:
            await self._notify_callbacks(items)

    async def _run_playwright_5min(self, sources):
        """Run Playwright 5min fetches sequentially (shared browser)."""
        items = []
        for source in sources:
            try:
                src_items = await self.playwright_fetcher.fetch_source(source)
                items.extend(src_items)
            except Exception as e:
                logger.warning("PW 5min %s failed: %s",
                               source.get('name', '?'), e)
        return items

    async def _tick_15min(self):
        """15-minute tier — now a no-op.

        All content sources moved to _tick_5min() on 2026-07-07.
        This slot is reserved for future low-frequency sources.
        """

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

        # Startup Twitter browser (Playwright + auth cookie)
        try:
            await self.twitter_fetcher.startup()
        except Exception as e:
            logger.warning(f"Twitter fetcher startup failed (non-fatal): {e}")

        while self._running:
            now = time.monotonic()

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
        await self.web_scraper.shutdown()
        await self.finnhub_fetcher.close()
        await self.futu_news_fetcher.close()
