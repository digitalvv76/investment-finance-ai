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
    """Single day of money flow data.

    Analysis framework (user-defined):
      Anchor  — 特大单 (super_big): single trade ≥ 100万 CNY equivalent.
                Institutions cannot hide block trades; this is the ONE signal
                that cannot be faked.
      主力     — 特大单 + 大单 combined. Prevents institutions from hiding
                behind order-splitting (拆单). Used for participation ratio.
      中单/小单 — Retail sentiment confirmation (reverse indicator).

    Futu raw fields are mapped as follows:
      Futu main_in_flow  → main_net (★ 主力 = Futu官方"主力大单", 回退super+big)
      Futu super_in_flow → super_big_net  (the anchor — 特大单)
      Futu big_in_flow   → big_net
      Futu mid_in_flow   → mid_net
      Futu sml_in_flow   → sml_net

    main_net = Futu main_in_flow (historical) or super+big (intraday fallback).
    """

    date: str
    main_net: float = 0.0        # 主力 = Futu main_in_flow (官方定义), 回退 super+big
    main_in_flow: float = 0.0    # Futu官方"主力大单净流入"（仅历史周期有效）
    super_big_net: float = 0.0   # ★ 特大单 (THE anchor — Futu: super_in_flow)
    big_net: float = 0.0         # 大单 (Futu: big_in_flow)
    mid_net: float = 0.0         # 中单 (Futu: mid_in_flow)
    small_net: float = 0.0       # 小单 (Futu: sml_in_flow)
    main_pct: float = 0.0        # 主力占比 = main_net / abs(total) * 100

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

        # Retry transient failures (network jitter, OpenD restart) with backoff.
        # 3 attempts: immediate → 1s → 2s.  Graceful — a single retry rescues
        # most transient errors without slowing the 71-ticker batch meaningfully.
        last_err = None
        for attempt in range(3):
            try:
                result = await asyncio.to_thread(self._fetch_sync, futu_code, ticker, days, market)
                if result is not None:
                    self._cache.set(cache_key, result)
                    return result
                # _fetch_sync returned None (e.g. empty data) — not retry-worthy
                return None
            except Exception as e:
                last_err = e
                if attempt < 2:
                    delay = [0, 1, 2][attempt]
                    if delay:
                        await asyncio.sleep(delay)
                    logger.debug("Futu fetch retry %d/3 for %s: %s", attempt + 1, ticker, e)

        logger.error("Futu fetch failed after 3 retries for %s: %s", ticker, last_err)
        return None

    def _fetch_sync(
        self, futu_code: str, ticker: str, days: int, market: str
    ) -> Optional[FundFlowResult]:
        """Synchronous Futu API call — runs in thread pool."""
        from futu import OpenQuoteContext, PeriodType, RET_OK, KLType, AuType

        ctx = OpenQuoteContext(host=self._host, port=self._port)
        try:
            # Calculate date range
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime(
                "%Y-%m-%d"
            )  # extra buffer for non-trading days

            # ---- Capital flow ----
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

            # ---- Price data via history K-line (Futu native, no subscription) ----
            price_map: dict[str, dict] = {}  # "2026-07-14" → {close, change_rate}
            name = ""
            try:
                ret_k, kline, _ = ctx.request_history_kline(
                    futu_code,
                    start=start_date,
                    end=end_date,
                    ktype=KLType.K_DAY,
                    autype=AuType.QFQ,
                    max_count=days + 5,
                )
                if ret_k == RET_OK and len(kline) > 0:
                    for _, kr in kline.iterrows():
                        kdate = str(kr.get("time_key", ""))
                        if " " in kdate:
                            kdate = kdate.split(" ")[0]
                        price_map[kdate] = {
                            "close": float(kr.get("close", 0) or 0),
                            "change_rate": float(kr.get("change_rate", 0) or 0),
                        }
                else:
                    logger.warning(
                        "Futu K-line empty for %s: ret=%s rows=%s",
                        futu_code, ret_k, len(kline) if kline is not None else 0,
                    )
            except Exception as e:
                logger.warning("Futu K-line failed for %s: %s", futu_code, e)

            # Stock name from snapshot
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

                    super_in = float(row.get("super_in_flow", 0) or 0)
                    big_in = float(row.get("big_in_flow", 0) or 0)
                    mid_in = float(row.get("mid_in_flow", 0) or 0)
                    sml_in = float(row.get("sml_in_flow", 0) or 0)
                    futu_main = float(row.get("main_in_flow", 0) or 0)

                    # ★ 主力 = Futu官方 main_in_flow（主力大单净流入），回退 super+big
                    main_net = futu_main if futu_main != 0 else (super_in + big_in)

                    # 主力占比 = main_net / 总成交绝对值 * 100
                    # Denominator: gross turnover — net flow can be near-zero
                    # when tiers cancel, producing nonsensical percentages.
                    total_abs = (
                        abs(super_in) + abs(big_in)
                        + abs(mid_in) + abs(sml_in)
                    )
                    if total_abs > 0:
                        main_pct = (main_net / total_abs) * 100
                    else:
                        main_pct = 0.0

                    # Populate price from kline lookup
                    price_info = price_map.get(flow_time, {})
                    close_price = price_info.get("close", 0.0)
                    change_pct = price_info.get("change_rate", 0.0)

                    fd = FundFlowDay(
                        date=flow_time,
                        main_net=main_net,
                        main_in_flow=futu_main,      # Futu官方主力定义
                        super_big_net=super_in,       # ★ anchor
                        big_net=big_in,
                        mid_net=mid_in,
                        small_net=sml_in,
                        main_pct=round(main_pct, 2),
                        close_price=close_price,
                        change_pct=change_pct,
                    )
                    parsed_days.append(fd)
                except Exception as e:
                    logger.debug("Skipping row for %s: %s", futu_code, e)
                    continue

            if not parsed_days:
                return None

            # Return last N days
            parsed_days = parsed_days[-days:]

            # K-line subscription check: if ALL change_pct are zero, the
            # kline API likely failed silently (no market data subscription).
            if parsed_days and all(d.change_pct == 0 for d in parsed_days):
                logger.warning(
                    "Futu: ALL kline change_pct=0 for %s (%s) — "
                    "market data subscription may be missing. "
                    "Price-dependent signals (divergence, retail_trap, "
                    "golden_pit) will be degraded.",
                    ticker, futu_code,
                )

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
        # Futu rate limit: 30 req per 30 seconds → 1 req/s max
        sem = asyncio.Semaphore(1)

        async def _fetch_one(ticker: str) -> tuple:
            async with sem:
                result = await self.fetch(ticker, days=days)
                await asyncio.sleep(1.0)  # P0: 1 req/s, 30/min at Futu limit
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
    """Compute price vs fund-flow divergence signal — 5-law framework.

    ★ Anchor: 特大单 (super_big_net).
    主力 = super+big for participation ratio (V2.1 P0 anti-splitting).

    Five laws from user training data:
      E. 合力检测 — all 4 tiers same direction = healthy; only retail = trap
      F. 散户陷阱 — price up + super flat/out + small crazy in = downgrade ×2
      G. 黄金坑 — extreme drop + tiny outflow + super buying = stronger than normal divergence

    Returns: {signal, strength, detail, details, laws}
    """

    if len(days) < 3:
        return {"signal": "insufficient_data", "strength": 0, "detail": "insufficient data"}

    recent = days[-3:]
    latest = recent[-1]

    # --- Backfill change_pct from close_price when missing (DB reconstruction) ---
    for i, d in enumerate(recent):
        if d.change_pct == 0 and d.close_price != 0 and i > 0:
            prev_close = recent[i - 1].close_price
            if prev_close != 0:
                d.change_pct = (d.close_price - prev_close) / prev_close * 100

    # --- Anchor: 特大单 ---
    cum_super_big = sum(d.super_big_net for d in recent)
    cum_main = sum(d.main_net for d in recent)
    cum_small = sum(d.small_net for d in recent)
    cum_mid = sum(d.mid_net for d in recent)
    cum_big = sum(d.big_net for d in recent)

    # True cumulative return from close prices (preferred over sum-of-pcts
    # which amplifies error for volatile/leveraged tickers).
    closes = [d.close_price for d in recent if d.close_price != 0]
    if len(closes) >= 2 and closes[0] != 0:
        cum_price = (closes[-1] - closes[0]) / closes[0] * 100
    else:
        cum_price = sum(d.change_pct for d in recent if d.change_pct != 0)

    super_directions = [1 if d.super_big_net > 0 else -1 if d.super_big_net < 0 else 0 for d in recent]
    super_continuity = sum(super_directions)

    # --- Divergence detection ---
    price_direction = 0
    flow_direction = 0
    divergent_count = 0

    for i in range(1, len(recent)):
        prev, curr = recent[i - 1], recent[i]
        price_delta = curr.change_pct - prev.change_pct
        flow_delta = curr.super_big_net - prev.super_big_net  # ★ Anchor

        if price_delta != 0:
            price_direction += 1 if price_delta > 0 else -1
        if flow_delta != 0:
            flow_direction += 1 if flow_delta > 0 else -1

        if price_delta > 0 and flow_delta < 0:
            divergent_count += 1
        elif price_delta < 0 and flow_delta > 0:
            divergent_count += 1

    # -------------------------------------------------------------------
    # New Law checks
    # -------------------------------------------------------------------

    # Law E: 合力检测 — are all 4 tiers aligned?
    all_tiers = [cum_super_big, cum_big, cum_mid, cum_small]
    all_positive = all(t > 0 for t in all_tiers)
    all_negative = all(t < 0 for t in all_tiers)
    retail_only_positive = cum_small > 0 and cum_mid > 0 and cum_super_big <= 0
    retail_only_selling = cum_small < 0 and cum_mid < 0 and cum_super_big >= 0

    # Law F: 散户陷阱 — price up but super flat/out, small crazy in.
    # When super_big is exactly zero, abs(0)*3 = 0, so ANY positive
    # cum_small would trigger → false positive.  Require a minimum
    # retail inflow of at least 1% of total absolute turnover.
    total_abs = sum(abs(d.super_big_net) + abs(d.big_net) + abs(d.mid_net) + abs(d.small_net) for d in recent)
    min_retail_threshold = total_abs * 0.01  # at least 1% of total turnover
    retail_trap = (
        cum_price > 5
        and cum_super_big <= 0
        and cum_small > max(abs(cum_super_big) * 3, min_retail_threshold)
    )

    # Law G: 黄金坑 — extreme drop + tiny outflow + super buying.
    # Reuses total_abs from retail_trap check above (per-day gross turnover).
    golden_pit = (
        cum_price < -10
        and cum_super_big > 0
        and total_abs < abs(cum_super_big) * 5
    )

    # -------------------------------------------------------------------
    # Signal determination
    # -------------------------------------------------------------------
    signal = "none"
    strength = 0
    detail = ""
    modifiers = []

    if divergent_count >= 2:
        if price_direction < 0 and flow_direction > 0:
            signal = "bullish_divergence"
            base_strength = min(divergent_count * 35, 100)
            if golden_pit:
                strength = min(base_strength + 20, 100)
                detail = f"★黄金坑★ 暴跌{abs(cum_price):.0f}%但特大单逆势净流入{cum_super_big/1e4:.0f}万，空头力竭+机构吸筹，强底背离"
                modifiers.append("golden_pit")
            else:
                strength = base_strength
                detail = f"价格下跌但特大单连续{divergent_count}日逆势净流入，底背离信号"
        elif price_direction > 0 and flow_direction < 0:
            signal = "bearish_divergence"
            if retail_trap:
                strength = min(divergent_count * 35 + 20, 100)
                detail = f"★散户陷阱★ 股价上涨但特大单未参与，小单疯狂流入{cum_small/1e4:.0f}万→诱多，强顶背离"
                modifiers.append("retail_trap")
            else:
                strength = min(divergent_count * 35, 100)
                detail = f"价格上涨但特大单连续{divergent_count}日逆势净流出，顶背离信号"
        else:
            signal = "divergence"
            detail = f"价格与特大单流向{divergent_count}日背离"
            strength = min(divergent_count * 35, 100)
    elif divergent_count == 1:
        signal = "warning"
        detail = "特大单出现1日背离，关注后续确认"
        strength = 30
        if golden_pit:
            strength += 15
            modifiers.append("golden_pit_partial")
    elif all_positive and cum_price > 0:
        signal = "confirmation"
        detail = f"四维共振：特大/大/中/小全净流入，健康上涨，趋势延续"
        strength = 75
        modifiers.append("all_tiers_aligned_up")
    elif all_negative and cum_price < 0:
        signal = "confirmation"
        detail = f"四维共振：特大/大/中/小全净流出，一致抛售，趋势延续"
        strength = 75
        modifiers.append("all_tiers_aligned_down")
    elif retail_only_positive:
        signal = "warning"
        detail = f"散户独舞：仅中单/小单净流入，特大单未参与→上涨不可持续，警惕诱多"
        strength = 40
        modifiers.append("retail_only")
    elif retail_only_selling:
        signal = "warning"
        detail = f"散户恐慌：仅中单/小单净流出，特大单未跟→可能为洗盘尾声"
        strength = 35
        modifiers.append("retail_panic")
    elif price_direction != 0 and flow_direction != 0 and price_direction == flow_direction:
        signal = "confirmation"
        direction = "看涨" if price_direction > 0 else "看跌"
        detail = f"价格与特大单方向一致（{direction}），趋势确认"
        strength = 60
    else:
        signal = "none"
        detail = "特大单无明显背离信号"
        strength = 0

    # V2.5: standardized strength tier
    if strength >= 70:
        final_strength = "STRONG"
    elif strength >= 40:
        final_strength = "STANDARD"
    else:
        final_strength = "WEAK"

    return {
        "signal": signal, "strength": strength, "final_strength": final_strength,
        "detail": detail,
        "details": {
            "continuity": (
                "continuous_inflow" if super_continuity >= 2
                else "continuous_outflow" if super_continuity <= -2
                else "mixed"
            ),
            "participation": (
                "extreme" if abs(latest.main_pct) > 15
                else "strong" if abs(latest.main_pct) > 8
                else "normal" if abs(latest.main_pct) > 3
                else "low"
            ),
            "cum_main_3d": cum_main,
            "cum_super_big_3d": cum_super_big,
            "latest_main_pct": latest.main_pct,
            "all_tiers_aligned": all_positive or all_negative,
            "retail_trap": retail_trap,
            "golden_pit": golden_pit,
            "modifiers": modifiers,
        },
    }
