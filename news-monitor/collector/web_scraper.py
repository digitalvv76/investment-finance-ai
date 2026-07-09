"""Web scraper — Playwright-based fast homepage scraping.

Scrapes four sites for real-time headlines, bypassing RSS/API cache delays:
  - 新浪财经 live (finance.sina.com.cn/7x24) — Chinese financial breaking news
  - 华尔街见闻 live (wallstreetcn.com/live) — Chinese financial breaking news
  - CNBC (cnbc.com) — US market headlines
  - MarketWatch (marketwatch.com) — US market headlines

Each scrape first tries CSS/JS extraction. If a source fails 3 consecutive times,
it falls back to VLM visual extraction (Claude Haiku, ~$0.005/call) with a 1-hour
cool-down before retrying CSS.

All sources share one browser instance.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

from storage.models import NewsItem

logger = logging.getLogger(__name__)

# HTML tag stripper
_HTML_RE = re.compile(r"<[^>]+>")

# Path to VLM extraction prompt
_VLM_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config", "prompts", "vlm_extract.txt",
)

# Per-source CSS extraction thresholds — fewer items than this = VLM fallback
_MIN_ITEMS_CSS = {
    "新浪财经": 3,
    "华尔街见闻": 3,
    "CNBC": 5,
    "MarketWatch": 5,
}

# VLM cool-down: after VLM triggers, wait this many seconds before retrying CSS
_VLM_COOLDOWN_SECONDS = 3600  # 1 hour

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Per-source config
SCRAPE_TIMEOUT = 15_000  # ms per page
MAX_ITEMS_PER_SOURCE = 15


class WebScraper:
    """Scrape news homepages using a shared Playwright browser instance.

    Falls back to VLM (Claude Haiku) when CSS/JS extraction returns too few
    items on a given source, with a 1-hour cool-down before retrying CSS.
    """

    # Browser restart every 2 hours to prevent Chrome process leak accumulation
    _BROWSER_RESTART_SECONDS = 7200  # 2 hours

    def __init__(self) -> None:
        self._browser = None
        self._playwright = None
        self._browser_started_at: float = 0.0  # monotonic timestamp

        # VLM fallback state — keyed by source name
        # Each entry: {"failures": int, "vlm_until": float (monotonic timestamp)}
        self._vlm_state: Dict[str, dict] = {}
        self._vlm_prompt: Optional[str] = None
        self._vlm_client: Optional[object] = None  # anthropic.Anthropic

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
            self._browser_started_at = time.monotonic()
            logger.info("WebScraper: browser launched")
        except ImportError:
            logger.error("WebScraper: playwright not installed")
        except Exception as e:
            logger.error("WebScraper: browser launch failed: %s", e)

    async def _restart_browser_if_stale(self) -> None:
        """Restart Chromium every _BROWSER_RESTART_SECONDS to prevent process leak."""
        if time.monotonic() - self._browser_started_at < self._BROWSER_RESTART_SECONDS:
            return
        logger.info("WebScraper: periodic browser restart (2h cycle)")
        try:
            if self._browser:
                await self._browser.close()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-gpu", "--disable-setuid-sandbox"],
            )
            self._browser_started_at = time.monotonic()
            logger.info("WebScraper: browser restarted successfully")
        except Exception as e:
            logger.error("WebScraper: browser restart failed: %s", e)

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

        await self._restart_browser_if_stale()

        tasks = [
            self._scrape_sina(),
            self._scrape_wallstreetcn(),
            self._scrape_cnbc(),
            # MarketWatch homepage is behind DataDome (HTTP 401 to headless
            # Chromium → 0 links). Covered by the mw_topstories RSS feed instead.
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
    # VLM fallback — Claude Haiku visual extraction
    # ------------------------------------------------------------------

    def _load_vlm_prompt(self) -> str:
        """Lazy-load the VLM system prompt from file."""
        if self._vlm_prompt is None:
            try:
                self._vlm_prompt = open(_VLM_PROMPT_PATH, encoding="utf-8").read().strip()
            except FileNotFoundError:
                logger.error("WebScraper: vlm_extract.txt not found at %s", _VLM_PROMPT_PATH)
                self._vlm_prompt = ""
        return self._vlm_prompt

    def _get_vlm_client(self) -> Optional[object]:
        """Lazy-init Anthropic client. Returns None if ANTHROPIC_API_KEY not set."""
        if self._vlm_client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                logger.warning("WebScraper: ANTHROPIC_API_KEY not set, VLM disabled")
                return None
            try:
                import anthropic
                self._vlm_client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                logger.error("WebScraper: anthropic SDK not installed")
                return None
            except Exception as e:
                logger.error("WebScraper: anthropic client init failed: %s", e)
                return None
        return self._vlm_client

    async def _vlm_extract(self, page, source_name: str) -> List[dict]:
        """Take a screenshot and send to Claude Haiku for headline extraction.

        Returns list of {title, url, snippet} dicts. On any failure, returns [].
        """
        client = self._get_vlm_client()
        if client is None:
            return []

        prompt = self._load_vlm_prompt()
        if not prompt:
            return []

        try:
            # Screenshot in memory — no disk write
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            if not screenshot_bytes:
                logger.warning("WebScraper: VLM screenshot empty for %s", source_name)
                return []

            img_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
            logger.info(
                "WebScraper: VLM extracting %s — screenshot %d bytes",
                source_name, len(screenshot_bytes),
            )

            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.messages.create,
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    system=prompt,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": f"Extract all visible news headlines from this screenshot of {source_name}.",
                            },
                        ],
                    }],
                ),
                timeout=15.0,
            )

            if resp.content and len(resp.content) > 0:
                raw = resp.content[0].text.strip()
                # Strip markdown fences if present
                raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
                raw = re.sub(r"\n?```\s*$", "", raw)
                headlines = json.loads(raw)
                if isinstance(headlines, list):
                    logger.info(
                        "WebScraper: VLM → %d headlines for %s",
                        len(headlines), source_name,
                    )
                    return headlines

            logger.warning("WebScraper: VLM empty/unexpected response for %s", source_name)
        except asyncio.TimeoutError:
            logger.error("WebScraper: VLM timeout for %s (15s)", source_name)
        except json.JSONDecodeError as e:
            logger.error("WebScraper: VLM JSON parse failed for %s: %s", source_name, e)
        except Exception as e:
            logger.error("WebScraper: VLM extract failed for %s: %s", source_name, e)

        return []

    def _should_use_vlm(self, source_name: str, css_count: int) -> bool:
        """Decide whether VLM fallback should trigger based on fail history.

        Returns True if CSS has failed 3+ consecutive times and we haven't
        exhausted the 1-hour VLM cool-down window (after which we retry CSS).
        """
        state = self._vlm_state.get(source_name, {"failures": 0, "vlm_until": 0.0})

        if css_count >= _MIN_ITEMS_CSS.get(source_name, 3):
            # CSS succeeded — reset counter
            state["failures"] = 0
            state["vlm_until"] = 0.0
            self._vlm_state[source_name] = state
            return False

        # CSS returned too few items
        state["failures"] = state.get("failures", 0) + 1
        now = time.monotonic()

        if state["failures"] < 3:
            self._vlm_state[source_name] = state
            return False

        # 3+ failures — check cool-down
        if now < state.get("vlm_until", 0.0):
            # Still in VLM window
            return True

        # Trigger VLM and set cool-down
        state["vlm_until"] = now + _VLM_COOLDOWN_SECONDS
        self._vlm_state[source_name] = state
        logger.info(
            "WebScraper: %s CSS failed %d times, switching to VLM (cool-down %ds)",
            source_name, state["failures"], _VLM_COOLDOWN_SECONDS,
        )
        return True

    def _vlm_items_to_news(self, headlines: List[dict],
                           source_name: str) -> List[NewsItem]:
        """Convert VLM {title, url, snippet} dicts to NewsItem list."""
        items: List[NewsItem] = []
        for h in headlines:
            title = (h.get("title") or "").strip()
            if not title:
                continue
            title = _HTML_RE.sub("", title)
            url = (h.get("url") or "").strip()
            snippet = (h.get("snippet") or title).strip()
            items.append(NewsItem(
                title=title[:200],
                url=url,
                source=source_name,
                content_snippet=snippet[:300],
            ))
        return items

    # ------------------------------------------------------------------
    # 新浪财经 — bypasses API 403 via browser fingerprint
    # ------------------------------------------------------------------

    async def _scrape_sina(self) -> List[NewsItem]:
        """Scrape Sina finance live page (not API) via Playwright.

        The JSON API returns 403 from ECS. The live webpage at
        finance.sina.com.cn/7x24 uses the same data but is served
        as HTML — browser fingerprint bypasses the API block.

        New DOM (2026-07): .seaio_list > div items, each contains
        <div>time</div>, <a>title+link</a>, <div.btn-view>reads, <div.btn-cmnt>comments.
        """
        items: List[NewsItem] = []
        page = None
        try:
            page = await self._browser.new_page()
            await page.set_extra_http_headers({"User-Agent": UA})
            await page.goto("https://finance.sina.com.cn/7x24/",
                           wait_until="domcontentloaded",
                           timeout=SCRAPE_TIMEOUT)
            # Wait for .seaio_list container to appear
            try:
                await page.wait_for_selector(".seaio_list",
                                             state="attached",
                                             timeout=10_000)
            except Exception:
                pass
            await asyncio.sleep(2)  # JS hydration

            headlines = await page.evaluate("""() => {
                const items = [];
                const container = document.querySelector('.seaio_list');
                if (!container) return items;
                // Each child div is a news item with a time div and an <a> link
                const children = container.children;
                for (const el of children) {
                    const link = el.querySelector('a[href]');
                    if (!link) continue;
                    const title = (link.textContent || '').trim();
                    const href = link.href || '';
                    if (title.length > 10 && href) {
                        items.push({title: title.substring(0, 200), url: href});
                    }
                }
                return items.slice(0, 20);
            }""")

            for h in headlines:
                title = _HTML_RE.sub("", h.get("title", "")).strip()
                if not title or len(title) < 12:
                    continue
                items.append(NewsItem(
                    title=title,
                    url=h.get("url", ""),
                    source="新浪财经",
                    content_snippet=title,
                ))

            logger.info("WebScraper: Sina → %d items", len(items))

            # VLM fallback if CSS returned too few
            if self._should_use_vlm("新浪财经", len(items)):
                vlm_headlines = await self._vlm_extract(page, "新浪财经")
                if vlm_headlines:
                    items = self._vlm_items_to_news(vlm_headlines, "新浪财经")

        except Exception as e:
            logger.warning("WebScraper: Sina live page scrape failed: %s", e)
        finally:
            if page:
                await page.close()
        return items

    # ------------------------------------------------------------------
    # 华尔街见闻 live
    # ------------------------------------------------------------------

    async def _scrape_wallstreetcn(self) -> List[NewsItem]:
        """Scrape wallstreetcn.com/live — real-time Chinese financial feed.

        The live page is a JS SPA; items appear in .live-item containers
        with .live-item_title and .live-item_html children.
        Waits for .livenews-main container then extracts all .live-item.
        """
        items: List[NewsItem] = []
        page = None
        try:
            page = await self._browser.new_page()
            await page.set_extra_http_headers({"User-Agent": UA})
            await page.goto("https://wallstreetcn.com/live/global",
                           wait_until="domcontentloaded",
                           timeout=SCRAPE_TIMEOUT)
            # Wait for SPA container to appear (attached, not necessarily visible)
            try:
                await page.wait_for_selector(".livenews-main",
                                             state="attached",
                                             timeout=10_000)
            except Exception:
                # Fallback: wait for any .live-item to be attached
                await page.wait_for_selector(".live-item",
                                             state="attached",
                                             timeout=5_000)
            await asyncio.sleep(2)  # let SPA hydrate

            headlines = await page.evaluate("""() => {
                const items = [];
                const elements = document.querySelectorAll('.live-item');
                for (const el of elements) {
                    const titleEl = el.querySelector('.live-item_title');
                    const contentEl = el.querySelector('.live-item_html');
                    const title = (titleEl?.textContent || '').trim();
                    const content = (contentEl?.textContent || '').trim();
                    const linkEl = el.querySelector('a[href]');
                    const url = linkEl?.href || '';
                    // Use title if available, otherwise first 80 chars of content
                    const combined = title || content?.substring(0, 80) || '';
                    if (combined.length > 10) {
                        items.push({
                            title: title || content?.substring(0, 200) || '',
                            snippet: content || title || '',
                            url: url
                        });
                    }
                }
                return items.slice(0, 15);
            }""")

            for h in headlines:
                title = _HTML_RE.sub("", h.get("title", "")).strip()
                if not title or len(title) < 10:
                    continue
                snippet = _HTML_RE.sub("", h.get("snippet", title)).strip()
                items.append(NewsItem(
                    title=title,
                    url=h.get("url", ""),
                    source="华尔街见闻",
                    content_snippet=snippet[:300],
                ))

            logger.info("WebScraper: WallstreetCN → %d items", len(items))

            # VLM fallback if CSS returned too few
            if self._should_use_vlm("华尔街见闻", len(items)):
                vlm_headlines = await self._vlm_extract(page, "华尔街见闻")
                if vlm_headlines:
                    items = self._vlm_items_to_news(vlm_headlines, "华尔街见闻")

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
            # Let JS render; CNBC is SSR-heavy and loads fast
            await asyncio.sleep(2)

            headlines = await page.evaluate("""() => {
                const items = [];
                const seen = new Set();
                // Broad: any link on the page that looks like an article
                const links = document.querySelectorAll('a[href]');
                for (const a of links) {
                    const href = a.href || '';
                    const title = (a.textContent || '').trim();
                    // CNBC article URLs contain year slug
                    if (title.length > 20 && !seen.has(href) && href.match(/cnbc\\.com\\/\\d{4}\\/\\d{2}\\/|cnbc\\.com\\/[a-z-]+\\//)) {
                        seen.add(href);
                        items.push({title: title.substring(0, 200), url: href});
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

            # VLM fallback if CSS returned too few
            if self._should_use_vlm("CNBC", len(items)):
                vlm_headlines = await self._vlm_extract(page, "CNBC")
                if vlm_headlines:
                    items = self._vlm_items_to_news(vlm_headlines, "CNBC")

        except Exception as e:
            logger.warning("WebScraper: CNBC scrape failed: %s", e)
        finally:
            if page:
                await page.close()
        return items

    # ------------------------------------------------------------------
    # MarketWatch
    # ------------------------------------------------------------------
    # Homepage scraper retired 2026-07-09: marketwatch.com is protected by
    # DataDome, which serves HTTP 401 + a JS-challenge shell (zero <a> tags)
    # to headless Chromium. Top stories are ingested via the Dow Jones RSS
    # feed (config/sources.yaml → mw_topstories) instead. See the Bloomberg
    # note in sources.yaml for the same anti-bot precedent.
