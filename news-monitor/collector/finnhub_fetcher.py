"""Finnhub company news fetcher — per-ticker news API.

Finnhub free tier: 60 requests/min.  With 21 watchlist tickers polled every
5 minutes, we use 21/60 = 35% of the rate limit, leaving ample headroom.

API docs: https://finnhub.io/docs/api/company-news
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List

import aiohttp

from storage.models import NewsItem

logger = logging.getLogger(__name__)

BASE_URL = "https://finnhub.io/api/v1"

# Number of articles to return per ticker (free tier returns up to ~100)
MAX_ARTICLES_PER_TICKER = 5

# Lookback window for news — 24h is enough to catch everything without
# stacking up hundreds of articles.
LOOKBACK_HOURS = 24


class FinnhubNewsFetcher:
    """Fetch company-specific news from Finnhub for each watchlist ticker.

    Unlike RSS/Twitter which are "broad feed then filter", Finnhub allows
    targeted per-ticker queries.  This fills the gap for mid-cap watchlist
    stocks (NBIS, OKLO, RKLB, ASTS, etc.) that don't appear on macro-focused
    Twitter feeds or major RSS headlines.
    """

    def __init__(self, watchlist: List[str], api_key: str = ""):
        self._watchlist = watchlist
        self._api_key = api_key or os.environ.get("FINNHUB_API_KEY", "")
        self._session: aiohttp.ClientSession | None = None
        # Track last seen article IDs per ticker to avoid re-pushing old news.
        self._seen_ids: set[int] = set()
        self._max_seen = 5000

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def fetch_ticker_news(self, ticker: str) -> List[NewsItem]:
        """Fetch recent news for a single ticker."""
        if not self._api_key:
            return []

        from_date = (datetime.now() - timedelta(hours=LOOKBACK_HOURS)).strftime(
            "%Y-%m-%d"
        )
        to_date = datetime.now().strftime("%Y-%m-%d")

        url = (
            f"{BASE_URL}/company-news"
            f"?symbol={ticker}"
            f"&from={from_date}&to={to_date}"
            f"&token={self._api_key}"
        )

        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Finnhub: %s returned %d — %s",
                        ticker, resp.status, await resp.text()[:100],
                    )
                    return []
                data = await resp.json()
        except asyncio.TimeoutError:
            logger.warning("Finnhub: %s timed out", ticker)
            return []
        except Exception as e:
            logger.error("Finnhub: %s error — %s", ticker, e)
            return []

        if not isinstance(data, list):
            logger.warning("Finnhub: %s returned non-list — %s", ticker, type(data))
            return []

        items = []
        for article in data[:MAX_ARTICLES_PER_TICKER]:
            article_id = article.get("id", 0)
            if article_id and article_id in self._seen_ids:
                continue

            headline = article.get("headline", "")
            if not headline:
                continue

            published_ts = article.get("datetime", 0)
            published_at = (
                datetime.fromtimestamp(published_ts) if published_ts else datetime.now()
            )

            item = NewsItem(
                title=headline,
                url=article.get("url", ""),
                source=f"Finnhub ({article.get('source', 'unknown')})",
                content_snippet=(article.get("summary", "") or "")[:800],
                published_at=published_at,
                tickers_found=ticker,
            )

            if article_id:
                self._seen_ids.add(article_id)

            items.append(item)

        # Keep _seen_ids bounded
        if len(self._seen_ids) > self._max_seen:
            self._seen_ids = set(list(self._seen_ids)[-self._max_seen // 2 :])

        if items:
            logger.info("Finnhub: %s — %d new article(s)", ticker, len(items))

        return items

    async def fetch_all(self) -> List[NewsItem]:
        """Fetch news for all watchlist tickers concurrently.

        Each ticker is one API call.  With 21 tickers and 60 req/min limit,
        this completes in 1-2 seconds wall-clock time.
        """
        if not self._api_key:
            logger.warning("Finnhub: no API key configured — skipping")
            return []

        sem = asyncio.Semaphore(5)  # limit concurrency to avoid bursts

        async def _fetch_one(ticker: str) -> List[NewsItem]:
            async with sem:
                return await self.fetch_ticker_news(ticker)

        tasks = [_fetch_one(t) for t in self._watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items: List[NewsItem] = []
        for ticker, result in zip(self._watchlist, results):
            if isinstance(result, Exception):
                logger.error(
                    "Finnhub: %s fetch failed — %s", ticker, result,
                )
            elif isinstance(result, list):
                items.extend(result)

        if items:
            logger.info(
                "Finnhub total: %d article(s) across %d ticker(s)",
                len(items), len(self._watchlist),
            )

        return items

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
