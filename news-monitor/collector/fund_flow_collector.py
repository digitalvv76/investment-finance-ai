"""Fund flow collector — daily post-market capital flow data pipeline.

Wires the EastMoneyFundFlowFetcher into the system: fetch → persist →
compute divergence signal → push extreme signals.

This is NOT part of NewsScheduler because fund flow data is daily
(post-market close), not real-time news. It runs as a separate
background loop in main.py, following the ImpactCollector pattern.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from collector.eastmoney_fetcher import (
    EastMoneyFundFlowFetcher,
    FundFlowResult,
    compute_divergence_signal,
)
from storage.database import Database
from storage.models import FundFlowRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback watchlist — used when neither config nor watchlist-state.md has
# tickers.  Covers the user's active positions + watchlist.
# ---------------------------------------------------------------------------
_FALLBACK_WATCHLIST = [
    "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL",
    "AMD", "PLTR", "RKLB", "ASTS", "SMR", "OKLO", "SOXL",
    "LRCX", "MRVL", "ARM", "AVGO", "ASML", "RGTI", "NBIS", "SPCX",
]


@dataclass
class FundFlowSignal:
    """Computed signal from a ticker's fund flow data."""
    ticker: str
    continuity: str          # "continuous_inflow" | "continuous_outflow" | "mixed"
    participation: str       # "extreme" | "strong" | "normal" | "low"
    cum_super_big_3d: float  # 3-day cumulative super-big net (CNY)
    cum_main_3d: float       # 3-day cumulative main net (CNY)
    latest_main_pct: float   # latest day main_pct


