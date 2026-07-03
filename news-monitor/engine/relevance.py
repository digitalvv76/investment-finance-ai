"""Two-direction relevance scoring — protective + opportunity.

Protective (backward-looking): how much does this news affect what I already own?
Opportunity (forward-looking):  does this news reveal a new trade to make?

The final relevance score takes the STRONGER of the two directions — not the
average.  A strategic event about a stock you don't own is an opportunity, not
irrelevant.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PORTFOLIO_PATH = _PROJECT_ROOT / ".claude" / "memory" / "portfolio-state.md"
_WATCHLIST_PATH = _PROJECT_ROOT / ".claude" / "memory" / "watchlist-state.md"

# ---------------------------------------------------------------------------
# Macro keywords — news that affects the whole market, not a single ticker.
# ---------------------------------------------------------------------------
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
]

# ---------------------------------------------------------------------------
# Ticker parsing (shared)
# ---------------------------------------------------------------------------

def _parse_tickers_from_md(path: Path) -> set[str]:
    tickers: set[str] = set()
    try:
        if not path.is_file():
            return tickers
        for match in re.finditer(r"\|\s*([A-Z0-9]{1,10})\s*\|", path.read_text(encoding="utf-8")):
            t = match.group(1).strip()
            if t and not t.isdigit() and t not in ("Ticker", "Coin", "——", "---"):
                tickers.add(t)
    except Exception as e:
        logger.debug("Failed to parse %s: %s", path, e)
    return tickers


def _parse_news_tickers(tickers_field: str) -> set[str]:
    if not tickers_field:
        return set()
    return {t.strip().upper() for t in tickers_field.split(",") if t.strip()}


def _is_macro(text: str, macro_tags: str = "") -> bool:
    combined = f"{text} {macro_tags}".lower()
    return any(kw.lower() in combined for kw in _MACRO_KEYWORDS)


# Cached
_portfolio: Optional[set[str]] = None
_watchlist: Optional[set[str]] = None


def _get_portfolio() -> set[str]:
    global _portfolio
    if _portfolio is None:
        _portfolio = _parse_tickers_from_md(_PORTFOLIO_PATH)
    return _portfolio


def _get_watchlist() -> set[str]:
    global _watchlist
    if _watchlist is None:
        _watchlist = _parse_tickers_from_md(_WATCHLIST_PATH)
    return _watchlist


# ---------------------------------------------------------------------------
# Direction 1 — Protective (backward-looking)
# ---------------------------------------------------------------------------

def _protective_score(news_tickers: set[str], news_text: str,
                      macro_tags: str) -> float:
    """How much does this news threaten or confirm my existing positions?

    Returns 0.0–1.5.
    """
    portfolio = _get_portfolio()
    watchlist = _get_watchlist()
    score = 0.0

    # Portfolio hits are the strongest protective signal.
    portfolio_hits = [t for t in news_tickers if t in portfolio]
    if portfolio_hits:
        score = 0.8 + min(len(portfolio_hits) * 0.3, 0.7)  # 0.8–1.5

    # Watchlist hits — moderate interest, they're on my radar.
    watchlist_hits = [t for t in news_tickers if t in watchlist and t not in portfolio]
    if watchlist_hits:
        wl_score = 0.5 + min(len(watchlist_hits) * 0.2, 0.4)  # 0.5–0.9
        score = max(score, wl_score)

    # Macro events affect everything I own.
    if _is_macro(news_text, macro_tags):
        score = max(score, 0.6)

    return score


# ---------------------------------------------------------------------------
# Direction 2 — Opportunity (forward-looking)
# ---------------------------------------------------------------------------

# Strategic event categories that signal INVESTABLE OPPORTUNITIES.
# These are NOT about protecting existing positions — they're about finding
# the NEXT trade.
_OPPORTUNITY_CATEGORIES = {
    "gov_intervention":        1.2,   # US gov invests/subsidies → follow the money
    "nvda_investment":         1.0,   # NVIDIA invests → follow Jensen's bet
    "nvda_endorsement":        0.9,   # Jensen praises a company → buy signal
    "nvda_competitive_threat": 0.7,   # NVIDIA entering new market → buy NVIDIA, short incumbents
}

# Sector-level keywords that suggest a rising tide (all boats in a sector lift).
_SECTOR_SIGNALS = {
    "扶持":   0.8,  # gov support
    "补贴":   0.8,  # subsidies
    "拨款":   0.7,  # funding/grant
    "行政命令": 0.7,  # executive order
    "invests":     0.8,  # government invests
    "subsidizes":  0.8,
    "funding":     0.7,
    "grant":       0.7,
    "strategic partnership": 0.6,
    "breakthrough": 0.6,
    "突破":         0.6,
    "战略合作":      0.6,
    "入股":         1.0,  # takes equity stake — strongest signal
    "收购":         0.8,  # acquisition
    "领投":         0.9,  # lead investor
    "站台":         0.7,  # public endorsement (Chinese)
    "赞扬":         0.6,  # praise
}


def _opportunity_score(news_text: str, strategic_matches: list | None,
                       is_breaking: bool, macro_tags: str = "") -> float:
    """How much NEW INVESTMENT OPPORTUNITY does this news create?

    Returns 0.0–1.5.
    """
    score = 0.0
    text_lower = news_text.lower()

    # --- Strategic event match (strongest signal) ---
    if strategic_matches:
        for m in strategic_matches:
            cat_score = _OPPORTUNITY_CATEGORIES.get(m.category, 0.5)
            score = max(score, cat_score * m.confidence)

    # --- FastLane strategic tags (backup when re-detect wasn't run) ---
    if macro_tags and "STRATEGIC_" in macro_tags:
        for cat, cat_score in _OPPORTUNITY_CATEGORIES.items():
            if cat in macro_tags:
                score = max(score, cat_score * 0.85)  # default confidence for FastLane tag

    # --- Sector-level signals (gov support, subsidies to an industry) ---
    sector_bonus = 0.0
    for kw, weight in _SECTOR_SIGNALS.items():
        if kw.lower() in text_lower:
            sector_bonus = max(sector_bonus, weight)
    if sector_bonus > 0:
        score = max(score, sector_bonus)

    # --- Breaking / novel news gets a timeliness boost ---
    if is_breaking:
        score = max(score, 0.5)  # at minimum, breaking news is worth watching

    return min(score, 1.5)


# ---------------------------------------------------------------------------
# Combined relevance
# ---------------------------------------------------------------------------

def relevance_multiplier(
    news_tickers: str = "",
    news_text: str = "",
    macro_tags: str = "",
    strategic_matches: list | None = None,
    is_breaking: bool = False,
) -> float:
    """Compute how personally relevant this news is — protective + opportunity.

    Takes the STRONGER direction, not the average.  A strategic event about
    a stock you don't own is an opportunity (1.2x), not "irrelevant" (0.3x).

    Returns a multiplier in [0.3, 1.5]:
      0.3  — noise: no ticker match, no strategic signal, no macro angle
      0.5  — weak signal: breaking but no specifics
      0.7  — moderate: sector-level signal or watchlist match
      1.0  — strong: strategic event or portfolio match
      1.2+ — urgent: high-confidence gov/nvda strategic event
    """
    item_tickers = _parse_news_tickers(news_tickers)

    protective = _protective_score(item_tickers, news_text, macro_tags)
    opportunity = _opportunity_score(news_text, strategic_matches, is_breaking, macro_tags)

    score = max(protective, opportunity)

    # Floor: even noise gets 0.3 so it still reaches Telegram silently.
    if score == 0.0:
        return 0.3

    return min(score, 1.5)


def get_portfolio_summary() -> dict:
    return {
        "portfolio_tickers": sorted(_get_portfolio()),
        "watchlist_tickers": sorted(_get_watchlist()),
    }
