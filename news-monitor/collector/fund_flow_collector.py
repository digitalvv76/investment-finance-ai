"""Fund flow collector — daily post-market capital flow data pipeline.

Wires the FutuFundFlowFetcher into the system: fetch → persist →
compute divergence signal → LLM analysis (Prompt v2) → push.

This is NOT part of NewsScheduler because fund flow data is daily
(post-market close), not real-time news. It runs as a separate
background loop in main.py, following the ImpactCollector pattern.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import yfinance as yf

from collector.futu_fetcher import (
    FutuFundFlowFetcher,
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

# ---------------------------------------------------------------------------
# Prompt v2 — the divergence analysis framework
# ---------------------------------------------------------------------------
_PROMPT_V2_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "prompts", "fund_flow_v2.txt",
)


def _load_prompt_v2() -> str:
    """Load Prompt v2 from disk; fall back to inline copy."""
    try:
        p = os.path.normpath(_PROMPT_V2_PATH)
        if os.path.exists(p):
            return open(p, encoding="utf-8").read()
    except Exception:
        pass
    # Inline fallback — short version of the key instructions
    return (
        "你是一位拥有15年美股/港股市场经验的专业资金流分析师。\n"
        "核心信念：不看单日涨跌，看涨跌与特大单流向是否一致。"
        "一致 = 趋势延续；背离 = 拐点临近。\n\n"
        "⚠️ 分析锚点是「特大单」列。第3列「主力净流入」=特大单+大单的合计（防拆单）。\n\n"
        "## 六大法则\n"
        "A. 小单反向确认：背离+小单反向=增强，同向=降级\n"
        "B. 连续性确认：特大单连续3日同向>单日\n"
        "C. 主力占比定强度：<1%降级, 1-5%维持, 5-10%升级, >10%极端\n"
        "D. 合力检测：四维共振(全部同向)=健康, 仅散户独舞=危险\n"
        "E. 散户陷阱：涨>5%+特大单不动/流出+小单疯狂流入→诱多, 降两级\n"
        "F. 黄金坑：跌<-10%+流出极小+特大单逆势流入→强底部, 升一级\n\n"
        "## 输出要求\n"
        "先输出「核心信号」1-2句（有/无背离，方向，强度），"
        "再输出完整分析（趋势定位→背离细节→辅助确认→情景推演→验证条件）。"
    )


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class FundFlowSignal:
    """Computed signal from a ticker's fund flow data.

    ★ Anchor: 特大单 (super_big_net) — the signal that can't be faked.
    主力 = 特大单+大单 (V2.1 P0: anti-splitting).
    主力占比 = (特大+大) / abs(total) * 100.
    """

    ticker: str
    continuity: str          # "continuous_inflow" | "continuous_outflow" | "mixed"
    participation: str       # "extreme" | "strong" | "normal" | "low"
    cum_main_3d: float       # 3-day 主力 (super+big) cumulative
    cum_super_big_3d: float  # 3-day ★ 特大单 cumulative (the anchor)
    latest_main_pct: float   # 主力占比 = (super+big) / abs(total) * 100
    price_change_3d: float = 0.0       # 3-day cumulative price change (%)
    price_data: list[dict] = field(default_factory=list)  # [{date, close}]
    fund_flow_days: list = field(default_factory=list)    # FundFlowDay objects
    analysis_summary: str = ""         # LLM 主要观点
    analysis_full: str = ""            # LLM 完整报告
    silenced: bool = False             # true = 财报静默期内，仅入库不推送


# ---------------------------------------------------------------------------
# FundFlowCollector
# ---------------------------------------------------------------------------

class FundFlowCollector:
    """Daily fund flow collection + LLM analysis — two windows per trading day.

    Window 1 — Post-market (~17:00 ET): fetch fresh data from Futu,
    persist to DB, compute signals, run LLM analysis, push.

    Window 2 — Pre-market (~08:00 ET next trading day): re-read yesterday's
    data from DB, re-fetch prices (pre-market may have moved), re-run LLM
    with updated context, push if signal is still valid.
    """

    WINDOW_POST = "post"       # 17:00 ET — full collect + analyze
    WINDOW_PRE = "pre"         # 08:00 ET — re-analyze from DB

    def __init__(
        self,
        db: Database,
        alert_dispatcher=None,          # AlertDispatcher (for Pushover)
        bot=None,                        # NewsBot (for Telegram)
        futu_host: str = "127.0.0.1",
        futu_port: int = 11111,
        watchlist: Optional[list[str]] = None,
        days_to_fetch: int = 20,
    ):
        self._db = db
        self._dispatcher = alert_dispatcher
        self._bot = bot
        self._days = days_to_fetch
        self._fetcher = FutuFundFlowFetcher(host=futu_host, port=futu_port)

        # Resolve watchlist: explicit → watchlist-state.md → fallback
        if watchlist:
            self._watchlist = [t.upper() for t in watchlist]
        else:
            self._watchlist = [t.upper() for t in self._load_watchlist_from_memory()]

        # Track which windows have already run today (ET date → set of windows)
        self._completed: dict[str, set[str]] = {}  # {"2026-07-15": {"post", "pre"}}

        # Batching — process N tickers per window to avoid rate limits
        self._batch_size = 20        # tickers per batch
        self._batch_index = 0        # next batch start position in watchlist
        self._batch_signals: list[FundFlowSignal] = []  # accumulated signals

        # LLM client (lazy init)
        self._llm_client = None
        self._llm_model = "deepseek-chat"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def collect_batch(self) -> int:
        """Post-market: fetch ONE batch of tickers, persist, analyze.

        Called repeatedly by the main loop until all tickers are done.
        Each batch is ~20 tickers; 71 tickers ≈ 4 batches over 2 hours.

        Returns the number of strong signals accumulated after the final batch,
        or 0 for intermediate batches.
        """
        start = self._batch_index
        end = min(start + self._batch_size, len(self._watchlist))
        batch = self._watchlist[start:end]
        is_last_batch = (end >= len(self._watchlist))

        logger.info("FundFlow[post]: batch %d/%d — %d tickers (%s → %s)",
                     start // self._batch_size + 1,
                     (len(self._watchlist) + self._batch_size - 1) // self._batch_size,
                     len(batch), batch[0] if batch else "?", batch[-1] if batch else "?")

        results = await self._fetcher.fetch_multi(batch, days=self._days)

        persisted = 0
        for ticker, result in results.items():
            if result is None:
                continue
            await self._persist_result(result)
            persisted += 1
            signals = self._compute_signals(result)
            self._batch_signals.extend(signals)

        logger.info("FundFlow[post]: batch persisted %d tickers, signals so far %d",
                     persisted, len(self._batch_signals))

        self._batch_index = end

        if is_last_batch:
            return await self._finalize_collect()
        return 0

    async def _finalize_collect(self) -> int:
        """Run LLM analysis on all accumulated signals, push, and mark done."""
        all_signals = self._batch_signals
        logger.info("FundFlow[post]: finalizing — %d total signals from %d batches",
                     len(all_signals),
                     (len(self._watchlist) + self._batch_size - 1) // self._batch_size)

        for s in all_signals:
            if s.participation in ("extreme", "strong"):
                await self._analyze_signal(s)
                await self._check_earnings_silence(s)

        pushed = await self._push_signals(all_signals)
        self._mark_done(self.WINDOW_POST)
        self._batch_index = 0
        self._batch_signals = []
        return pushed

    async def analyze_stored(self) -> int:
        """Pre-market: re-analyze yesterday's DB data with updated prices.

        Does NOT fetch from East Money — reads the latest date from fund_flow
        table for each ticker, rebuilds signals, re-fetches prices, re-runs
        LLM, and pushes if signals are still strong.

        Returns the number of signals pushed.
        """
        logger.info("FundFlow[pre]: re-analyzing from DB for %d tickers",
                     len(self._watchlist))

        all_signals: list[FundFlowSignal] = []
        for ticker in self._watchlist:
            rows = self._db.get_fund_flow(ticker, days=self._days)
            if len(rows) < 3:
                continue
            sig = self._reconstruct_signal(ticker, rows)
            if sig is not None:
                all_signals.append(sig)

        logger.info("FundFlow[pre]: %d signals from DB", len(all_signals))

        for s in all_signals:
            if s.participation in ("extreme", "strong"):
                await self._analyze_signal(s)
                await self._check_earnings_silence(s)

        pushed = await self._push_signals(all_signals, window=self.WINDOW_PRE)
        self._mark_done(self.WINDOW_PRE)
        return pushed

    def get_pending_window(self) -> Optional[str]:
        """Return which window should run now, or None.

        Post-market: 17:00–23:59 ET on trading days. Runs in batches — returns
        "post" repeatedly until all tickers are done, then stops.

        Pre-market: 05:00–09:29 ET on trading days. Single pass from DB.
        """
        if not self._is_trading_day():
            return None

        now_et = datetime.now(timezone.utc) - timedelta(hours=_et_offset_hours())
        today = (datetime.now(timezone.utc) - timedelta(hours=_et_offset_hours())).strftime("%Y-%m-%d")

        # Post-market: 17:00+
        if now_et.hour >= 17 and self.WINDOW_POST not in self._completed.get(today, set()):
            return self.WINDOW_POST

        # Pre-market: 05:00–09:29
        if 5 <= now_et.hour <= 9 and self.WINDOW_PRE not in self._completed.get(today, set()):
            return self.WINDOW_PRE

        return None

    async def close(self):
        """Release the underlying aiohttp session."""
        await self._fetcher.close()

    # ------------------------------------------------------------------
    # Earnings quiet-period check (P0-3: V2.1)
    # ------------------------------------------------------------------

    async def _check_earnings_silence(self, signal: FundFlowSignal):
        """Mark signal as silenced if within 3 trading days post-earnings."""
        try:
            ticker = signal.ticker
            stock = await asyncio.to_thread(lambda: yf.Ticker(ticker))
            cal = await asyncio.to_thread(lambda: stock.calendar)
            if cal is None or not isinstance(cal, dict):
                return

            # yfinance calendar: earnings dates as list of dicts or timestamps
            earnings_dates = []
            for key in ("Earnings Date", "Earnings High", "Earnings Low"):
                val = cal.get(key)
                if val is not None:
                    if isinstance(val, list):
                        earnings_dates.extend(val)
                    else:
                        earnings_dates.append(val)

            if not earnings_dates:
                return

            # Get the most recent past earnings date
            from datetime import date as date_type
            today = date_type.today()
            recent_earnings = None
            for ed in earnings_dates:
                if isinstance(ed, datetime):
                    ed_date = ed.date()
                elif hasattr(ed, "date"):
                    ed_date = ed.date()
                elif isinstance(ed, str):
                    ed_date = datetime.fromisoformat(ed[:10]).date()
                else:
                    continue
                if ed_date <= today:
                    if recent_earnings is None or ed_date > recent_earnings:
                        recent_earnings = ed_date

            if recent_earnings is None:
                return

            # Count trading days since earnings
            days_since = (today - recent_earnings).days
            # Approximate: if within 5 calendar days (~3 trading days)
            if days_since <= 5:
                signal.silenced = True
                logger.info(
                    "FundFlow: %s silenced — earnings %s (%d days ago)",
                    ticker, recent_earnings, days_since,
                )

        except Exception:
            # Earnings check failure should not block the signal
            pass

    # ------------------------------------------------------------------
    # Re-analysis from DB (pre-market window)
    # ------------------------------------------------------------------

    def _reconstruct_signal(
        self, ticker: str, rows: list[dict],
    ) -> Optional[FundFlowSignal]:
        """Rebuild a FundFlowSignal from stored DB rows."""
        from collector.futu_fetcher import FundFlowDay
        days = [
            FundFlowDay(
                date=r["date"], main_net=r["main_net"],
                super_big_net=r["super_big_net"], big_net=r["big_net"],
                mid_net=r["mid_net"], small_net=r["small_net"],
                main_pct=r["main_pct"],
            )
            for r in rows
        ]
        signal_dict = compute_divergence_signal(days)
        if signal_dict["signal"] == "insufficient_data":
            return None

        details = signal_dict["details"]
        return FundFlowSignal(
            ticker=ticker,
            continuity=details.get("continuity", "mixed"),
            participation=details.get("participation", "low"),
            cum_super_big_3d=details.get("cum_super_big_3d", 0.0),
            cum_main_3d=details.get("cum_main_3d", 0.0),
            latest_main_pct=details.get("latest_main_pct", 0.0),
            fund_flow_days=days,
        )

    # ------------------------------------------------------------------
    # LLM Analysis
    # ------------------------------------------------------------------

    async def _analyze_signal(self, s: FundFlowSignal):
        """Run Prompt v2 LLM analysis on a signal. Populates s.analysis_summary
        and s.analysis_full in-place."""
        try:
            # Fetch price data via yfinance
            price_data = await asyncio.to_thread(
                lambda: _fetch_price_data(s.ticker, period="1mo"),
            )
            if price_data:
                s.price_data = price_data
                recent = price_data[-3:]
                if len(recent) >= 2:
                    s.price_change_3d = (
                        (recent[-1]["close"] - recent[0]["close"])
                        / recent[0]["close"] * 100
                    )

            # Build prompt with fund flow + price data
            prompt = self._build_analysis_prompt(s)

            # Call LLM
            response = await self._call_llm(prompt)

            # Extract 核心信号 (主要观点) vs full report
            s.analysis_full = response
            s.analysis_summary = _extract_core_signal(response)

            logger.info("FundFlow: LLM analysis done for %s (%d chars)",
                         s.ticker, len(response))

        except Exception:
            logger.exception("FundFlow: LLM analysis failed for %s", s.ticker)
            s.analysis_summary = "（AI 分析暂时不可用）"

    def _build_analysis_prompt(self, s: FundFlowSignal) -> str:
        """Build the analysis prompt with fund flow data + price context."""
        # Format fund flow table
        rows = []
        for day in s.fund_flow_days:
            rows.append(
                f"| {day.date} | {getattr(day, 'change_pct', 0):.1f}% | "
                f"{day.main_net/1e4:.0f}万 | {day.super_big_net/1e4:.0f}万 | "
                f"{day.big_net/1e4:.0f}万 | {day.mid_net/1e4:.0f}万 | "
                f"{day.small_net/1e4:.0f}万 | {day.main_pct:.1f}% |"
            )

        header = (
            "| 日期 | 涨跌幅% | 主力净流入(万) | 特大单净流入(万) | "
            "大单净流入(万) | 中单净流入(万) | 小单净流入(万) | 主力占比% |"
        )
        table = "\n".join([header, *rows]) if rows else "（无数据）"

        # Price info
        price_info = ""
        if s.price_data:
            closes = [d["close"] for d in s.price_data[-10:]]
            price_info = f"近10日收盘价: {', '.join(f'{c:.2f}' for c in closes)}"

        system_prompt = _load_prompt_v2()
        user_prompt = (
            f"标的名称：{s.ticker}\n"
            f"数据周期：最近{s._days if hasattr(s, '_days') else 20}个交易日\n"
            f"{price_info}\n\n"
            f"{table}\n\n"
            f"请根据以上数据和分析框架，以「背离信号」为核心，"
            f"输出一份完整的专业资金流分析报告。"
        )

        return f"{system_prompt}\n\n---\n\n{user_prompt}"

    async def _call_llm(self, prompt: str) -> str:
        """Call DeepSeek LLM. Returns response text."""
        if self._llm_client is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if not api_key:
                return "（DeepSeek API Key 未配置）"
            from openai import OpenAI
            self._llm_client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com",
            )
            self._llm_model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

        resp = await asyncio.wait_for(
            asyncio.to_thread(
                self._llm_client.chat.completions.create,
                model=self._llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000,
            ),
            timeout=120,
        )
        return resp.choices[0].message.content.strip()

    # ------------------------------------------------------------------
    # Internal: persistence + signal computation
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
            cum_main_3d=details.get("cum_main_3d", 0.0),     # Futu 主力 (Block Orders)
            cum_super_big_3d=details.get("cum_super_big_3d", 0.0),
            latest_main_pct=details.get("latest_main_pct", 0.0),
            fund_flow_days=result.days,
        )]

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    async def _push_signals(
        self, signals: list[FundFlowSignal], window: str = WINDOW_POST,
    ) -> int:
        """Push strong signals. Skips silenced signals (earnings quiet period).

        Returns count of pushed signals.
        """
        pushed = 0
        for s in signals:
            if s.silenced:
                logger.info("FundFlow: %s silenced (earnings quiet period)", s.ticker)
                continue
            if s.participation == "extreme":
                await self._push_extreme(s, window)
                pushed += 1
            elif s.participation == "strong":
                await self._push_strong(s, window)
                pushed += 1
        return pushed

    async def _push_extreme(self, s: FundFlowSignal, window: str = WINDOW_POST):
        """★★★ 强背离 → Pushover + Telegram.  V2.5: 强制首位标定信号类型."""
        inflow = s.cum_main_3d > 0
        label = "盘前更新" if window == self.WINDOW_PRE else "收盘分析"

        # V2.5: 强制首位标定 — 🔴【顶背离·风险】/ 🟢【底背离·机会】
        price_down = s.price_change_3d < 0
        price_up = s.price_change_3d > 0
        if price_down and inflow:
            prefix = "🟢【底背离·机会】"
            tag = "底背离"
        elif price_up and not inflow:
            prefix = "🔴【顶背离·风险】"
            tag = "顶背离"
        else:
            prefix = "⚪"
            tag = "量价同向"

        title = f"{prefix} {s.ticker}"

        pushover_body = (
            f"{'流入' if inflow else '流出'} ¥{abs(s.cum_main_3d)/1e8:.1f}亿, "
            f"主力占比 {s.latest_main_pct:.1f}%"
        )
        if s.analysis_summary:
            pushover_body += f"\n\n💡 {s.analysis_summary}"

        if self._dispatcher:
            try:
                await self._dispatcher.send_system_alert(
                    title, pushover_body, emergency=False, quiet=False,
                )
            except Exception:
                logger.exception("FundFlow: Pushover push failed for %s", s.ticker)

        if self._bot:
            try:
                tg_text = self._format_tg_message(s, emoji, tag, signal_type, window)
                await self._bot.send_message(
                    chat_id=self._bot._primary_chat_id,
                    text=tg_text,
                    disable_notification=False,
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("FundFlow: Telegram push failed for %s", s.ticker)

    async def _push_strong(self, s: FundFlowSignal, window: str = WINDOW_POST):
        """★★ 标准背离 → Telegram only (silent)."""
        if self._bot:
            try:
                inflow = s.cum_main_3d > 0
                tag = "底背离" if s.price_change_3d < 0 and inflow else \
                      "顶背离" if s.price_change_3d > 0 and not inflow else "量价信号"
                tg_text = self._format_tg_message(
                    s, "📊", tag, "跟踪观察", window,
                )
                await self._bot.send_message(
                    chat_id=self._bot._primary_chat_id,
                    text=tg_text,
                    disable_notification=True,
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("FundFlow: Telegram silent push failed for %s", s.ticker)

    def _format_tg_message(
        self, s: FundFlowSignal, emoji: str, tag: str, signal_type: str,
        window: str = WINDOW_POST,
    ) -> str:
        """Format Telegram message with V2.1 semantics."""
        inflow = s.cum_main_3d > 0
        direction = "流入" if inflow else "流出"
        label = "🔔 盘前更新" if window == self.WINDOW_PRE else "📈 收盘分析"
        lines = [
            f"{emoji} <b>[{signal_type}] {s.ticker} {tag}</b>  <i>{label}</i>",
            "",
            f"📊 主力净{direction} ¥{abs(s.cum_main_3d)/1e8:.1f}亿, "
            f"主力占比 {s.latest_main_pct:.1f}%",
        ]

        if s.price_change_3d != 0:
            pct_str = f"{s.price_change_3d:+.1f}%"
            lines.append(f"📉 3日涨跌幅：{pct_str}")

        if s.analysis_summary:
            lines.append("")
            lines.append("💡 <b>主要观点</b>")
            lines.append(s.analysis_summary)

        if s.analysis_full:
            lines.append("")
            lines.append(
                f"<i>💬 发送 /ff {s.ticker} 查看完整分析报告</i>"
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_trading_day(self) -> bool:
        try:
            from collector.exchange_calendar import ExchangeCalendar
            return ExchangeCalendar().is_trading_day()
        except Exception:
            return True  # calendar unavailable → assume yes

    def _mark_done(self, window: str):
        today = self._et_today_str()
        if today not in self._completed:
            self._completed[today] = set()
        self._completed[today].add(window)
        # Prune old entries
        for key in list(self._completed.keys()):
            if key != today:
                del self._completed[key]

    # ------------------------------------------------------------------
    # Watchlist + helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_watchlist_from_memory() -> list[str]:
        """Load watchlist from .claude/memory/watchlist-state.md."""
        try:
            from pathlib import Path
            module_file = Path(__file__).resolve()
            for offset in (2, 3):
                candidate = (
                    module_file.parents[offset]
                    / ".claude" / "memory" / "watchlist-state.md"
                )
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_price_data(ticker: str, period: str = "1mo") -> list[dict]:
    """Fetch daily closing prices via yfinance. Returns [{date, close}, ...]."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        if hist.empty:
            return []
        return [
            {"date": str(idx.date()), "close": round(row["Close"], 2)}
            for idx, row in hist.iterrows()
        ]
    except Exception:
        return []


