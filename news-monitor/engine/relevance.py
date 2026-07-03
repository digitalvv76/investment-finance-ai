"""Four-dimension investment signal scoring.

Combines four orthogonal dimensions into a single signal score that determines
whether a news item deserves a phone push:

  1. Impact     (冲击力) — predicted market impact     → ImpactEvaluator LLM
  2. Timeliness (时效性) — can I act before others?    → age + market hours
  3. Novelty    (新颖性) — is this new or already known? → dedup + first-seen
  4. Relevance  (相关性) — protective + opportunity     → StrategicDetector + portfolio

Each dimension is 0.0–1.0.  The combined signal is their product — a weak
score on ANY dimension drags the whole signal down.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PORTFOLIO_PATH = _PROJECT_ROOT / ".claude" / "memory" / "portfolio-state.md"
_WATCHLIST_PATH = _PROJECT_ROOT / ".claude" / "memory" / "watchlist-state.md"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MACRO_KEYWORDS = [
    "FOMC", "fomc", "fed", "Federal Reserve", "美联储",
    "CPI", "cpi", "inflation", "通胀", "GDP", "gdp",
    "NFP", "nonfarm", "unemployment", "失业",
    "interest rate", "利率", "rate hike", "rate cut",
    "recession", "衰退", "treasury", "国债", "yield", "收益率",
    "tariff", "关税", "trade war", "贸易战",
    "geopolitical", "地缘", "war", "战争", "sanction", "制裁",
    "oil", "原油", "energy crisis",
    "stimulus", "刺激", "bailout", "救助",
    "PBOC", "央行", "ECB", "BOJ",
]

_NOVELTY_KEYWORDS = [
    "first", "首次", "unprecedented", "史无前例",
    "breaking", "突发", "just in", "快讯",
    "exclusive", "独家", "scoop",
    "surprise", "意外", "unexpected", "出乎意料",
    "new", "全新", "launch", "发布", "unveil", "公布",
    "breakthrough", "突破",
]

_SURPRISE_KEYWORDS = [
    "crash", "暴跌", "surge", "飙升", "plunge", "急跌",
    "panic", "恐慌", "meltdown", "shock", "震惊",
    "unexpectedly", "意外地", "suddenly", "突然",
    "unprecedented", "前所未有",
]

_OPPORTUNITY_CATEGORIES = {
    "gov_intervention":        1.2,
    "nvda_investment":         1.0,
    "nvda_endorsement":        0.9,
    "nvda_competitive_threat": 0.7,
}

# Only the HIGHEST-impact event categories get an automatic relevance boost.
# Lower-tier events (earnings, product launches, IPOs) don't get boosted —
# they need other signals (ticker match, strategic pattern, sector keyword).
_HIGH_IMPACT_CATEGORIES = {
    # Monetary — affects every asset in existence
    "fomc":               1.00,
    "monetary_policy":    0.95,
    "rate_hike":          0.90,
    "rate_cut":           0.90,
    "inflation":          0.90,
    "cpi":                0.90,
    "fed":                0.85,
    "interest_rate":      0.85,
    "stagflation_risk":   0.85,
    # Geopolitical — highest impact, hardest to hedge
    "war":                1.00,
    "geopolitical":       1.00,
    "oil_supply":         0.90,
    "energy_crisis":      0.90,
    "trade_war":          0.85,
    "sanction":           0.80,
    # Systemic — "the plumbing is breaking"
    "systemic_risk":      0.85,
    "contagion":          0.80,
    "tariff":             0.85,
    "trade_policy":       0.80,
    # Macro data surprises
    "macro_data":         0.80,
    "gdp":                0.70,
    "employment":         0.70,
    # China macro
    "china_stimulus":     0.85,
    "pboc":               0.80,
}

# Categories that are INHERENTLY LOW IMPACT — they should NOT trigger
# phone pushes unless paired with a strategic signal or ticker match.
_LOW_IMPACT_CATEGORIES = {
    "earnings", "merger", "acquisition", "ipo",
    "product_launch", "leadership_change",
    "transparency", "routine_data",
}

_SECTOR_SIGNALS = {
    "扶持": 0.8, "补贴": 0.8, "拨款": 0.7, "行政命令": 0.7,
    "invests": 0.8, "subsidizes": 0.8, "funding": 0.7, "grant": 0.7,
    "strategic partnership": 0.6, "breakthrough": 0.6, "突破": 0.6,
    "战略合作": 0.6, "入股": 1.0, "收购": 0.8, "领投": 0.9,
    "站台": 0.7, "赞扬": 0.6,
}


def _parse_tickers_from_md(path: Path) -> set[str]:
    tickers: set[str] = set()
    try:
        if not path.is_file():
            return tickers
        for match in re.finditer(r"\|\s*([A-Z0-9]{1,10})\s*\|", path.read_text(encoding="utf-8")):
            t = match.group(1).strip()
            if t and not t.isdigit() and t not in ("Ticker", "Coin", "——", "---"):
                tickers.add(t)
    except Exception:
        pass
    return tickers


def _parse_news_tickers(tickers_field: str) -> set[str]:
    if not tickers_field:
        return set()
    return {t.strip().upper() for t in tickers_field.split(",") if t.strip()}


def _is_macro(text: str, macro_tags: str = "") -> bool:
    combined = f"{text} {macro_tags}".lower()
    return any(kw.lower() in combined for kw in _MACRO_KEYWORDS)


# Cached portfolio/watchlist
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


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 1 — Timeliness (时效性)      0.0–1.0
# ═══════════════════════════════════════════════════════════════════════════

# Exponential decay: a 5-minute-old breaking news is worth ~0.95;
# a 4-hour-old article is worth ~0.37.
_HALF_LIFE_MINUTES = 30          # relevance halves every 30 minutes
_BREAKING_BYPASS_MINUTES = 10    # breaking news gets full score for 10 min


def timeliness_factor(
    published_at: Optional[str] = None,
    is_breaking: bool = False,
) -> float:
    """How timely is this news?  Can I act before the market prices it in?

    Breaking news degrades slowly (full score for 10 min, then decays).
    Regular news decays faster — a 2-hour-old article has minimal edge.

    Returns 1.0 (just happened) → 0.0 (stale).
    """
    if published_at is None:
        return 1.0  # unknown age → assume fresh (don't penalize missing data)

    try:
        if isinstance(published_at, str):
            # Normalise ISO-ish formats
            ts = published_at.replace("T", " ").replace("Z", "")
            pub = datetime.fromisoformat(ts[:19])  # YYYY-MM-DD HH:MM:SS
        elif isinstance(published_at, datetime):
            pub = published_at
        else:
            return 1.0
    except (ValueError, TypeError):
        return 1.0

    age_minutes = (datetime.now() - pub).total_seconds() / 60
    if age_minutes < 0:
        age_minutes = 0  # clock skew

    # Breaking news: full score for the first BREAKING_BYPASS_MINUTES,
    # then decays with the same half-life.
    if is_breaking and age_minutes <= _BREAKING_BYPASS_MINUTES:
        return 1.0

    # Exponential decay: score = 2^(-age / half_life)
    decay = 2 ** (-age_minutes / _HALF_LIFE_MINUTES)
    return round(max(decay, 0.05), 3)  # floor at 0.05 — never zero


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 2 — Novelty (新颖性)        0.0–1.0
# ═══════════════════════════════════════════════════════════════════════════

# Track seen headlines in a simple in-memory LRU set (for dedup-aware novelty).
# In production this should use ChromaDB; this is the lightweight fast-path.
_SEEN_SIGNATURES: set[int] = set()
_MAX_SEEN = 2000


def novelty_factor(
    news_text: str = "",
    is_breaking: bool = False,
    macro_tags: str = "",
) -> float:
    """Is this NEW information, or has the market already absorbed it?

    Factors:
    - Breaking markers → high novelty
    - Surprise / unprecedented language → high novelty
    - First-seen keywords (突破/首次/exclusive) → high novelty
    - Has this exact title been seen before? → zero novelty

    Returns 1.0 (completely new) → 0.0 (already known).
    """
    if not news_text:
        return 0.85  # unknown → assume novel

    text_lower = news_text.lower()

    # --- Breaking + surprise markers → high novelty ---
    if is_breaking:
        return 1.0  # breaking news is definitionally novel

    surprise_count = sum(1 for kw in _SURPRISE_KEYWORDS if kw.lower() in text_lower)
    if surprise_count >= 2:
        return 1.0
    elif surprise_count == 1:
        return 0.9

    novelty_count = sum(1 for kw in _NOVELTY_KEYWORDS if kw.lower() in text_lower)
    if novelty_count >= 2:
        return 0.85

    # --- Exact duplicate check (fast path via title hash) ---
    sig = hash(news_text[:200])  # first 200 chars as fingerprint
    if sig in _SEEN_SIGNATURES:
        return 0.1  # exact duplicate → very low novelty
    _SEEN_SIGNATURES.add(sig)
    if len(_SEEN_SIGNATURES) > _MAX_SEEN:
        _SEEN_SIGNATURES.clear()  # simple LRU: just flush when full

    # Default: assume novel (don't penalize without evidence of staleness)
    return 0.85


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 3 — Protective relevance (向后看)  0.0–1.5
# ═══════════════════════════════════════════════════════════════════════════

def _protective_score(news_tickers: set[str], news_text: str,
                      macro_tags: str) -> float:
    portfolio = _get_portfolio()
    watchlist = _get_watchlist()
    score = 0.0

    portfolio_hits = [t for t in news_tickers if t in portfolio]
    if portfolio_hits:
        score = 0.8 + min(len(portfolio_hits) * 0.3, 0.7)

    watchlist_hits = [t for t in news_tickers if t in watchlist and t not in portfolio]
    if watchlist_hits:
        wl_score = 0.5 + min(len(watchlist_hits) * 0.2, 0.4)
        score = max(score, wl_score)

    if _is_macro(news_text, macro_tags):
        score = max(score, 0.6)

    return score


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 4 — Opportunity relevance (向前看)  0.0–1.5
# ═══════════════════════════════════════════════════════════════════════════

def _opportunity_score(news_text: str, strategic_matches: list | None,
                       macro_tags: str) -> float:
    score = 0.0
    text_lower = news_text.lower()
    tags_lower = macro_tags.lower()

    # --- StrategicDetector regex matches ---
    if strategic_matches:
        for m in strategic_matches:
            cat_score = _OPPORTUNITY_CATEGORIES.get(m.category, 0.5)
            score = max(score, cat_score * m.confidence)

    # --- FastLane STRATEGIC_ tags ---
    if macro_tags and "STRATEGIC_" in macro_tags:
        for cat, cat_score in _OPPORTUNITY_CATEGORIES.items():
            if cat in macro_tags:
                score = max(score, cat_score * 0.85)

    # --- High-impact category boost (FOMC, war, CPI, etc.) ---
    # Only the top-tier event categories get an automatic boost.
    # Lower-tier events (earnings, product launches) don't — they need
    # strategic signals or ticker matches to earn relevance.
    category_bonus = 0.0
    for tag, weight in _HIGH_IMPACT_CATEGORIES.items():
        if tag.lower() in tags_lower:
            category_bonus = max(category_bonus, weight)
    if category_bonus > 0:
        score = max(score, category_bonus)

    # --- Low-impact category penalty ---
    # If ALL the event's tags are low-impact, pull the score down.
    if tags_lower:
        tag_set = set(tags_lower.replace(",", " ").split())
        if tag_set and tag_set.issubset(_LOW_IMPACT_CATEGORIES):
            score = min(score, 0.5)  # cap at 0.5 for purely low-impact events

    # --- Sector-level signals (gov support, subsidies) ---
    sector_bonus = 0.0
    for kw, weight in _SECTOR_SIGNALS.items():
        if kw.lower() in text_lower:
            sector_bonus = max(sector_bonus, weight)
    if sector_bonus > 0:
        score = max(score, sector_bonus)

    return min(score, 1.5)


# ═══════════════════════════════════════════════════════════════════════════
# Combined signal score (4 dimensions)
# ═══════════════════════════════════════════════════════════════════════════

def signal_score(
    news_tickers: str = "",
    news_text: str = "",
    macro_tags: str = "",
    strategic_matches: list | None = None,
    is_breaking: bool = False,
    published_at: Optional[str] = None,
) -> dict:
    """Compute the four-dimension investment signal score.

    Returns a dict with the composite score and per-dimension breakdown:
      {
        "composite": 0.0–1.0+,   ← this is what controls the push decision
        "timeliness": float,
        "novelty": float,
        "relevance": float,      ← max(protective, opportunity), 0.3–1.5
        "relevance_direction": "protective" | "opportunity" | "both" | "none",
      }

    Composite = timeliness × novelty × relevance

    A weak score on ANY dimension pulls the composite down — you can have
    a high-relevance event, but if the news is 4 hours old (timeliness=0.1),
    there's no edge left to trade on.
    """
    item_tickers = _parse_news_tickers(news_tickers)

    # 1. Timeliness
    timely = timeliness_factor(published_at, is_breaking)

    # 2. Novelty
    novel = novelty_factor(news_text, is_breaking, macro_tags)

    # 3 + 4. Protective + Opportunity → relevance
    protective = _protective_score(item_tickers, news_text, macro_tags)
    opportunity = _opportunity_score(news_text, strategic_matches, macro_tags)
    relevance = max(protective, opportunity)
    if relevance == 0.0:
        relevance = 0.3  # floor

    # Direction label for logging
    if protective >= opportunity and protective > 0:
        direction = "protective"
    elif opportunity > protective:
        direction = "opportunity"
    else:
        direction = "none"

    # Composite — multiplicative so a zero on any dimension kills the signal
    composite = round(timely * novel * relevance, 3)

    return {
        "composite": composite,
        "timeliness": timely,
        "novelty": novel,
        "relevance": relevance,
        "relevance_direction": direction,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Backward-compatible wrapper
# ═══════════════════════════════════════════════════════════════════════════

def relevance_multiplier(
    news_tickers: str = "",
    news_text: str = "",
    macro_tags: str = "",
    strategic_matches: list | None = None,
    is_breaking: bool = False,
    published_at: Optional[str] = None,
) -> float:
    """Backward-compatible wrapper — returns the composite signal score.

    Use signal_score() for the full 4-dimension breakdown.
    """
    return signal_score(
        news_tickers=news_tickers,
        news_text=news_text,
        macro_tags=macro_tags,
        strategic_matches=strategic_matches,
        is_breaking=is_breaking,
        published_at=published_at,
    )["composite"]


def get_portfolio_summary() -> dict:
    return {
        "portfolio_tickers": sorted(_get_portfolio()),
        "watchlist_tickers": sorted(_get_watchlist()),
    }
