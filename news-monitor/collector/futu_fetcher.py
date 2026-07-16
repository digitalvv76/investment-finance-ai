"""Futu fund-flow fetcher — daily money flow via Futu OpenD.

Replaces East Money fetcher with same FundFlowDay / FundFlowResult interface.
Uses Futu OpenD gateway for market data — no IP blocking, no proxy needed.

Usage:
  fetcher = FutuFundFlowFetcher(host="127.0.0.1", port=11111)
  data = await fetcher.fetch("AAPL", days=20)  # → FundFlowResult | None
  await fetcher.close()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model — identical to eastmoney_fetcher.py for drop-in compatibility
# ---------------------------------------------------------------------------


@dataclass
class FundFlowDay:
    """Single day of money flow data — Futu standard.

    Futu order-size tiers (algorithm-defined, not fixed CNY thresholds):
      main       — 主力 (Block Orders): institution/insider orders identified
                   by trading pattern, not simple amount aggregation
      super_big  — 特大单: extra-large block trades
      big        — 大单: large orders
      mid        — 中单: medium orders
      sml        — 小单: small/retail orders

    CRITICAL: Futu's `main` is a standalone metric — it is NOT simply
    super_big + big. It represents algorithmically-identified "smart money"
    flow. Do NOT decompose it into sub-components.
    """

    date: str
    main_net: float = 0.0        # 主力净流入 (Futu: main_in_flow)
    super_big_net: float = 0.0   # 特大单净流入 (Futu: super_in_flow)
    big_net: float = 0.0         # 大单净流入 (Futu: big_in_flow)
    mid_net: float = 0.0         # 中单净流入 (Futu: mid_in_flow)
    small_net: float = 0.0       # 小单净流入 (Futu: sml_in_flow)
    main_pct: float = 0.0        # 主力占比 = main_net / abs(total_flow) * 100

    # Derived fields (populated post-fetch from yfinance)
    close_price: float = 0.0
    change_pct: float = 0.0


@dataclass
class FundFlowResult:
    """Full fund flow fetch result for one ticker — Futu standard."""

    ticker: str
    secid: str = ""
    name: str = ""
    market: str = ""  # "US" / "HK"
    days: List[FundFlowDay] = field(default_factory=list)
    fetched_at: float = 0.0
    source: str = "futu"


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class _Cache:
    """Simple TTL cache."""

    def __init__(self, ttl: float = 3600):
        self._store: Dict[str, tuple] = {}
        self._ttl = ttl

    def get(self, key: str) -> Optional[FundFlowResult]:
        ts, val = self._store.get(key, (0, None))
        if time.time() - ts < self._ttl:
            return val
        return None

    def set(self, key: str, val: FundFlowResult):
        self._store[key] = (time.time(), val)


# ---------------------------------------------------------------------------
# Ticker mapping
# ---------------------------------------------------------------------------

# Known HK tickers (pure digits like 00700)
_HK_TICKERS = frozenset({
    "00700", "09988", "00388", "00981", "09618", "03690", "01810",
    "02318", "02628", "00005", "01299", "01398", "03988", "00883",
    "00941", "01024", "09626", "09660", "01347", "09888", "09999",
    "02015", "02018", "09961", "01833", "00020", "02899", "01818",
    "01288", "01109", "02601", "06862", "02382", "02020", "01038",
})


def _to_futu_code(ticker: str) -> str:
    """Map raw ticker to Futu format: AAPL→US.AAPL, 00700→HK.00700"""
    t = ticker.upper().strip()
    # HK tickers: 5-digit numeric
    if t.isdigit() and len(t) == 5:
        return f"HK.{t}"
    # US tickers: alphabetic
    return f"US.{t}"


def _ticker_to_market(ticker: str) -> str:
    """Guess market from ticker format."""
    t = ticker.upper().strip()
    if t.isdigit() and len(t) == 5:
        return "HK"
    return "US"


# ---------------------------------------------------------------------------
# FutuFundFlowFetcher
# ---------------------------------------------------------------------------


class FutuFundFlowFetcher:
    """Fetch fund flow data via Futu OpenD.

    The Futu Python SDK is synchronous, so all API calls are wrapped
    in ``asyncio.to_thread`` to avoid blocking the event loop.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self._host = host
        self._port = port
        self._cache = _Cache(ttl=3600)

    async def fetch(
        self, ticker: str, days: int = 20, prefer_market: str = ""
    ) -> Optional[FundFlowResult]:
        """Fetch fund flow for a single ticker.

        Args:
            ticker: Stock ticker (e.g. "AAPL", "00700")
            days: Number of trading days to fetch (max ~100)
            prefer_market: Unused; market is inferred from ticker format.

        Returns:
            FundFlowResult on success, None on failure.
        """
        ticker = ticker.upper().strip()
        cache_key = f"{ticker}:{days}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for %s (%d days)", ticker, days)
            return cached

        futu_code = _to_futu_code(ticker)
        market = prefer_market or _ticker_to_market(ticker)

        try:
            result = await asyncio.to_thread(self._fetch_sync, futu_code, ticker, days, market)
            if result is not None:
                self._cache.set(cache_key, result)
                return result
        except Exception as e:
            logger.error("Futu fetch failed for %s (%s): %s", ticker, futu_code, e)

        return None

    def _fetch_sync(
        self, futu_code: str, ticker: str, days: int, market: str
    ) -> Optional[FundFlowResult]:
        """Synchronous Futu API call — runs in thread pool."""
        from futu import OpenQuoteContext, PeriodType, RET_OK, SubType

        ctx = OpenQuoteContext(host=self._host, port=self._port)
        try:
            # Calculate date range
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime(
                "%Y-%m-%d"
            )  # extra buffer for non-trading days

            ret, data = ctx.get_capital_flow(
                futu_code,
                period_type=PeriodType.DAY,
                start=start_date,
                end=end_date,
            )

            if ret != RET_OK:
                logger.warning(
                    "Futu get_capital_flow failed for %s: %s", futu_code, data
                )
                return None

            if data is None or len(data) == 0:
                logger.debug("Futu returned empty data for %s", futu_code)
                return None

            # Fetch stock name via snapshot
            name = ""
            try:
                ret_snap, snap = ctx.get_market_snapshot([futu_code])
                if ret_snap == RET_OK and len(snap) > 0:
                    name = str(snap.iloc[0].get("name", ""))
            except Exception:
                pass

            # Parse days
            parsed_days = []
            for _, row in data.iterrows():
                try:
                    flow_time = str(row.get("capital_flow_item_time", ""))
                    # Format: "2026-07-14 00:00:00" → "2026-07-14"
                    if " " in flow_time:
                        flow_time = flow_time.split(" ")[0]

                    main_in = float(row.get("main_in_flow", 0) or 0)
                    super_in = float(row.get("super_in_flow", 0) or 0)
                    big_in = float(row.get("big_in_flow", 0) or 0)
                    mid_in = float(row.get("mid_in_flow", 0) or 0)
                    sml_in = float(row.get("sml_in_flow", 0) or 0)
                    in_flow = float(row.get("in_flow", 0) or 0)

                    # Compute main_pct: main / abs(total) * 100
                    if in_flow != 0:
                        main_pct = (main_in / abs(in_flow)) * 100
                    else:
                        total_abs = (
                            abs(main_in) + abs(super_in) + abs(big_in)
                            + abs(mid_in) + abs(sml_in)
                        )
                        if total_abs > 0:
                            main_pct = (main_in / total_abs) * 100
                        else:
                            main_pct = 0.0

                    fd = FundFlowDay(
                        date=flow_time,
                        main_net=main_in,
                        super_big_net=super_in,
                        big_net=big_in,
                        mid_net=mid_in,
                        small_net=sml_in,
                        main_pct=round(main_pct, 2),
                    )
                    parsed_days.append(fd)
                except Exception as e:
                    logger.debug("Skipping row for %s: %s", futu_code, e)
                    continue

            if not parsed_days:
                return None

            # Return last N days
            parsed_days = parsed_days[-days:]

            return FundFlowResult(
                ticker=ticker,
                secid=futu_code,
                name=name,
                market=market,
                days=parsed_days,
                fetched_at=time.time(),
                source="futu",
            )

        except Exception as e:
            logger.error("Futu error for %s (%s): %s", ticker, futu_code, e)
            return None
        finally:
            ctx.close()

    async def fetch_multi(
        self, tickers: List[str], days: int = 20
    ) -> Dict[str, Optional[FundFlowResult]]:
        """Fetch fund flow for multiple tickers concurrently."""
        results = {}
        # Futu rate limit: ~10 req/s is safe
        sem = asyncio.Semaphore(5)

        async def _fetch_one(ticker: str) -> tuple:
            async with sem:
                result = await self.fetch(ticker, days=days)
                return ticker, result

        tasks = [_fetch_one(t) for t in tickers]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        for item in gathered:
            if isinstance(item, Exception):
                logger.error("Batch fetch error: %s", item)
                continue
            ticker, result = item
            results[ticker] = result

        return results

    async def close(self):
        """No-op — each call opens/closes its own connection."""
        pass


