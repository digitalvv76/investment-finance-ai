"""Web scraper — Playwright-based fast homepage scraping.

Scrapes three sites for real-time headlines, bypassing RSS/API cache delays:
  - 华尔街见闻 live (wallstreetcn.com/live) — Chinese financial breaking news
  - CNBC (cnbc.com) — US market headlines
  - MarketWatch (marketwatch.com) — US market headlines

All three share one browser instance. Each scrape completes in ~5-8s per page
(domcontentloaded only, no images). Total wall-clock: ~15s concurrent.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import List

from storage.models import NewsItem

logger = logging.getLogger(__name__)

# HTML tag stripper
_HTML_RE = re.compile(r"<[^>]+>")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Per-source config
SCRAPE_TIMEOUT = 15_000  # ms per page
MAX_ITEMS_PER_SOURCE = 15


class WebScraper:
    """Scrape news homepages using a shared Playwright browser instance."""

    def __init__(self) -> None:
        self._browser = None
        self._playwright = None

    async def startup(self) -> None:
        """Launch headless Chromium (shared with Twitter fetcher if co-located)."""
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-gpu", "--disable-setuid-sandbox"],
            )
            logger.info("WebScraper: browser launched")
        except ImportError:
            logger.error("WebScraper: playwright not installed")
        except Exception as e:
            logger.error("WebScraper: browser launch failed: %s", e)

    async def shutdown(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("WebScraper: browser closed")

    async def fetch_all(self) -> List[NewsItem]:
        """Scrape all configured sites concurrently. Returns deduplicated items."""
        if not self._browser:
            logger.warning("WebScraper: browser not available, skipping")
            return []

        tasks = [
            self._scrape_wallstreetcn(),
            self._scrape_cnbc(),
            self._scrape_marketwatch(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: List[NewsItem] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("WebScraper: site %d failed: %s", i, result)
            elif result:
                all_items.extend(result)

        return all_items

    # ------------------------------------------------------------------
    # 华尔街见闻 live
    # ------------------------------------------------------------------

    async def _scrape_wallstreetcn(self) -> List[NewsItem]:
        """Scrape wallstreetcn.com/live — real-time Chinese financial feed.

        The live page loads items via JS; we extract them from the DOM
        after waiting for the feed container to render.
        """
        items: List[NewsItem] = []
        page = None
        try:
            page = await self._browser.new_page()
            await page.set_extra_http_headers({"User-Agent": UA})
            await page.goto("https://wallstreetcn.com/live/global",
                           wait_until="domcontentloaded",
                           timeout=SCRAPE_TIMEOUT)
            # Wait for live feed items to render
            await page.wait_for_selector("[class*='live-item'], [class*='article'], .live-content",
                                         timeout=10_000)
            await asyncio.sleep(1)  # let JS hydration finish

            headlines = await page.evaluate("""() => {
                const items = [];
                // WallstreetCN live items — try multiple selectors
                const selectors = [
                    '[class*="live-item"]', '[class*="LiveCard"]',
                    'article', '[class*="article-item"]'
                ];
                let elements = [];
                for (const sel of selectors) {
                    elements = document.querySelectorAll(sel);
                    if (elements.length > 5) break;
                }
                for (const el of elements) {
                    const title = el.textContent?.trim()?.substring(0, 200) || '';
                    const link = el.querySelector('a')?.href || '';
                    const timeEl = el.querySelector('time, [class*="time"]');
                    const time = timeEl?.textContent?.trim() || '';
                    if (title.length > 10) {
                        items.push({title, url: link, time});
                    }
                }
                return items.slice(0, 15);
            }""")

            for h in headlines:
                title = _HTML_RE.sub("", h.get("title", "")).strip()
                if not title or len(title) < 10:
                    continue
                items.append(NewsItem(
                    title=title,
                    url=h.get("url", ""),
                    source="华尔街见闻",
                    content_snippet=title,
                ))

            logger.info("WebScraper: WallstreetCN → %d items", len(items))
        except Exception as e:
            logger.warning("WebScraper: WallstreetCN scrape failed: %s", e)
        finally:
            if page:
                await page.close()
        return items

    # ------------------------------------------------------------------
    # CNBC
    # ------------------------------------------------------------------

    async def _scrape_cnbc(self) -> List[NewsItem]:
        """Scrape cnbc.com homepage headlines."""
        items: List[NewsItem] = []
        page = None
        try:
            page = await self._browser.new_page()
            await page.set_extra_http_headers({"User-Agent": UA})
            await page.goto("https://www.cnbc.com/",
                           wait_until="domcontentloaded",
                           timeout=SCRAPE_TIMEOUT)
            await page.wait_for_selector("a[href*='/202']", timeout=8_000)
            await asyncio.sleep(0.5)

            headlines = await page.evaluate("""() => {
                const items = [];
                const links = document.querySelectorAll(
                    'a[href*="/2026/"], a[href*="/2025/"], .Card-title a, .FeaturedCard-title a'
                );
                const seen = new Set();
                for (const a of links) {
                    const title = a.textContent?.trim() || '';
                    const url = a.href || '';
                    if (title.length > 15 && !seen.has(url) && url.includes('cnbc.com')) {
                        seen.add(url);
                        items.push({title: title.substring(0, 200), url});
                    }
                }
                return items.slice(0, 15);
            }""")

            for h in headlines:
                items.append(NewsItem(
                    title=h["title"],
                    url=h["url"],
                    source="CNBC",
                    content_snippet=h["title"],
                ))

            logger.info("WebScraper: CNBC → %d items", len(items))
        except Exception as e:
            logger.warning("WebScraper: CNBC scrape failed: %s", e)
        finally:
            if page:
                await page.close()
        return items

    # ------------------------------------------------------------------
    # MarketWatch
    # ------------------------------------------------------------------

    async def _scrape_marketwatch(self) -> List[NewsItem]:
        """Scrape marketwatch.com homepage headlines."""
        items: List[NewsItem] = []
        page = None
        try:
            page = await self._browser.new_page()
            await page.set_extra_http_headers({"User-Agent": UA})
            await page.goto("https://www.marketwatch.com/",
                           wait_until="domcontentloaded",
                           timeout=SCRAPE_TIMEOUT)
            await page.wait_for_selector("a[href*='/story/']", timeout=8_000)
            await asyncio.sleep(0.5)

            headlines = await page.evaluate("""() => {
                const items = [];
                const links = document.querySelectorAll(
                    'a[href*="/story/"], .article__headline a, h3 a'
                );
                const seen = new Set();
                for (const a of links) {
                    const title = a.textContent?.trim() || '';
                    const url = a.href || '';
                    if (title.length > 15 && !seen.has(url)) {
                        seen.add(url);
                        items.push({title: title.substring(0, 200), url});
                    }
                }
                return items.slice(0, 15);
            }""")

            for h in headlines:
                items.append(NewsItem(
                    title=h["title"],
                    url=h["url"],
                    source="MarketWatch",
                    content_snippet=h["title"],
                ))

            logger.info("WebScraper: MarketWatch → %d items", len(items))
        except Exception as e:
            logger.warning("WebScraper: MarketWatch scrape failed: %s", e)
        finally:
            if page:
                await page.close()
        return items
