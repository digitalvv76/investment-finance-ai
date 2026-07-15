"""Fund flow collector — daily post-market capital flow data pipeline.

Wires the EastMoneyFundFlowFetcher into the system: fetch → persist →
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
        "## 背离框架\n"
        "底背离（买入信号）：股价暴跌 + 特大单逆势净流入 = 主力吸筹\n"
        "顶背离（卖出信号）：股价大涨 + 特大单逆势净流出 = 主力出货\n\n"
        "## 输出要求\n"
        "先输出「核心信号」1-2句（有/无背离，方向，强度），"
        "再输出完整分析（趋势定位→背离细节→辅助确认→情景推演→验证条件）。"
    )


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class FundFlowSignal:
    """Computed signal from a ticker's fund flow data."""
    ticker: str
    continuity: str          # "continuous_inflow" | "continuous_outflow" | "mixed"
    participation: str       # "extreme" | "strong" | "normal" | "low"
    cum_super_big_3d: float  # 3-day cumulative super-big net (CNY)
    cum_main_3d: float       # 3-day cumulative main net (CNY)
    latest_main_pct: float   # latest day main_pct
    price_change_3d: float = 0.0       # 3-day cumulative price change (%)
    price_data: list[dict] = field(default_factory=list)  # [{date, close}]
    fund_flow_days: list = field(default_factory=list)    # FundFlowDay objects
    analysis_summary: str = ""         # LLM 主要观点
    analysis_full: str = ""            # LLM 完整报告


# ---------------------------------------------------------------------------
# FundFlowCollector
# ---------------------------------------------------------------------------

class FundFlowCollector:
    """Daily post-market fund flow collection + LLM analysis + signal dispatch.

    Owns an EastMoneyFundFlowFetcher instance and wires it into the
    storage + alerting + LLM subsystems.  Designed to be called once per
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

        # LLM client (lazy init)
        self._llm_client = None
        self._llm_model = "deepseek-chat"

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

        # Run LLM analysis on strong signals before pushing
        for s in all_signals:
            if s.participation in ("extreme", "strong"):
                await self._analyze_signal(s)

        pushed = await self._push_signals(all_signals)
        if persisted > 0:
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
            "大单净流入(万) | 中单净流入(万) | 小单净流入(万) | 主力净占比% |"
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
            cum_super_big_3d=details.get("cum_super_big_3d", 0.0),
            cum_main_3d=details.get("cum_main_3d", 0.0),
            latest_main_pct=details.get("latest_main_pct", 0.0),
            fund_flow_days=result.days,
        )]

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

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
        return pushed

    async def _push_extreme(self, s: FundFlowSignal):
        """Extreme participation → Pushover + Telegram (loud)."""
        direction = "流入" if s.cum_super_big_3d > 0 else "流出"
        emoji = "🟢" if s.cum_super_big_3d > 0 else "🔴"
        title = f"{emoji} 主力持续{direction} {s.ticker}"

        # Pushover — concise, no markdown
        pushover_body = (
            f"3日超大单净{direction} ¥{abs(s.cum_super_big_3d)/1e8:.1f}亿, "
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

        # Telegram — richer format
        if self._bot:
            try:
                tg_text = self._format_tg_message(s, emoji, direction)
                await self._bot.send_message(
                    chat_id=self._bot._primary_chat_id,
                    text=tg_text,
                    disable_notification=False,
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("FundFlow: Telegram push failed for %s", s.ticker)

    async def _push_strong(self, s: FundFlowSignal):
        """Strong participation → Telegram only (silent)."""
        direction = "流入" if s.cum_super_big_3d > 0 else "流出"
        emoji = "📊"

        if self._bot:
            try:
                tg_text = self._format_tg_message(s, emoji, direction)
                await self._bot.send_message(
                    chat_id=self._bot._primary_chat_id,
                    text=tg_text,
                    disable_notification=True,
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("FundFlow: Telegram silent push failed for %s", s.ticker)

    def _format_tg_message(self, s: FundFlowSignal, emoji: str, direction: str) -> str:
        """Format Telegram message with signal summary + 主要观点."""
        lines = [
            f"{emoji} <b>{s.ticker} 主力持续{direction}</b>",
            "",
            f"📊 3日超大单净{direction} ¥{abs(s.cum_super_big_3d)/1e8:.1f}亿，"
            f"主力占比 {s.latest_main_pct:.1f}%",
        ]

        if s.price_change_3d != 0:
            pct_str = f"{s.price_change_3d:+.1f}%"
            lines.append(f"📉 3日涨跌幅：{pct_str}")

        if s.analysis_summary:
            lines.append("")
            lines.append(f"💡 <b>主要观点</b>")
            lines.append(s.analysis_summary)

        # Deep analysis hint
        if s.analysis_full:
            lines.append("")
            lines.append(
                f"<i>💬 发送 /ff {s.ticker} 查看完整分析报告</i>"
            )

        return "\n".join(lines)

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
