"""API-based trigger fetcher for FRED economic calendar and SEC filings.

Provides standalone HTTP fallbacks when running outside Claude Code (where
MCP tools are unavailable). Each method tries the direct HTTP API first;
on failure, logs a warning and returns an empty list so the pipeline
degrades gracefully.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List

import aiohttp

from storage.models import NewsItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# High-impact FRED release names to flag
# ---------------------------------------------------------------------------
HIGH_IMPACT_RELEASES = {
    "gross domestic product": "GDP",
    "consumer price index": "CPI",
    "producer price index": "PPI",
    "unemployment rate": "Unemployment",
    "nonfarm payroll": "NFP",
    "federal funds": "FOMC",
    "fomc": "FOMC",
    "treasury constant maturity": "Treasury",
    "retail sales": "Retail",
    "industrial production": "Industry",
    "personal consumption expenditures": "PCE",
    "initial claims": "Jobless",
    "ism manufacturing": "ISM",
    "consumer sentiment": "Sentiment",
}

# SEC EDGAR RSS feed for recent 8-K filings
SEC_RSS_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&output=atom&count=20"
)


class APIFetcher:
    """Fetches economic event, SEC filing, and market news triggers.

    Uses direct HTTP calls as the primary path (standalone deployment),
    with graceful fallback to empty results on network/API errors.
    """

    def __init__(self, fred_api_key: str = "", av_api_key: str = "", watchlist: list = None):
        self.fred_api_key = fred_api_key or os.environ.get("FRED_API_KEY", "")
        self.av_api_key = av_api_key or os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        self.watchlist = watchlist or ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "NewsMonitor/1.0 (financial-news-bot)"},
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # FRED Economic Calendar
    # ------------------------------------------------------------------

    async def check_fred_calendar(self) -> List[NewsItem]:
        """Check FRED for recent high-impact economic releases.

        Calls the FRED releases API to find releases dated today or yesterday.
        Flags high-impact releases (GDP, CPI, Unemployment, FOMC, etc.).
        """
        if not self.fred_api_key:
            logger.debug("FRED_API_KEY not set — skipping FRED calendar check")
            return []

        items = []
        try:
            today = datetime.now()
            date_start = (today - timedelta(days=2)).strftime("%Y-%m-%d")
            date_end = today.strftime("%Y-%m-%d")

            session = await self._get_session()
            url = (
                f"https://api.stlouisfed.org/fred/releases/dates"
                f"?api_key={self.fred_api_key}"
                f"&realtime_start={date_start}"
                f"&realtime_end={date_end}"
                f"&file_type=json"
            )
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("FRED API returned %d", resp.status)
                    return []
                data = await resp.json()

            releases = data.get("release_dates", [])
            for rel in releases:
                name = rel.get("release_name", "")
                release_date = rel.get("date", "")
                matched = None
                for keyword, tag in HIGH_IMPACT_RELEASES.items():
                    if keyword in name.lower():
                        matched = tag
                        break
                if not matched:
                    continue

                items.append(NewsItem(
                    title=f"[{matched}] {name} — released {release_date}",
                    url=f"https://fred.stlouisfed.org/releases?rid={rel.get('release_id','')}",
                    source="FRED Economic Data",
                    content_snippet=f"FRED release: {name} ({release_date})",
                    macro_tags=matched,
                    priority_score=0.55,  # Economic releases are moderately important
                ))

            if items:
                logger.info("FRED: %d high-impact releases found", len(items))
        except Exception as e:
            logger.warning("FRED calendar fetch failed: %s", e)

        return items

    # ------------------------------------------------------------------
    # SEC EDGAR 8-K Filings
    # ------------------------------------------------------------------

    async def check_sec_filings(self) -> List[NewsItem]:
        """Check SEC EDGAR for recent 8-K filings from watchlist tickers.

        Parses the SEC EDGAR Atom feed for 8-K filings and filters to
        companies matching the watchlist.
        """
        items = []
        try:
            import xml.etree.ElementTree as ET

            session = await self._get_session()
            # SEC requires a descriptive User-Agent
            headers = {"User-Agent": "NewsMonitor/1.0 (contact@example.com)"}
            async with session.get(SEC_RSS_URL, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning("SEC EDGAR returned %d", resp.status)
                    return []
                feed_xml = await resp.text()

            # Parse Atom feed
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            root = ET.fromstring(feed_xml)
            entries = root.findall("atom:entry", ns)

            # Build ticker lookup map
            watch_upper = {t.upper() for t in self.watchlist}

            for entry in entries[:30]:
                title_el = entry.find("atom:title", ns)
                title = title_el.text if title_el is not None and title_el.text else ""
                if not title:
                    continue

                # Title format: "8-K - COMPANY NAME (CIK ...)"
                # Check if any watchlist ticker appears in the title
                title_upper = title.upper()
                matched_tickers = [t for t in watch_upper if t in title_upper]
                if not matched_tickers:
                    continue

                link_el = entry.find("atom:link", ns)
                url = link_el.get("href", "") if link_el is not None else ""
                updated_el = entry.find("atom:updated", ns)
                updated = updated_el.text if updated_el is not None else ""

                items.append(NewsItem(
                    title=f"SEC 8-K Filing: {title}",
                    url=url,
                    source="SEC EDGAR",
                    content_snippet=f"8-K filing for {','.join(matched_tickers)} — {updated}",
                    tickers_found=",".join(matched_tickers),
                    priority_score=0.45,
                ))

            if items:
                logger.info("SEC: %d watchlist 8-K filings found", len(items))
        except ImportError:
            logger.debug("xml.etree unavailable — SEC EDGAR parsing skipped")
        except Exception as e:
            logger.warning("SEC EDGAR fetch failed: %s", e)

        return items

    # ------------------------------------------------------------------
    # Alpha Vantage News
    # ------------------------------------------------------------------

    async def check_alpha_vantage_news(self) -> List[NewsItem]:
        """Check Alpha Vantage for recent news about watchlist tickers.

        Uses the NEWS_SENTIMENT endpoint (free tier: 5 calls/min, 25/day).
        Samples the top 3 tickers from the watchlist to stay within limits.
        """
        if not self.av_api_key:
            logger.debug("ALPHA_VANTAGE_API_KEY not set — skipping AV news")
            return []

        items = []
        # Rate-limit: check at most 2 tickers per 5-min tick
        sample_tickers = self.watchlist[:2]
        seen_urls = set()

        try:
            session = await self._get_session()
            for ticker in sample_tickers:
                url = (
                    f"https://www.alphavantage.co/query"
                    f"?function=NEWS_SENTIMENT"
                    f"&tickers={ticker}"
                    f"&limit=5"
                    f"&apikey={self.av_api_key}"
                )
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            logger.warning("Alpha Vantage returned %d for %s", resp.status, ticker)
                            continue
                        data = await resp.json()
                except Exception as e:
                    logger.warning("Alpha Vantage request failed for %s: %s", ticker, e)
                    continue

                # Alpha Vantage may return rate-limit or error messages
                if "feed" not in data:
                    note = data.get("Note", data.get("Information", ""))
                    if note:
                        logger.debug("Alpha Vantage note: %s", note[:80])
                    continue

                for article in data.get("feed", [])[:5]:
                    article_url = article.get("url", "")
                    if not article_url or article_url in seen_urls:
                        continue
                    seen_urls.add(article_url)

                    # Parse sentiment
                    overall = article.get("overall_sentiment_label", "").lower()
                    items.append(NewsItem(
                        title=article.get("title", ""),
                        url=article_url,
                        source=f"Alpha Vantage — {article.get('source', 'unknown')}",
                        content_snippet=article.get("summary", "")[:500],
                        tickers_found=ticker,
                        sentiment=overall if overall in ("bullish", "bearish") else "",
                        macro_tags="AlphaVantage",
                    ))
                # Small delay between ticker calls for rate limiting
                await asyncio.sleep(2)

            if items:
                logger.info("Alpha Vantage: %d news items fetched", len(items))
        except Exception as e:
            logger.warning("Alpha Vantage news fetch failed: %s", e)

        return items

    # ------------------------------------------------------------------
    # Bulk check
    # ------------------------------------------------------------------

    async def check_all(self) -> List[NewsItem]:
        """Run all API checks concurrently."""
        results = await asyncio.gather(
            self.check_fred_calendar(),
            self.check_sec_filings(),
            self.check_alpha_vantage_news(),
            return_exceptions=True,
        )

        all_items = []
        for i, result in enumerate(results):
            source = ["FRED", "SEC", "AlphaVantage"][i] if i < 3 else f"source{i}"
            if isinstance(result, Exception):
                logger.warning("%s check threw: %s", source, result)
            elif isinstance(result, list):
                all_items.extend(result)

        logger.info(f"API triggers: {len(all_items)} items total")
        return all_items
