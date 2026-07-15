"""East Money fund-flow fetcher — daily money flow by order size (free, no key).

Data source: push2his.eastmoney.com (primary) with ff.eastmoney.com HTTP fallback.
Provides 主力/超大单/大单/中单/小单 net inflow + 主力占比 for US and HK stocks.

Anti-scraping strategy (East Money rate-limits aggressively):
  - Minimum 6s between requests (proven safe at ~10 req/min)
  - Random User-Agent rotation per request
  - Proper Referer + ut token
  - Exponential backoff with jitter on 429/connection errors
  - Proxy support via HTTP_PROXY / HTTPS_PROXY env vars
  - Dedup cache: same ticker+daterange → cached for TTL

Usage:
  fetcher = EastMoneyFundFlowFetcher(proxy="http://user:pass@host:8080")
  data = await fetcher.fetch("AAPL", days=20)  # → List[FundFlowDay]
  await fetcher.close()
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------
PUSH2HIS_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
FF_URL = "http://ff.eastmoney.com/EM_CapitalFlowInterface/api/js"

# Access tokens (public, extracted from East Money web frontends)
UT_TOKEN = "b2884a393a59ad64002292a3e90d46a5"
FF_TOKEN = "1942f5da9b46b069953c873404aad4b5"

# Fields for push2his: date, main_net, super_big_net, big_net, mid_net, small_net, main_pct
FIELDS2 = "f51,f52,f53,f54,f55,f56,f57"

# User-Agent pool (recent Chrome/Firefox on Win/Mac/Linux)
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]

# Minimum seconds between API requests (East Money rate limit is aggressive;
# Server-disconnect errors suggest ~20 req/min before temporary IP ban)
MIN_REQUEST_INTERVAL = 12.0

# Cache TTL: fund flow data only changes once per day (after US market close)
CACHE_TTL_SECONDS = 3600  # 1 hour

# Retry config — connection failures skip retries (not transient);
# only 429/403 trigger the full backoff.
MAX_RETRIES = 2
BASE_BACKOFF = 3.0  # seconds


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class FundFlowDay:
    """Single day of money flow data."""

    date: str  # "YYYY-MM-DD"
    main_net: float = 0.0  # 主力净流入 (元)
    super_big_net: float = 0.0  # 超大单净流入 (元)
    big_net: float = 0.0  # 大单净流入 (元)
    mid_net: float = 0.0  # 中单净流入 (元)
    small_net: float = 0.0  # 小单净流入 (元)
    main_pct: float = 0.0  # 主力净占比 (%)

    # Derived fields (computed post-fetch)
    close_price: float = 0.0  # populated if available from yfinance
    change_pct: float = 0.0  # populated if available from yfinance

    @classmethod
    def from_kline(cls, kline: str) -> "FundFlowDay":
        """Parse a kline string: date,main,super,big,mid,small,pct"""
        parts = kline.split(",")
        if len(parts) < 7:
            raise ValueError(f"Expected 7 fields, got {len(parts)}: {kline!r}")
        return cls(
            date=parts[0].strip(),
            main_net=float(parts[1]),
            super_big_net=float(parts[2]),
            big_net=float(parts[3]),
            mid_net=float(parts[4]),
            small_net=float(parts[5]),
            main_pct=float(parts[6]),
        )


@dataclass
class FundFlowResult:
    """Full fund flow fetch result for one ticker."""

    ticker: str
    secid: str
    name: str = ""
    market: str = ""  # "NASDAQ" / "NYSE" / "HK"
    days: List[FundFlowDay] = field(default_factory=list)
    fetched_at: float = 0.0
    source: str = ""  # "push2his" / "ff"


# ---------------------------------------------------------------------------
# Symbol resolver
# ---------------------------------------------------------------------------
# Known exchange mappings from yfinance 'exchange' field → East Money market code
_EXCHANGE_TO_MKT: Dict[str, int] = {
    "NMS": 105,  # NASDAQ
    "NGM": 105,  # NASDAQ Global Market
    "NCM": 105,  # NASDAQ Capital Market
    "NYQ": 106,  # NYSE
    "ASE": 106,  # NYSE American
    "PCX": 106,  # NYSE Arca
    "BTS": 106,  # NYSE (BATS)
    "OQX": 107,  # OTC
    "OQB": 107,  # OTC
    "PNK": 107,  # OTC Pink
}

# Common tickers and their known markets (to avoid extra API calls)
_KNOWN_MARKETS: Dict[str, Tuple[int, str]] = {
    # NASDAQ
    "AAPL": (105, "NASDAQ"), "MSFT": (105, "NASDAQ"), "GOOGL": (105, "NASDAQ"),
    "AMZN": (105, "NASDAQ"), "NVDA": (105, "NASDAQ"), "META": (105, "NASDAQ"),
    "TSLA": (105, "NASDAQ"), "NFLX": (105, "NASDAQ"), "AMD": (105, "NASDAQ"),
    "INTC": (105, "NASDAQ"), "AVGO": (105, "NASDAQ"), "ASML": (105, "NASDAQ"),
    "ARM": (105, "NASDAQ"), "MRVL": (105, "NASDAQ"), "PLTR": (105, "NASDAQ"),
    "RKLB": (105, "NASDAQ"), "ASTS": (105, "NASDAQ"), "RGTI": (105, "NASDAQ"),
    "TEM": (105, "NASDAQ"), "OKLO": (105, "NASDAQ"), "SMR": (105, "NASDAQ"),
    "NBIS": (105, "NASDAQ"), "SOXL": (105, "NASDAQ"),
    # NYSE
    "BRK.A": (106, "NYSE"), "BRK.B": (106, "NYSE"), "JPM": (106, "NYSE"),
    "V": (106, "NYSE"), "WMT": (106, "NYSE"), "XOM": (106, "NYSE"),
    "SPCX": (106, "NYSE"), "KTOS": (106, "NYSE"), "BOT": (106, "NYSE"),
    "LRCX": (106, "NASDAQ"),  # Actually NASDAQ
    # HK (116)
    "00700": (116, "HK"), "09988": (116, "HK"), "09618": (116, "HK"),
    "00388": (116, "HK"), "00981": (116, "HK"),
}


def resolve_secid(ticker: str) -> str:
    """Convert a ticker to East Money secid.

    Tries known-market lookup first, then heuristics.
    Returns a comma-separated list of candidate secids to try.
    """
    # Check known markets first
    if ticker.upper() in _KNOWN_MARKETS:
        mkt, _ = _KNOWN_MARKETS[ticker.upper()]
        return f"{mkt}.{ticker.upper()}"

    # Heuristic: 4-5 digit code → HK, 1-5 letter code → try NASDAQ + NYSE
    if ticker.isdigit():
        ticker_padded = ticker.zfill(5)
        return f"116.{ticker_padded}"
    else:
        # For US stocks, we don't know exchange — return both to try
        return f"105.{ticker.upper()}"  # Default to NASDAQ


# ---------------------------------------------------------------------------
# Simple in-memory cache
# ---------------------------------------------------------------------------
class _Cache:
    """Minimal TTL cache to avoid re-fetching the same ticker repeatedly."""

    def __init__(self):
        self._store: Dict[str, Tuple[float, FundFlowResult]] = {}

    def get(self, key: str) -> Optional[FundFlowResult]:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, val = entry
        if time.time() - ts > CACHE_TTL_SECONDS:
            del self._store[key]
            return None
        return val

    def set(self, key: str, val: FundFlowResult):
        self._store[key] = (time.time(), val)

    def clear(self):
        self._store.clear()


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------
class EastMoneyFundFlowFetcher:
    """Async fetcher for East Money daily fund flow data.

    Designed for low-frequency use: 1 request per ticker per hour (cached).
    NOT suitable for real-time streaming — East Money rate limits aggressively.
    """

    def __init__(self, proxy: str = ""):
        self._proxy = proxy or os.environ.get("HTTPS_PROXY", os.environ.get("HTTP_PROXY", ""))
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache = _Cache()
        self._last_request_time = 0.0
        self._request_count = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = None
            timeout = aiohttp.ClientTimeout(total=20)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    async def _throttle(self):
        """Ensure minimum interval between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            delay = MIN_REQUEST_INTERVAL - elapsed + random.uniform(0, 1)
            logger.debug("Throttling %.1fs before next East Money request", delay)
            await asyncio.sleep(delay)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # Core fetch
    # ------------------------------------------------------------------
    async def fetch(
        self, ticker: str, days: int = 20, prefer_market: str = ""
    ) -> Optional[FundFlowResult]:
        """Fetch fund flow for a single ticker.

        Args:
            ticker: Stock ticker (e.g. "AAPL", "00700")
            days: Number of trading days to fetch (max ~100)
            prefer_market: Hint for exchange resolution ("NASDAQ" / "NYSE" / "HK")

        Returns:
            FundFlowResult on success, None on failure.
        """
        ticker = ticker.upper().strip()
        cache_key = f"{ticker}:{days}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for %s (%d days)", ticker, days)
            return cached

        secid = resolve_secid(ticker)

        # Try primary (push2his HTTPS)
        result = await self._fetch_push2his(secid, days)
        if result is not None:
            result.ticker = ticker
            self._cache.set(cache_key, result)
            return result

        # Fallback: try alternate market (105→106 or vice versa for US stocks)
        alt_secid = self._alt_secid(secid)
        if alt_secid:
            logger.debug("Trying alternate secid %s for %s", alt_secid, ticker)
            result = await self._fetch_push2his(alt_secid, days)
            if result is not None:
                result.ticker = ticker
                self._cache.set(cache_key, result)
                return result

        # Last resort: try HTTP ff.eastmoney.com
        result = await self._fetch_ff(secid, days)
        if result is not None:
            result.ticker = ticker
            self._cache.set(cache_key, result)
            return result

        logger.warning("All sources failed for %s (%s)", ticker, secid)
        return None

    @staticmethod
    def _alt_secid(secid: str) -> Optional[str]:
        """Try the other US exchange: 105 ↔ 106"""
        if secid.startswith("105."):
            return "106." + secid[4:]
        if secid.startswith("106."):
            return "105." + secid[4:]
        return None

    async def _fetch_push2his(self, secid: str, days: int) -> Optional[FundFlowResult]:
        """Primary: push2his HTTPS API."""
        params = {
            "secid": secid,
            "klt": 101,
            "fields1": "f1,f2,f3,f7",
            "fields2": FIELDS2,
            "lmt": str(days),
            "ut": UT_TOKEN,
        }
        headers = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Referer": "https://data.eastmoney.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }

        for attempt in range(MAX_RETRIES):
            await self._throttle()
            session = await self._get_session()
            try:
                async with session.get(
                    PUSH2HIS_URL, params=params, headers=headers, proxy=self._proxy or None,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._parse_push2his(secid, data)
                    elif resp.status in (429, 403):
                        logger.warning(
                            "East Money returned %d for %s (attempt %d/%d)",
                            resp.status, secid, attempt + 1, MAX_RETRIES,
                        )
                    else:
                        logger.debug(
                            "East Money returned %d for %s", resp.status, secid,
                        )
            except aiohttp.ClientError as e:
                logger.warning(
                    "East Money request failed for %s (attempt %d/%d): %s",
                    secid, attempt + 1, MAX_RETRIES, e,
                )
                # Server-disconnect = IP throttling; retrying makes it worse
                if "Server disconnected" in str(e):
                    break
            except asyncio.TimeoutError as e:
                logger.warning(
                    "East Money timeout for %s (attempt %d/%d): %s",
                    secid, attempt + 1, MAX_RETRIES, e,
                )

            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 1)
                logger.debug("Backoff %.1fs before retry", backoff)
                await asyncio.sleep(backoff)

        return None

    async def _fetch_ff(self, secid: str, days: int) -> Optional[FundFlowResult]:
        """Fallback: ff.eastmoney.com HTTP API (no SSL, may bypass GFW)."""
        # ff.eastmoney.com uses a different ID format: 105.AAPL → just the code part
        code = secid.split(".")[-1] if "." in secid else secid

        params = {
            "id": code,
            "type": "hff",  # historical fund flow
            "rtntype": "2",
            "acces_token": FF_TOKEN,
        }
        headers = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Referer": "https://data.eastmoney.com/",
        }

        for attempt in range(min(2, MAX_RETRIES)):
            await self._throttle()
            session = await self._get_session()
            try:
                async with session.get(
                    FF_URL, params=params, headers=headers, proxy=self._proxy or None,
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        return self._parse_ff_response(secid, text, days)
                    elif resp.status == 302:
                        logger.debug("ff.eastmoney.com returned 302 redirect for %s", secid)
                    else:
                        logger.debug("ff.eastmoney.com returned %d for %s", resp.status, secid)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.debug("ff.eastmoney.com request failed for %s: %s", secid, e)

            if attempt < min(2, MAX_RETRIES) - 1:
                await asyncio.sleep(1.5)

        return None

    # ------------------------------------------------------------------
    # Batch fetch
    # ------------------------------------------------------------------
    async def fetch_multi(
        self, tickers: List[str], days: int = 20,
    ) -> Dict[str, Optional[FundFlowResult]]:
        """Fetch fund flow for multiple tickers sequentially (respects rate limit).

        Returns a dict mapping ticker → result (None for failures).
        """
        results = {}
        for i, ticker in enumerate(tickers):
            logger.debug(
                "Fetching %s (%d/%d)", ticker, i + 1, len(tickers),
            )
            try:
                results[ticker] = await self.fetch(ticker, days=days)
            except Exception as e:
                logger.error("Unexpected error fetching %s: %s", ticker, e)
                results[ticker] = None

            # Extra gap between batch items to be safe
            if i < len(tickers) - 1:
                await asyncio.sleep(0.5)

        success = sum(1 for v in results.values() if v is not None)
        logger.info(
            "Batch complete: %d/%d tickers succeeded", success, len(tickers),
        )
        return results

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_push2his(secid: str, data: dict) -> Optional[FundFlowResult]:
        """Parse push2his JSON response into FundFlowResult."""
        inner = data.get("data")
        if not inner:
            logger.debug("push2his returned no data for %s (rc=%s)", secid, data.get("rc"))
            return None

        klines = inner.get("klines")
        if not klines:
            logger.debug("push2his returned empty klines for %s", secid)
            return None

        code = inner.get("code", "")
        name = inner.get("name", "")
        market_num = inner.get("market", 0)

        market_map = {105: "NASDAQ", 106: "NYSE", 107: "US_OTHER", 116: "HK"}
        market = market_map.get(market_num, f"MKT{market_num}")

        days = []
        for line in klines:
            try:
                days.append(FundFlowDay.from_kline(line))
            except ValueError as e:
                logger.warning("Skipping malformed kline for %s: %s", secid, e)

        return FundFlowResult(
            ticker="",
            secid=secid,
            name=name,
            market=market,
            days=days,
            fetched_at=time.time(),
            source="push2his",
        )

    @staticmethod
    def _parse_ff_response(secid: str, text: str, max_days: int) -> Optional[FundFlowResult]:
        """Parse ff.eastmoney.com JS-like response.

        Format: ([...]) — a JSON array wrapped in parentheses.
        Each element is a comma-separated string.
        Fields: date, inflow, outflow, net_inflow, net_pct,
                super_inflow, super_outflow, super_net, super_pct,
                large_inflow, large_outflow, large_net, large_pct,
                mid_inflow, mid_outflow, mid_net, mid_pct,
                small_inflow, small_outflow, small_net, small_pct,
                close, change_pct, col1
        """
        try:
            # Strip outer parentheses
            text = text.strip()
            if text.startswith("("):
                text = text[1:]
            if text.endswith(")"):
                text = text[:-1]
            if text.endswith(";"):
                text = text[:-1]

            import json
            raw_data = json.loads(text)
            if not isinstance(raw_data, list):
                return None

            days = []
            for item in raw_data[-max_days:]:  # take last N days
                if isinstance(item, str):
                    parts = item.split(",")
                else:
                    continue

                if len(parts) < 23:
                    continue

                try:
                    day = FundFlowDay(
                        date=parts[0].strip(),
                        main_net=float(parts[3]),  # net_inflow = main_net
                        super_big_net=float(parts[7]),  # super_net
                        big_net=float(parts[11]),  # large_net
                        mid_net=float(parts[15]),  # mid_net
                        small_net=float(parts[19]),  # small_net
                        main_pct=float(parts[4]),  # net_pct
                        close_price=float(parts[21]) if len(parts) > 21 else 0.0,
                        change_pct=float(parts[22]) if len(parts) > 22 else 0.0,
                    )
                    days.append(day)
                except (ValueError, IndexError) as e:
                    logger.debug("Skipping malformed ff line: %s", e)

            return FundFlowResult(
                ticker="",
                secid=secid,
                days=days,
                fetched_at=time.time(),
                source="ff",
            )
        except Exception as e:
            logger.warning("Failed to parse ff response for %s: %s", secid, e)
            return None


# ---------------------------------------------------------------------------
# Convenience: compute derived signals from fund flow data
# ---------------------------------------------------------------------------
def compute_divergence_signal(days: List[FundFlowDay]) -> dict:
    """Apply the v2 Prompt divergence analysis to fund flow data.

    Uses main_net (= 特大单 + 大单) as the primary metric, per V2.1
    revision: merging super_big + big prevents institutions from hiding
    behind order-splitting.

    Returns a dict with signal type, strength, and supporting evidence.
    """
    if len(days) < 3:
        return {"signal": "insufficient_data", "strength": 0}

    latest = days[-1]
    recent = days[-3:]

    # Main force = 特大单 + 大单 (V2.1: 防机构拆单)
    cum_main = sum(d.main_net for d in recent)
    cum_super_big = sum(d.super_big_net for d in recent)

    signal = {"signal": "none", "strength": 0, "details": {}}

    signal["details"]["cum_main_3d"] = cum_main             # primary metric (V2.1)
    signal["details"]["cum_super_big_3d"] = cum_super_big   # retained for reference
    signal["details"]["latest_main_pct"] = latest.main_pct
    signal["details"]["latest_main_net"] = latest.main_net

    # ------------------------------------------------------------------
    # Participation thresholds — main_pct = (特大单+大单)/成交额
    # (V2.1: same threshold bands, now applied to the broader metric)
    # ------------------------------------------------------------------
    abs_pct = abs(latest.main_pct)
    if abs_pct < 2:
        signal["details"]["participation"] = "low"
    elif abs_pct < 8:
        signal["details"]["participation"] = "normal"
    elif abs_pct < 15:
        signal["details"]["participation"] = "strong"
    else:
        signal["details"]["participation"] = "extreme"

    # Continuity: main_net direction over 3 days (V2.1: 特大单+大单合计)
    main_directions = [1 if d.main_net > 0 else -1 for d in recent]
    if all(d == 1 for d in main_directions):
        signal["details"]["continuity"] = "continuous_inflow"
    elif all(d == -1 for d in main_directions):
        signal["details"]["continuity"] = "continuous_outflow"
    else:
        signal["details"]["continuity"] = "mixed"

    return signal
