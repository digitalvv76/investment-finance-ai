"""Futu news fetcher — keyword-based news search via Futu OpenD.

Uses get_search_news API to pull Chinese & English financial news from
Futu's news aggregation (富途资讯, MT Newswires, Benzinga, PR Newswire,
金十数据, 证券时报, etc.).

Strategy: search ALL keywords every cycle using concurrent API calls.
Each keyword gets its own OpenQuoteContext connection running in a thread
pool.  Deduplication by title hash prevents cross-keyword duplicates.

v2 (2026-07-21): replaced keyword rotation with full concurrent search.
All keywords searched every 60s instead of rotating 16 per cycle.
English company names added as supplementary keywords.

v2.1 (2026-07-21): keyword→ticker fallback.  When Futu returns an article
with empty related_securities, inject the search keyword's canonical ticker
(like Finnhub does via its symbol= parameter).  Prevents score=0 when
entity extraction misses a Chinese company name.
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
# Keywords — tickers + English company names + macro/people/theme
# ---------------------------------------------------------------------------
# Each watchlist stock gets BOTH its ticker AND its English company name
# as search keywords.  Ticker catches "KTOS stock surges"; company name
# catches "Kratos wins $156M contract" when the headline doesn't use the
# ticker symbol.  Futu get_search_news is language-agnostic.
_SEARCH_KEYWORDS = [
    # === Watchlist tickers + English company names (dual-keyword) ===
    "AAOI", "ABSI", "ACHR", "Archer Aviation",
    "ALAB", "AMBA",
    "ARKK", "ARKQ", "ARM", "Arm Holdings",
    "ASTS", "AST SpaceMobile",
    "AVAV", "AeroVironment",
    "AVGO", "Broadcom",
    "BABA", "Alibaba",
    "BE", "Bloom Energy",
    "BOT", "BOTZ", "BTBT",
    "BTC", "Bitcoin", "BTCS", "BTDR",
    "BWXT", "BWX Technologies",
    "CBRS", "CLPT", "CRWV", "DTIL",
    "ETH", "Ethereum",
    "FIG", "FUTU",
    "GLD", "GLXY", "Galaxy Digital",
    "GOOGL", "Google",
    "HII", "Huntington Ingalls",
    "HPE", "Hewlett Packard Enterprise",
    "IONQ", "IonQ",
    "IREN", "Iris Energy",
    "KTOS", "Kratos",
    "LEU", "Centrus Energy",
    "LITE", "Lumentum",
    "LRCX", "Lam Research",
    "MP", "MP Materials",
    "MRAAY", "MRVL", "Marvell",
    "MU", "Micron",
    "NBIS", "Nebius",
    "NNE", "Nano Nuclear",
    "NVDA", "Nvidia",
    "NVTS", "Navitas Semiconductor",
    "OKLO", "Oklo",
    "ORCL", "Oracle",
    "PLTR", "Palantir",
    "QQQ", "QQQM",
    "RDW", "Redwire",
    "RGTI", "Rigetti",
    "RKLB", "Rocket Lab",
    "ROBT", "RXRX", "Recursion",
    "SATS", "EchoStar",
    "SERV", "Serve Robotics",
    "SMH", "SMR", "NuScale",
    "SOL", "SOXL", "SOXX",
    "SPCX", "SpaceX",
    "TEM", "Tempus AI",
    "TSLA", "Tesla",
    "TSM", "TSMC", "Taiwan Semiconductor",
    "UPXI", "UUUU", "Energy Fuels",
    "VOO", "VPG", "VST", "Vistra",
    "WEN", "WOLF", "Wolfspeed",
    "ZETA", "Zeta Global",
    # === Macro / Fed (no ticker needed) ===
    "美联储", "CPI", "PPI", "非农", "GDP",
    # === Key people (person-driven events) ===
    "黄仁勋", "Jensen Huang", "马斯克", "Elon Musk", "巴菲特", "Warren Buffett",
    # === Broad market fallback ===
    "美股", "港股",
    # === Policy catalysts ===
    "芯片法案", "关税", "CHIPS Act", "tariff",
]

# Max results per keyword
_MAX_PER_KEYWORD = 20

# Max concurrent Futu API calls (local OpenD — keep modest to avoid
# overwhelming the daemon)
_MAX_CONCURRENT = 5

# Minimum seconds between cycles
_MIN_CYCLE_INTERVAL = 60

# Dedup window — skip titles seen in last N seconds
_DEDUP_TTL = 3600 * 4  # 4 hours

# ---------------------------------------------------------------------------
# Keyword → ticker fallback (like Finnhub's symbol= parameter)
# ---------------------------------------------------------------------------
# When Futu returns an article with empty related_securities, inject the
# search keyword's canonical ticker so the article gets a ticker hit in
# scoring.  Built from entity_extractor's company-name mappings + direct
# ticker matching against the known watchlist.
_KEYWORD_TO_TICKER: Dict[str, str] = {}


def _build_keyword_ticker_map() -> Dict[str, str]:
    """Build keyword→ticker lookup from entity_extractor mappings + keyword list.

    Called once at module load.  Returns a dict suitable for O(1) lookup
    during fetch.  Covers EVERY watchlist stock through three strategies:
      1. Direct ticker: uppercase 2-5 letters in the ticker section → self
      2. English company name → ticker (via entity_extractor._company_to_ticker)
      3. Manual company name → ticker for watchlist stocks not in entity_extractor
    Non-ticker keywords (macro, people, market, policy) are excluded.
    """
    from engine.entity_extractor import EntityExtractor

    ee = EntityExtractor(config=None)

    # Merge English + Chinese company-name → ticker maps
    company_to_ticker: Dict[str, str] = {}
    for name, ticker in ee._company_to_ticker.items():
        company_to_ticker[name.lower()] = ticker
    for name, ticker in ee._cn_company_to_ticker.items():
        company_to_ticker[name.lower()] = ticker

    # Additional watchlist-specific company names not in entity_extractor
    _extra_company_names: Dict[str, str] = {
        # Space / defense
        "archer aviation": "ACHR", "aerovironment": "AVAV",
        "redwire": "RDW", "huntington ingalls": "HII",
        # Tech / semiconductors
        "ionq": "IONQ", "hewlett packard enterprise": "HPE",
        "navitas semiconductor": "NVTS",
        # Energy / nuclear
        "oklo": "OKLO", "nuscale": "SMR", "nano nuclear": "NNE",
        "centrus energy": "LEU", "bloom energy": "BE",
        "iris energy": "IREN", "energy fuels": "UUUU",
        "vistra": "VST",
        # Industrials / materials
        "mp materials": "MP", "bwx technologies": "BWXT",
        "lumentum": "LITE",
        # Biotech / health
        "tempus ai": "TEM", "recursion": "RXRX",
        "serv robotics": "SERV", "serve robotics": "SERV",
        # Finance / crypto
        "galaxy digital": "GLXY",
        # Satcom / space
        "ast spacemobile": "ASTS", "echostar": "SATS",
        # Chips / hardware
        "micron": "MU", "oracle": "ORCL",
        "wolfspeed": "WOLF",
        # Adtech / data
        "zeta global": "ZETA",
        # Broadcom / Marvell (ensure)
        "broadcom": "AVGO", "marvell": "MRVL",
        "arm holdings": "ARM",
    }
    company_to_ticker.update(_extra_company_names)

    # Also add commonly-used short names
    for short_name, ticker in [
        ("arm", "ARM"), ("ionq", "IONQ"), ("oklo", "OKLO"),
        ("spacex", "SPCX"), ("nebius", "NBIS"), ("kratos", "KTOS"),
        ("nvidia", "NVDA"), ("tesla", "TSLA"), ("palantir", "PLTR"),
        ("rigetti", "RGTI"), ("oracle", "ORCL"), ("micron", "MU"),
        ("broadcom", "AVGO"), ("marvell", "MRVL"),
        ("tsmc", "TSM"), ("alibaba", "BABA"), ("google", "GOOGL"),
        ("rocket lab", "RKLB"), ("lam research", "LRCX"),
        ("taiwan semiconductor", "TSM"),
    ]:
        if short_name not in company_to_ticker:
            company_to_ticker[short_name] = ticker

    # Non-ticker keywords to exclude (macro, people, market, policy)
    _NON_TICKER = {
        "CPI", "PPI", "GDP", "ETH", "BTC", "SOL",
        "美联储", "非农", "美股", "港股", "芯片法案", "关税",
        "CHIPS Act", "chips act", "tariff",
        "黄仁勋", "Jensen Huang", "马斯克", "Elon Musk",
        "巴菲特", "Warren Buffett",
    }

    result: Dict[str, str] = {}
    for kw in _SEARCH_KEYWORDS:
        if kw in _NON_TICKER:
            continue

        kw_lower = kw.lower()

        # Strategy 1: Direct ticker (uppercase 2-5 letters)
        if 1 <= len(kw) <= 5 and kw.isalpha() and kw.isupper():
            result[kw] = kw
            continue

        # Strategy 2: Company name → ticker
        ticker = company_to_ticker.get(kw_lower)
        if ticker:
            result[kw] = ticker

    return result


# Build at import time
_KEYWORD_TO_TICKER = _build_keyword_ticker_map()


class FutuNewsFetcher:
    """Futu news search fetcher — concurrent full-keyword coverage.

    Searches ALL keywords every cycle using concurrent connections.
    No rotation — every ticker/company name is polled every 60 seconds.
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
        self._last_cycle = 0.0
        self._seen: Dict[str, float] = {}  # title_hash → timestamp

    async def fetch(self) -> List[NewsItem]:
        """Fetch news for ALL keywords concurrently. Call on heartbeat timer."""
        now = time.time()
        if now - self._last_cycle < _MIN_CYCLE_INTERVAL:
            remaining = _MIN_CYCLE_INTERVAL - (now - self._last_cycle)
            logger.debug("FutuNews: cooldown (%.0fs remaining)", remaining)
            return []

        self._last_cycle = now

        logger.info("FutuNews: searching ALL %d keywords (concurrent, max %d)",
                     len(self._keywords), _MAX_CONCURRENT)

        # ── Concurrent fetch: each keyword gets its own connection ──
        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _fetch_one(kw: str) -> List[dict]:
            async with sem:
                return await asyncio.to_thread(self._fetch_single_keyword, kw)

        tasks = [_fetch_one(kw) for kw in self._keywords]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results, skipping exceptions
        all_raw: List[dict] = []
        for kw, result in zip(self._keywords, results):
            if isinstance(result, Exception):
                logger.debug("FutuNews: keyword '%s' error: %s", kw, result)
            elif isinstance(result, list):
                all_raw.extend(result)

        logger.debug("FutuNews: %d raw items from %d keywords",
                     len(all_raw), len(self._keywords))

        # ── Dedup + build NewsItems ──
        items: List[NewsItem] = []
        for raw in all_raw:
            title = raw.get("title", "")
            title_hash = hashlib.md5(
                title.encode("utf-8", errors="replace")
            ).hexdigest()
            if title_hash in self._seen:
                if now - self._seen[title_hash] < _DEDUP_TTL:
                    continue
            self._seen[title_hash] = now

            tickers_raw = raw.get("related_tickers", [])
            # ── Finnhub-style fallback: inject search keyword's ticker ──
            # When Futu returns empty related_securities (common for Chinese-
            # language articles found via English ticker search), use the
            # keyword→ticker map to ensure the article gets a ticker hit in
            # scoring.  This mirrors Finnhub's tickers_found=ticker from its
            # symbol= query parameter.
            if not tickers_raw:
                search_kw = raw.get("_search_kw", "")
                fallback_ticker = _KEYWORD_TO_TICKER.get(search_kw, "")
                if fallback_ticker:
                    tickers_raw = [fallback_ticker]
            tickers_str = ",".join(tickers_raw)
            items.append(NewsItem(
                title=title,
                url=raw.get("url", ""),
                source=raw.get("source", ""),
                content_snippet=title,
                published_at=_parse_futu_time(raw.get("published_at", "")),
                tickers_found=tickers_str,
            ))

        # Cleanup old seen entries
        cutoff = now - _DEDUP_TTL * 2
        self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

        logger.info("FutuNews: %d unique items (from %d raw)",
                     len(items), len(all_raw))
        return items

    def _fetch_single_keyword(self, kw: str) -> List[dict]:
        """Fetch news for ONE keyword. Runs in thread pool (Futu API is sync)."""
        from futu import OpenQuoteContext, NewsSubType, RET_OK

        ctx = None
        try:
            ctx = OpenQuoteContext(host=self._host, port=self._port)
            ret, data = ctx.get_search_news(
                kw,
                max_count=_MAX_PER_KEYWORD,
                news_sub_type=NewsSubType.ALL,
            )
            if ret != RET_OK:
                logger.debug("FutuNews: search '%s' failed: %s", kw, data)
                return []
            if data is None or len(data) == 0:
                return []

            items: List[dict] = []
            for _, row in data.iterrows():
                related = row.get("related_securities", None)
                if related is None or not isinstance(related, list):
                    related = []

                items.append({
                    "title": str(row.get("title", "")),
                    "source": f"富途·{row.get('source', '资讯')}",
                    "url": str(row.get("url", "")),
                    "published_at": str(row.get("publish_time", "")),
                    "related_tickers": related,
                    "_search_kw": kw,  # for keyword→ticker fallback
                })
            return items
        except Exception as e:
            logger.debug("FutuNews: keyword '%s' error: %s", kw, e)
            return []
        finally:
            if ctx is not None:
                ctx.close()

    async def close(self):
        """No-op — connections are per-cycle."""
        pass


def _parse_futu_time(ts: str) -> datetime:
    """Parse Futu publish_time to datetime. Returns now() on failure."""
    if not ts:
        return datetime.now()
    try:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d"):
            try:
                return datetime.strptime(ts.strip(), fmt)
            except ValueError:
                continue
        parts = ts.strip().split("/")
        if len(parts) == 2:
            return datetime(datetime.now().year, int(parts[0]), int(parts[1]))
    except Exception:
        pass
    return datetime.now()