def _extract_core_signal(text: str) -> str:
    """Extract the 核心信号 / ultimate conclusion from the LLM response.

    Looks for the first meaningful paragraph after section headers like
    「核心信号」「1. 核心信号」「## 核心信号」. Falls back to first 300 chars.
    """
    patterns = [
        r'(?:核心信号|1\.\s*核心信号|##\s*核心信号)[：:\s]*\n?(.{10,500}?)(?=\n\n|\n#|\n\d\.|\Z)',
        r'(?:终极结论|主要结论)[：:\s]*\n?(.{10,500}?)(?=\n\n|\n#|\n\d\.|\Z)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            return m.group(1).strip()
    # Fallback: first meaningful paragraph (skip blank/separator lines)
    for line in text.split("\n"):
        stripped = line.strip()
        if len(stripped) > 30 and not stripped.startswith("#") and not stripped.startswith("-"):
            return stripped[:500]
    return text[:300]


def _et_offset_hours() -> int:
    """Quick US Eastern Time offset from UTC (standard=-5, daylight=-4)."""
    now = datetime.now(timezone.utc)
    year = now.year
    mar = datetime(year, 3, 14, tzinfo=timezone.utc)
    nov = datetime(year, 11, 7, tzinfo=timezone.utc)
    dst_start = 14 - ((mar.weekday() + 1) % 7)
    dst_end = 7 - ((nov.weekday() + 1) % 7)
    if (now.month > 3 and now.month < 11) or \
       (now.month == 3 and now.day >= dst_start) or \
       (now.month == 11 and now.day < dst_end):
        return 4   # EDT (UTC-4)
    return 5       # EST (UTC-5)
