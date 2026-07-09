"""Playwright-based browser fetcher for Tier 2 sources.

Scrapes Bloomberg, CNBC Live Blog, ZeroHedge — sources without RSS feeds —
using headless Chromium to extract headlines and links from rendered pages.
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from playwright.async_api import async_playwright, Browser, Page

from storage.models import NewsItem

logger = logging.getLogger(__name__)

HEADLESS_TIMEOUT = 15000  # 15s
PAGE_TIMEOUT = 20000      # 20s


class PlaywrightFetcher:
    """Fetch news headlines from JavaScript-rendered Tier 2 sources.

    Each source config dict must have:
        name      — human-readable source name
        url       — target page URL
        selectors — dict with 'headline' (required), 'link' (optional),
                    'breaking' (optional)
    """

    def __init__(self, sources: list):
        self.sources = sources
        self._playwright = None
        self._browser: Optional[Browser] = None

    async def startup(self):
        """Launch headless Chromium browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        logger.info("Playwright browser launched")

    async def shutdown(self):
        """Close browser and stop Playwright gracefully."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Playwright shut down")

    async def fetch_source(self, source: dict) -> List[NewsItem]:
        """Scrape a single source using Playwright.

        Args:
            source: Tier 2 source config dict with name, url, selectors.

        Returns:
            List of NewsItem objects extracted from the page.
        """
        name = source['name']
        url = source['url']
        selectors = source.get('selectors', {})
        items: List[NewsItem] = []
        page = None

        if not self._browser:
            await self.startup()

        try:
            page = await self._browser.new_page()
            await page.set_extra_http_headers({
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                )
            })

            await page.goto(url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT)
            await page.wait_for_timeout(2000)  # Let dynamic content render

            # Extract headlines
            headline_sel = selectors.get('headline', 'h1, h2, h3')
            link_sel = selectors.get('link', 'a')
            breaking_sel = selectors.get('breaking', '')

            # Find all headline elements
            headline_elements = await page.query_selector_all(headline_sel)

            for elem in headline_elements[:30]:  # Max 30 headlines per source
                try:
                    title = (await elem.inner_text()).strip()
                    if not title or len(title) < 10:
                        continue

                    # Try to get the link
                    link = ''
                    link_elem = await elem.query_selector('a[href]') or elem
                    href = await link_elem.get_attribute('href')
                    if href:
                        if href.startswith('http'):
                            link = href
                        elif href.startswith('/'):
                            link = f"{url.rstrip('/')}{href}"
                        else:
                            link = f"{url.rstrip('/')}/{href}"

                    # Check if breaking news marker
                    is_breaking = False
                    if breaking_sel:
                        try:
                            breaking_elem = await elem.query_selector(breaking_sel)
                            is_breaking = breaking_elem is not None
                        except Exception:
                            pass

                    items.append(NewsItem(
                        title=title,
                        url=link or url,
                        source=name,
                        is_breaking=is_breaking,
                        captured_at=datetime.now(),
                    ))
                except Exception as e:
                    logger.debug(f"Playwright {name}: element extraction error — {e}")
                    continue

            logger.info(f"Playwright {name}: {len(items)} headlines")

        except asyncio.TimeoutError:
            logger.warning(f"Playwright {name}: page load timeout")
        except Exception as e:
            logger.error(f"Playwright {name}: {e}")
        finally:
            if page:
                await page.close()

        return items

    async def fetch_all(self) -> List[NewsItem]:
        """Fetch all Playwright sources sequentially (to avoid browser overload).

        Returns:
            Combined list of NewsItem objects from all configured sources.
        """
        all_items: List[NewsItem] = []
        for source in self.sources:
            items = await self.fetch_source(source)
            all_items.extend(items)
        logger.info(
            f"Playwright total: {len(all_items)} items "
            f"from {len(self.sources)} sources"
        )
        return all_items
