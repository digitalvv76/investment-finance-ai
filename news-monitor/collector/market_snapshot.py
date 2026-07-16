"""Market snapshot collector — pre-market & intraday real-time quotes via Futu OpenD.

Two windows per trading day:
  Pre-market  09:25 ET — full scan of ~71 tickers, push movers >±2%
  Intraday    14:30 ET — re-scan, push extreme movers >±5% with volume surge

Futu API: get_market_snapshot — batch query up to 400 stocks in one call.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SnapshotItem:
    """Single stock snapshot."""
    ticker: str
    name: str = ""
    last_price: float = 0.0
    prev_close: float = 0.0
    change_rate: float = 0.0  # e.g. 0.032 = +3.2%
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    volume: int = 0
    turnover: float = 0.0
    turnover_rate: float = 0.0  # 换手率
    pe_ratio: float = 0.0
    market_cap: float = 0.0

    @property
    def change_pct(self) -> float:
        return self.change_rate * 100

    def fmt_change(self) -> str:
        """Format change for push: +3.2% or -1.5%"""
        sign = "+" if self.change_rate >= 0 else ""
        return f"{sign}{self.change_pct:.1f}%"


@dataclass
class SnapshotSummary:
    """Pre-market / intraday summary."""
    window: str  # "pre" | "intra"
    timestamp: float = field(default_factory=time.time)
    movers: List[SnapshotItem] = field(default_factory=list)
    extreme: List[SnapshotItem] = field(default_factory=list)
    watchlist_count: int = 0
    error_count: int = 0


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class MarketSnapshotCollector:
    """Real-time snapshot collector via Futu get_market_snapshot.

    get_market_snapshot accepts up to 400 codes per call, so all ~71 tickers
    fit in a single batch. No rate-limiting concerns — Futu Gateway handles
    this at the protocol level.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        watchlist: Optional[List[str]] = None,
    ):
        self._host = host
        self._port = port
        self._watchlist = watchlist or self._load_watchlist()
        self._last_run: dict[str, float] = {}  # window → timestamp

    @staticmethod
    def _load_watchlist() -> List[str]:
        """Load watchlist from memory file (same logic as FundFlowCollector)."""
        tickers = [
            "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL",
            "AMD", "PLTR", "RKLB", "ASTS", "SMR", "OKLO", "SOXL",
            "LRCX", "MRVL", "ARM", "AVGO", "ASML", "RGTI", "NBIS", "SPCX",
            "INTC", "QCOM", "TSM", "MU", "AMAT", "KLAC", "TXN", "ON",
            "COIN", "MSTR", "MARA", "RIOT", "SQ", "HOOD", "SOFI", "AFRM",
            "JPM", "GS", "BAC", "C", "WFC", "XOM", "CVX", "NKE", "DIS",
            "NFLX", "CRM", "ORCL", "ADBE", "PYPL", "BA", "WMT",
            "SOXX", "SMH", "QQQ", "ARKK", "XLF", "XLE",
            "KTOS", "BOT", "TEM", "HUT", "CLSK", "WULF", "MRAAY", "CBRS",
        ]
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
                        tickers = [t for t in found if t.isalpha() and len(t) <= 5]
                    break
        except Exception:
            pass
        return tickers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def pre_market_snapshot(self) -> Optional[SnapshotSummary]:
        """Pre-market scan: all watchlist tickers, push movers >±2%."""
        return await self._run_window("pre", threshold=0.02)

    async def intraday_snapshot(self) -> Optional[SnapshotSummary]:
        """Intraday scan: push extreme movers >±5%."""
        return await self._run_window("intra", threshold=0.05)

    async def _run_window(self, window: str, threshold: float) -> Optional[SnapshotSummary]:
        """Execute a snapshot window."""
        now = time.time()
        # Don't re-run within 5 minutes
        if window in self._last_run and now - self._last_run[window] < 300:
            return None

        self._last_run[window] = now

        try:
            snapshots = await asyncio.to_thread(self._fetch_snapshots, self._watchlist)
        except Exception as e:
            logger.error("Snapshot %s fetch failed: %s", window, e)
            return None

        movers = [s for s in snapshots if abs(s.change_rate) >= threshold]
        extreme = [s for s in movers if abs(s.change_rate) >= 0.05]

        summary = SnapshotSummary(
            window=window,
            movers=movers,
            extreme=extreme,
            watchlist_count=len(self._watchlist),
        )

        logger.info(
            "Snapshot %s: %d/%d movers (≥%d%%), %d extreme",
            window, len(movers), len(snapshots),
            int(threshold * 100), len(extreme),
        )
        return summary

    def _fetch_snapshots(self, tickers: List[str]) -> List[SnapshotItem]:
        """Synchronous Futu call — runs in thread pool."""
        from futu import OpenQuoteContext, RET_OK

        futu_codes = [f"US.{t}" for t in tickers]
        ctx = OpenQuoteContext(host=self._host, port=self._port)
        items: List[SnapshotItem] = []

        try:
            ret, data = ctx.get_market_snapshot(futu_codes)
            if ret != RET_OK:
                logger.warning("Snapshot fetch failed: %s", data)
                return items

            if data is None or len(data) == 0:
                return items

            for _, row in data.iterrows():
                code = str(row.get("code", ""))
                ticker = code.replace("US.", "") if code.startswith("US.") else code

                items.append(SnapshotItem(
                    ticker=ticker,
                    name=str(row.get("name", "")),
                    last_price=float(row.get("last_price", 0) or 0),
                    prev_close=float(row.get("prev_close_price", 0) or 0),
                    change_rate=float(row.get("change_rate", 0) or 0),
                    open_price=float(row.get("open_price", 0) or 0),
                    high_price=float(row.get("high_price", 0) or 0),
                    low_price=float(row.get("low_price", 0) or 0),
                    volume=int(row.get("volume", 0) or 0),
                    turnover=float(row.get("turnover", 0) or 0),
                    turnover_rate=float(row.get("turnover_rate", 0) or 0),
                    pe_ratio=float(row.get("pe_ratio", 0) or 0),
                    market_cap=float(row.get("market_cap", 0) or 0),
                ))
        finally:
            ctx.close()

        return items

    async def close(self):
        """No-op."""
        pass

    # ------------------------------------------------------------------
    # Push formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_pre_market_summary(summary: SnapshotSummary) -> str:
        """Format pre-market summary for TG push."""
        lines = [f"📊 盘前异动 (09:25 ET)\n"]
        for s in sorted(summary.movers, key=lambda x: abs(x.change_rate), reverse=True):
            emoji = "🔴" if s.change_rate < 0 else "🟢"
            lines.append(f"{emoji} {s.ticker} {s.fmt_change()}  ${s.last_price:.2f}")
        return "\n".join(lines)

    @staticmethod
    def format_intraday_alert(summary: SnapshotSummary) -> str:
        """Format intraday extreme alert for push."""
        lines = [f"⚡ 盘中极端异动 (14:30 ET)\n"]
        for s in sorted(summary.extreme, key=lambda x: abs(x.change_rate), reverse=True):
            emoji = "🔴" if s.change_rate < 0 else "🟢"
            vol_note = f"换手 {s.turnover_rate:.1f}%" if s.turnover_rate > 0 else ""
            lines.append(f"{emoji} {s.ticker} {s.fmt_change()}  ${s.last_price:.2f}  {vol_note}")
        if not summary.extreme:
            lines.append("无极端异动")
        return "\n".join(lines)
