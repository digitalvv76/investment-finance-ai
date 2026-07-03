"""Twitter/X feed fetcher via Playwright browser with auth cookie.

Twitter/X in 2026 requires authentication for all content access.  This
fetcher uses a headless Chromium browser with an auth_token cookie (from a
logged-in X account) to load profile pages and extract tweet text.

Requirements:
  - TWITTER_AUTH_TOKEN env var (or auth_token in sources.yaml -> twitter)
  - A proxy (e.g. Clash) if running from mainland China
  - Playwright with Chromium

Architecture:
  - One browser instance is launched at startup and reused across fetches.
  - Each fetch creates a new context with the auth cookie, loads all
    configured accounts sequentially, and closes the context.
  - Tweets are extracted via DOM selectors, not API calls.
"""

import asyncio
import hashlib
import logging
import os
from datetime import datetime
from typing import List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from storage.models import NewsItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def _generate_ct0(auth_token: str) -> str:
    """Generate the CSRF token (ct0) from auth_token.

    X uses a SHA-256 hash of the auth_token, truncated to 32 hex chars.
    """
    return hashlib.sha256(auth_token.encode()).hexdigest()[:32]


def _load_auth_token(config: dict) -> str:
    """Resolve auth_token from config dict or TWITTER_AUTH_TOKEN env var."""
    token = (config or {}).get("auth_token", "")
    if not token:
        token = os.environ.get("TWITTER_AUTH_TOKEN", "")
    return token.strip()


# ---------------------------------------------------------------------------
# TwitterFetcher
# ---------------------------------------------------------------------------

class TwitterFetcher:
    """Fetch tweets via Playwright browser using an auth cookie.

    Config dict (from sources.yaml -> twitter):
        accounts:
          - "@elerianm"
          - "@Newsquawk"
        auth_token: "xxx"            # or set TWITTER_AUTH_TOKEN env var
        proxy: "http://127.0.0.1:7897"  # optional, also reads HTTPS_PROXY
        max_items_per_account: 5
        request_delay_seconds: 3.0
    """

    def __init__(self, config: dict = None):
        config = config or {}
        self.accounts: List[str] = config.get("accounts", [])
        self.auth_token: str = _load_auth_token(config)
        self.proxy: str = (
            config.get("proxy", "")
            or os.environ.get("HTTPS_PROXY", "")
            or os.environ.get("https_proxy", "")
        ).replace("socks5h://", "http://")  # Playwright prefers http proxy
        self.max_items: int = config.get("max_items_per_account", 5)
        self.delay: float = config.get("request_delay_seconds", 3.0)

        # Playwright internals
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._ct0: str = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def startup(self):
        """Launch headless Chromium (once, reused across fetches)."""
        if self._browser:
            return

        self._playwright = await async_playwright().start()
        launch_kwargs = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if self.proxy:
            launch_kwargs["proxy"] = {"server": self.proxy}
            logger.info("Twitter: using proxy %s", self.proxy)

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._ct0 = _generate_ct0(self.auth_token) if self.auth_token else ""
        logger.info("Twitter: browser launched (auth=%s)", "yes" if self.auth_token else "no")

    async def shutdown(self):
        """Close browser and stop Playwright."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Twitter: browser shut down")

    async def close(self):
        """Public alias for shutdown."""
        await self.shutdown()

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    async def _create_context(self) -> BrowserContext:
        """Create a new browser context with the auth cookie set."""
        context = await self._browser.new_context()
        if self.auth_token and self._ct0:
            await context.add_cookies([
                {
                    "name": "auth_token",
                    "value": self.auth_token,
                    "domain": ".x.com",
                    "path": "/",
                },
                {
                    "name": "ct0",
                    "value": self._ct0,
                    "domain": ".x.com",
                    "path": "/",
                },
            ])
        return context

    async def fetch_account(self, account: str) -> List[NewsItem]:
        """Fetch recent tweets for a single Twitter/X account.

        Loads the profile page (x.com/{username}) in a headless browser,
        waits for React to render, then extracts tweet text and links.
        """
        items: List[NewsItem] = []
        username = account.strip().lstrip("@")
        if not username or not self._browser:
            return items
        if not self.auth_token:
            logger.warning("Twitter: no auth_token configured — skipping")
            return items

        context = await self._create_context()
        page: Page = await context.new_page()

        try:
            url = f"https://x.com/{username}"
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            # Let React render the timeline
            await page.wait_for_timeout(4000)

            # Check if the page actually loaded tweets (not login wall)
            tweet_elements = await page.query_selector_all(
                '[data-testid="tweetText"]'
            )
            if not tweet_elements:
                # Might be rate-limited or the page structure changed
                body = await page.inner_text("body")
                if "Sign in" in body[:500]:
                    logger.warning(
                        "Twitter @%s: auth cookie rejected (login wall)", username
                    )
                    return items

            for elem in tweet_elements[: self.max_items]:
                try:
                    text = (await elem.inner_text()).strip()
                    if not text or len(text) < 10:
                        continue

                    # Try to get the tweet's permalink
                    link = url
                    try:
                        # Walk up to the article element and find the time link
                        article = await elem.evaluate_handle(
                            """el => {
                                let a = el.closest('article');
                                if (!a) return '';
                                let timeLink = a.querySelector('a[href*=\"/status/\"]');
                                return timeLink ? timeLink.href : '';
                            }"""
                        )
                        article_link = await article.json_value()
                        if article_link:
                            link = article_link
                    except Exception:
                        pass

                    items.append(NewsItem(
                        title=text[:200] if len(text) <= 200 else text[:197] + "...",
                        url=link,
                        source=f"Twitter @{username}",
                        content_snippet=text[:500],
                        captured_at=datetime.now(),
                    ))
                except Exception as e:
                    logger.debug("Twitter @%s: element error — %s", username, e)
                    continue

            if items:
                logger.info("Twitter @%s: %d tweets fetched", username, len(items))

        except asyncio.TimeoutError:
            logger.warning("Twitter @%s: page load timeout", username)
        except Exception as e:
            logger.error("Twitter @%s: %s", username, e)
        finally:
            await context.close()

        return items

    async def fetch_all(self) -> List[NewsItem]:
        """Fetch tweets from all configured accounts sequentially.

        Shares one browser instance across all accounts; creates a fresh
        context per account for cookie isolation.
        """
        if not self.accounts:
            return []

        # Lazy-start the browser on first fetch
        if not self._browser:
            try:
                await self.startup()
            except Exception as e:
                logger.error("Twitter: browser startup failed — %s", e)
                return []

        all_items: List[NewsItem] = []
        for account in self.accounts:
            try:
                items = await self.fetch_account(account)
                all_items.extend(items)
                if self.delay > 0:
                    await asyncio.sleep(self.delay)
            except Exception as e:
                logger.error("Twitter account %s: %s", account, e)

        logger.info(
            "Twitter total: %d tweets from %d accounts",
            len(all_items),
            len(self.accounts),
        )
        return all_items
