"""Personalized relevance scoring — how much does this news matter to ME?

Weights news against the user's portfolio positions and watchlist, so that
news about tickers the user actually owns or tracks gets boosted, while
news about unrelated tickers gets deprioritized.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Paths relative to this file
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PORTFOLIO_PATH = _PROJECT_ROOT / ".claude" / "memory" / "portfolio-state.md"
_WATCHLIST_PATH = _PROJECT_ROOT / ".claude" / "memory" / "watchlist-state.md"

# Macro keywords that make news relevant regardless of ticker match
_MACRO_KEYWORDS = [
    "FOMC", "fomc", "fed", "Federal Reserve", "美联储",
    "CPI", "cpi", "inflation", "通胀",
    "GDP", "gdp",
    "NFP", "nonfarm", "unemployment", "失业",
    "interest rate", "利率", "rate hike", "rate cut",
    "recession", "衰退",
    "treasury", "国债", "yield", "收益率",
    "tariff", "关税", "trade war", "贸易战",
    "geopolitical", "地缘", "war", "战争", "sanction", "制裁",
    "oil", "原油", "energy crisis",
    "stimulus", "刺激", "bailout", "救助",
    "PBOC", "央行", "ECB", "BOJ",
    "SEC", "sec", "regulation", "监管",
]


def _parse_portfolio_tickers() -> set[str]:
    """Extract ticker symbols from portfolio-state.md."""
    tickers: set[str] = set()
    try:
        if not _PORTFOLIO_PATH.is_file():
            return tickers
        text = _PORTFOLIO_PATH.read_text(encoding="utf-8")
        # Match ticker symbols in markdown tables: | AAPL | or | 600519 |
        for match in re.finditer(r"\|\s*([A-Z0-9]{1,10})\s*\|", text):
            ticker = match.group(1).strip()
            if ticker and not ticker.isdigit() and ticker not in ("Ticker", "Coin", "——", "---"):
                tickers.add(ticker)
    except Exception as e:
        logger.debug("Failed to parse portfolio: %s", e)
    return tickers


def _parse_watchlist_tickers() -> set[str]:
    """Extract ticker symbols from watchlist-state.md."""
    tickers: set[str] = set()
    try:
        if not _WATCHLIST_PATH.is_file():
            return tickers
        text = _WATCHLIST_PATH.read_text(encoding="utf-8")
        for match in re.finditer(r"\|\s*([A-Z0-9]{1,10})\s*\|", text):
            ticker = match.group(1).strip()
            if ticker and not ticker.isdigit() and ticker not in ("Ticker", "Coin", "——", "---"):
                tickers.add(ticker)
    except Exception as e:
        logger.debug("Failed to parse watchlist: %s", e)
    return tickers


def _parse_news_tickers(tickers_field: str) -> set[str]:
    """Parse the comma-separated tickers_found field from a news item."""
    if not tickers_field:
        return set()
    return {t.strip().upper() for t in tickers_field.split(",") if t.strip()}


def is_macro_event(text: str, macro_tags: str = "") -> bool:
    """Check whether the news describes a macro-level event that affects all positions."""
    combined = f"{text} {macro_tags}".lower()
    for kw in _MACRO_KEYWORDS:
        if kw.lower() in combined:
            return True
    return False


# Cached ticker sets (lazy-loaded, refreshed on each call for simplicity)
_portfolio: Optional[set[str]] = None
_watchlist: Optional[set[str]] = None


def _get_portfolio() -> set[str]:
    global _portfolio
    if _portfolio is None:
        _portfolio = _parse_portfolio_tickers()
    return _portfolio


def _get_watchlist() -> set[str]:
    global _watchlist
    if _watchlist is None:
        _watchlist = _parse_watchlist_tickers()
    return _watchlist


def relevance_multiplier(
    news_tickers: str,
    news_text: str = "",
    macro_tags: str = "",
) -> float:
    """Compute how personally relevant this news is to the user.

    Returns a multiplier in [0.3, 1.5]:
      - 0.3: news has no connection to portfolio or watchlist
      - 1.0: neutral / macro event with no direct ticker match
      - 1.5: news directly mentions a portfolio position

    Args:
        news_tickers: Comma-separated tickers_found string from NewsItem.
        news_text: Full news title + snippet for macro keyword detection.
        macro_tags: Comma-separated macro_tags from NewsItem.
    """
    portfolio = _get_portfolio()
    watchlist = _get_watchlist()
    item_tickers = _parse_news_tickers(news_tickers)

    score = 0.0

    # Direct ticker matches
    for t in item_tickers:
        if t in portfolio:
            score += 0.6  # Portfolio position → high relevance
        elif t in watchlist:
            score += 0.4  # Watchlist → moderate relevance

    # Macro event relevance (affects all positions)
    if is_macro_event(news_text, macro_tags):
        score += 0.5

    # If nothing matched at all, don't zero it out — just demote significantly
    if score == 0.0:
        return 0.3

    return min(score, 1.5)


def get_portfolio_summary() -> dict:
    """Return a summary of the user's current holdings for logging/diagnostics."""
    return {
        "portfolio_tickers": sorted(_get_portfolio()),
        "watchlist_tickers": sorted(_get_watchlist()),
    }
