"""Futu news fetcher — keyword-based news search via Futu OpenD.

Uses get_search_news API to pull Chinese & English financial news from
Futu's news aggregation (富途资讯, MT Newswires, Benzinga, PR Newswire,
金十数据, 证券时报, etc.).

Strategy: rotate through a keyword list on each heartbeat cycle. Each call
returns up to 100 items per keyword. Deduplication by title prevents
cross-keyword duplicates.

Usage:
  fetcher = FutuNewsFetcher(host="127.0.0.1", port=11111)
  items = await fetcher.fetch()  # → List[NewsItem]
  await fetcher.close()
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from storage.models import NewsItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword rotation — covers tickers, macro, sectors, people
# ---------------------------------------------------------------------------
_SEARCH_KEYWORDS = [
    # === Full watchlist — direct ticker search (74 stocks) ===
    # Futu get_search_news is language-agnostic: "NBIS" catches both
    # "NBIS Stock Jumps" and "奈比斯暴涨".  Finnhub covers English;
    # Futu fills the Chinese-language gap.
    "AAOI", "ABSI", "ACHR", "ALAB", "AMBA", "ARKK", "ARKQ", "ARM",
    "ASTS", "AVAV", "AVGO", "BABA", "BE", "BOT", "BOTZ", "BTBT",
    "BTC", "BTCS", "BTDR", "BWXT", "CBRS", "CLPT", "CRWV", "DTIL",
    "ETH", "FIG", "FUTU", "GLD", "GLXY", "GOOGL", "HII", "HPE",
    "IONQ", "IREN", "KTOS", "LEU", "LITE", "LRCX", "MP", "MRAAY",
    "MRVL", "MU", "NBIS", "NNE", "NVDA", "NVTS", "OKLO", "ORCL",
    "PLTR", "QQQ", "QQQM", "RDW", "RGTI", "RKLB", "ROBT", "RXRX",
    "SATS", "SERV", "SMH", "SMR", "SOL", "SOXL", "SOXX", "SPCX",
    "TEM", "TSLA", "UPXI", "UUUU", "VOO", "VPG", "VST", "WEN",
    "WOLF", "ZETA",
    # === Macro / Fed (no ticker needed) ===
    "美联储", "CPI", "PPI", "非农", "GDP",
    # === Key people (person-driven events) ===
    "黄仁勋", "马斯克", "巴菲特",
    # === Broad market fallback ===
    "美股", "港股",
    # === Policy catalysts ===
    "芯片法案", "关税",
]

# Number of keywords to search per cycle (rotate through full list)
_KEYWORDS_PER_CYCLE = 8

# Max results per keyword
_MAX_PER_KEYWORD = 20

# Minimum seconds between cycles (Futu rate limit friendly)
_MIN_CYCLE_INTERVAL = 60

# Dedup window — skip titles seen in last N seconds
_DEDUP_TTL = 3600 * 4  # 4 hours


class FutuNewsFetcher:
    """Futu news search fetcher.

    Rotates through keywords to avoid redundant API calls while maintaining
    broad coverage. Each cycle searches _KEYWORDS_PER_CYCLE keywords.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        keywords: Optional[List[str]] = None,
    ):
        self._host = host
        self._port = port
        self._keywords = keywords or _SEARCH_KEYWORDS
        self._keyword_index = 0
        self._last_cycle = 0.0
        self._seen: Dict[str, float] = {}  # title_hash → timestamp

    async def fetch(self) -> List[NewsItem]:
        """Fetch a batch of news items. Call this on a heartbeat timer."""
        now = time.time()
        if now - self._last_cycle < _MIN_CYCLE_INTERVAL:
            logger.debug("FutuNews: cycle cooldown (%.0fs remaining)",
                         _MIN_CYCLE_INTERVAL - (now - self._last_cycle))
            return []

        self._last_cycle = now

        # Rotate keywords
        batch = []
        start = self._keyword_index
        for i in range(_KEYWORDS_PER_CYCLE):
            idx = (start + i) % len(self._keywords)
            batch.append(self._keywords[idx])
        self._keyword_index = (start + _KEYWORDS_PER_CYCLE) % len(self._keywords)

        logger.info("FutuNews: searching %d keywords: %s", len(batch), batch)

        try:
            results = await asyncio.to_thread(self._fetch_batch_sync, batch)
        except Exception as e:
            logger.error("FutuNews: batch fetch failed: %s", e)
            return []

        # Dedup + build NewsItems
        items: List[NewsItem] = []
        for raw in results:
            title = raw.get("title", "")
            title_hash = hashlib.md5(title.encode("utf-8", errors="replace")).hexdigest()
            if title_hash in self._seen:
                if now - self._seen[title_hash] < _DEDUP_TTL:
                    continue
            self._seen[title_hash] = now

            # Build NewsItem
            tickers_str = ",".join(raw.get("related_tickers", []))
            items.append(NewsItem(
                title=title,
                url=raw.get("url", ""),
                source=raw.get("source", ""),
                content_snippet=title,  # title is the best we have
                published_at=_parse_futu_time(raw.get("published_at", "")),
                tickers_found=tickers_str,
            ))

        # Cleanup old seen entries
        cutoff = now - _DEDUP_TTL * 2
        self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

        logger.info("FutuNews: %d unique items (from %d raw)", len(items), len(results))
        return items

    def _fetch_batch_sync(self, keywords: List[str]) -> List[dict]:
        """Synchronous batch fetch — runs in thread pool."""
        from futu import OpenQuoteContext, NewsSubType, RET_OK

        ctx = OpenQuoteContext(host=self._host, port=self._port)
        all_items: List[dict] = []

        try:
            for kw in keywords:
                try:
                    ret, data = ctx.get_search_news(
                        kw,
                        max_count=_MAX_PER_KEYWORD,
                        news_sub_type=NewsSubType.ALL,
                    )
                    if ret != RET_OK:
                        logger.debug("FutuNews: search '%s' failed: %s", kw, data)
                        continue
                    if data is None or len(data) == 0:
                        continue

                    for _, row in data.iterrows():
                        related = row.get("related_securities", None)
                        if related is None or not isinstance(related, list):
                            related = []

                        all_items.append({
                            "title": str(row.get("title", "")),
                            "source": f"富途·{row.get('source', '资讯')}",
                            "url": str(row.get("url", "")),
                            "published_at": str(row.get("publish_time", "")),
                            "related_tickers": related,
                        })
                except Exception as e:
                    logger.debug("FutuNews: keyword '%s' error: %s", kw, e)
                    continue
        finally:
            ctx.close()

        return all_items

    async def close(self):
        """No-op — connections are per-cycle."""
        pass


def _parse_futu_time(ts: str) -> datetime:
    """Parse Futu publish_time to datetime. Returns now() on failure."""
    if not ts:
        return datetime.now()
    try:
        # Try common formats: "2026-07-16 10:30:00" or "5/13" etc.
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d"):
            try:
                return datetime.strptime(ts.strip(), fmt)
            except ValueError:
                continue
        # If just "5/13", use current year
        parts = ts.strip().split("/")
        if len(parts) == 2:
            return datetime(datetime.now().year, int(parts[0]), int(parts[1]))
    except Exception:
        pass
    return datetime.now()