class FundFlowCollector:
    """Daily post-market fund flow collection + signal dispatch.

    Owns an EastMoneyFundFlowFetcher instance and wires it into the
    storage + alerting subsystems.  Designed to be called once per
    trading day (after US market close, ~5pm ET).
    """

    def __init__(
        self,
        db: Database,
        alert_dispatcher=None,          # AlertDispatcher (for Pushover)
        bot=None,                        # NewsBot (for Telegram)
        proxy: str = "",
        watchlist: Optional[list[str]] = None,
        days_to_fetch: int = 20,
    ):
        self._db = db
        self._dispatcher = alert_dispatcher
        self._bot = bot
        self._days = days_to_fetch
        self._fetcher = EastMoneyFundFlowFetcher(proxy=proxy)

        # Resolve watchlist: explicit → watchlist-state.md → fallback
        if watchlist:
            self._watchlist = [t.upper() for t in watchlist]
        else:
            self._watchlist = [t.upper() for t in self._load_watchlist_from_memory()]

        self._last_run_date: Optional[str] = None  # "YYYY-MM-DD" in ET

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def collect_once(self) -> int:
        """Fetch fund flow for all watchlist tickers, persist, push signals.

        Returns the number of strong signals pushed.
        """
        tickers = self._watchlist
        logger.info("FundFlow: collecting for %d tickers (days=%d)",
                     len(tickers), self._days)

        results = await self._fetcher.fetch_multi(tickers, days=self._days)

        all_signals: list[FundFlowSignal] = []
        persisted = 0
        for ticker, result in results.items():
            if result is None:
                continue
            await self._persist_result(result)
            persisted += 1
            signals = self._compute_signals(result)
            all_signals.extend(signals)

        logger.info("FundFlow: persisted %d tickers, %d signals",
                     persisted, len(all_signals))

        pushed = await self._push_signals(all_signals)
        self._last_run_date = self._et_today_str()
        return pushed

    def should_run_today(self) -> bool:
        """Check if we should collect today.

        Conditions:
        1. Today is a US trading day.
        2. Current US Eastern Time hour >= 17 (5pm, after 4pm close).
        3. Has not already run today.
        """
        today_str = self._et_today_str()
        if self._last_run_date == today_str:
            return False

        try:
            from collector.exchange_calendar import ExchangeCalendar
            if not ExchangeCalendar().is_trading_day():
                return False
        except Exception:
            pass  # calendar unavailable → proceed

        now_et = datetime.now(timezone.utc) - timedelta(hours=_et_offset_hours())
        return now_et.hour >= 17

    async def close(self):
        """Release the underlying aiohttp session."""
        await self._fetcher.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _persist_result(self, result: FundFlowResult):
        """Upsert FundFlowDay rows into the fund_flow table."""
        for day in result.days:
            record = FundFlowRecord(
                ticker=result.ticker,
                date=day.date,
                main_net=day.main_net,
                super_big_net=day.super_big_net,
                big_net=day.big_net,
                mid_net=day.mid_net,
                small_net=day.small_net,
                main_pct=day.main_pct,
                source=result.source,
                fetched_at=result.fetched_at,
            )
            self._db.upsert_fund_flow(record)

    def _compute_signals(self, result: FundFlowResult) -> list[FundFlowSignal]:
        """Compute divergence signal for a single ticker's result."""
        signal_dict = compute_divergence_signal(result.days)
        if signal_dict["signal"] == "insufficient_data":
            return []

        details = signal_dict["details"]
        return [FundFlowSignal(
            ticker=result.ticker,
            continuity=details.get("continuity", "mixed"),
            participation=details.get("participation", "low"),
            cum_super_big_3d=details.get("cum_super_big_3d", 0.0),
            cum_main_3d=details.get("cum_main_3d", 0.0),
            latest_main_pct=details.get("latest_main_pct", 0.0),
        )]

    async def _push_signals(self, signals: list[FundFlowSignal]) -> int:
        """Push strong signals. Returns count of pushed signals."""
        pushed = 0
        for s in signals:
            if s.participation == "extreme":
                await self._push_extreme(s)
                pushed += 1
            elif s.participation == "strong":
                await self._push_strong(s)
                pushed += 1
            # normal/low: DB only, no push
        return pushed

    async def _push_extreme(self, s: FundFlowSignal):
        """Extreme participation → Pushover + Telegram (loud)."""
        direction = "流入" if s.cum_super_big_3d > 0 else "流出"
        emoji = "🟢" if s.cum_super_big_3d > 0 else "🔴"
        title = f"{emoji} 主力持续{direction} {s.ticker}"
        body = (
            f"3日超大单净{direction} ¥{abs(s.cum_super_big_3d)/1e8:.1f}亿, "
            f"主力占比 {s.latest_main_pct:.1f}%"
        )

        # Pushover
        if self._dispatcher:
            try:
                await self._dispatcher.send_system_alert(
                    title, body, emergency=False, quiet=False,
                )
            except Exception:
                logger.exception("FundFlow: Pushover push failed for %s", s.ticker)

        # Telegram
        if self._bot:
            try:
                await self._bot.send_message(
                    chat_id=self._bot._primary_chat_id,
                    text=f"{title}\n{body}",
                    disable_notification=False,
                )
            except Exception:
                logger.exception("FundFlow: Telegram push failed for %s", s.ticker)

    async def _push_strong(self, s: FundFlowSignal):
        """Strong participation → Telegram only (silent)."""
        direction = "流入" if s.cum_super_big_3d > 0 else "流出"
        text = (
            f"📊 主力持续{direction} {s.ticker}\n"
            f"3日超大单净{direction} ¥{abs(s.cum_super_big_3d)/1e8:.1f}亿, "
            f"主力占比 {s.latest_main_pct:.1f}%"
        )
        if self._bot:
            try:
                await self._bot.send_message(
                    chat_id=self._bot._primary_chat_id,
                    text=text,
                    disable_notification=True,
                )
            except Exception:
                logger.exception("FundFlow: Telegram silent push failed for %s", s.ticker)

    @staticmethod
    def _load_watchlist_from_memory() -> list[str]:
        """Load watchlist from .claude/memory/watchlist-state.md.

        Mirrors the pattern in NewsScheduler._load_watchlist().
        """
        try:
            from pathlib import Path
            import re
            module_file = Path(__file__).resolve()
            for offset in (2, 3):
                candidate = module_file.parents[offset] / ".claude" / "memory" / "watchlist-state.md"
                if candidate.exists():
                    content = candidate.read_text()
                    found = re.findall(r'\|\s*([A-Z]{1,5})\s*\|', content)
                    if found:
                        return [t for t in found if t.isalpha() and len(t) <= 5]
                    break
        except Exception:
            pass
        return _FALLBACK_WATCHLIST

    @staticmethod
    def _et_today_str() -> str:
        """Return today's date in US Eastern Time as 'YYYY-MM-DD'."""
        now_utc = datetime.now(timezone.utc)
        offset = timedelta(hours=_et_offset_hours())
        return (now_utc - offset).strftime("%Y-%m-%d")


def _et_offset_hours() -> int:
    """Quick US Eastern Time offset from UTC (standard=-5, daylight=-4).

    Accurate enough for the daily post-market check — we don't need
    full zoneinfo here.
    """
    now = datetime.now(timezone.utc)
    year = now.year
    # US DST: second Sunday March → first Sunday November
    mar = datetime(year, 3, 14, tzinfo=timezone.utc)
    nov = datetime(year, 11, 7, tzinfo=timezone.utc)
    dst_start = 14 - ((mar.weekday() + 1) % 7)  # second Sunday
    dst_end = 7 - ((nov.weekday() + 1) % 7)      # first Sunday
    if (now.month > 3 and now.month < 11) or \
       (now.month == 3 and now.day >= dst_start) or \
       (now.month == 11 and now.day < dst_end):
        return 4   # EDT (UTC-4)
    return 5       # EST (UTC-5)