# ---------------------------------------------------------------------------
# Divergence signal — same algorithm as eastmoney_fetcher.py
# ---------------------------------------------------------------------------


def compute_divergence_signal(days: List[FundFlowDay]) -> dict:
    """Compute price vs fund-flow divergence signal from recent days.

    Returns dict with keys:
      signal: "bullish_divergence" | "bearish_divergence" | "confirmation" | "none"
      strength: 0-100
      detail: one-line summary
    """
    if len(days) < 3:
        return {"signal": "none", "strength": 0, "detail": "insufficient data"}

    # Look at last 3 trading days
    recent = days[-3:]

    price_direction = 0
    flow_direction = 0
    divergent_count = 0

    for i in range(1, len(recent)):
        prev, curr = recent[i - 1], recent[i]

        price_delta = curr.change_pct - prev.change_pct
        flow_delta = curr.main_net - prev.main_net

        if price_delta != 0:
            price_direction += 1 if price_delta > 0 else -1
        if flow_delta != 0:
            flow_direction += 1 if flow_delta > 0 else -1

        # Divergence: price up but main force selling (or vice versa)
        if price_delta > 0 and flow_delta < 0:
            divergent_count += 1  # bearish: price up, money out
        elif price_delta < 0 and flow_delta > 0:
            divergent_count += 1  # bullish: price down, money in

    # Determine signal
    if divergent_count >= 2:
        if price_direction < 0 and flow_direction > 0:
            signal = "bullish_divergence"
            detail = f"价格下跌但主力连续{divergent_count}日净流入，底背离信号"
        elif price_direction > 0 and flow_direction < 0:
            signal = "bearish_divergence"
            detail = f"价格上涨但主力连续{divergent_count}日净流出，顶背离信号"
        else:
            signal = "divergence"
            detail = f"价格与资金流向{divergent_count}日背离"
        strength = min(divergent_count * 35, 100)
    elif divergent_count == 1:
        signal = "warning"
        detail = "出现1日背离，关注后续确认"
        strength = 30
    elif price_direction != 0 and flow_direction != 0 and price_direction == flow_direction:
        signal = "confirmation"
        direction = "看涨" if price_direction > 0 else "看跌"
        detail = f"价格与资金方向一致（{direction}），趋势确认"
        strength = 60
    else:
        signal = "none"
        detail = "无明显背离信号"
        strength = 0

    return {"signal": signal, "strength": strength, "detail": detail}
