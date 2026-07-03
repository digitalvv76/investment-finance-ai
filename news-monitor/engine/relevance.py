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
    "dividend", "buyback", "share_repurchase",
    "analyst_rating", "price_target", "stock_movement",
}

_SECTOR_SIGNALS = {
    "扶持": 0.8, "补贴": 0.8, "拨款": 0.7, "行政命令": 0.7,
    "invests": 0.8, "subsidizes": 0.8, "funding": 0.7, "grant": 0.7,
    "strategic partnership": 0.6, "breakthrough": 0.6, "突破": 0.6,
    "战略合作": 0.6, "入股": 1.0, "收购": 0.8, "领投": 0.9,
    "站台": 0.7, "赞扬": 0.6,
    # Government contracts & subsidies (expanded from user feedback)
    "加速开发": 0.75, "核反应堆": 0.75, "煤电": 0.70, "火电": 0.70,
    "关键矿产": 0.70, "能源合同": 0.75, "基础设施合同": 0.75,
    # Jensen Huang verbal signals (expanded)
    "喊话": 0.75, "力挺": 0.75, "背书": 0.70, "点名": 0.65,
    "公开赞扬": 0.70, "站台背书": 0.75,
    # FDA / drug approval catalysts
    "FDA": 0.70, "批准": 0.55, "加速批准": 0.80, "突破性疗法": 0.80,
    "accelerated approval": 0.80, "breakthrough therapy": 0.80,
    # Corporate actions with tradable opportunities
    "拆分": 0.70, "spinoff": 0.70, "spin off": 0.70,
    "分拆上市": 0.75, "剥离": 0.65, "divestiture": 0.65,
    "breakup": 0.70, "split into": 0.70, "carve out": 0.65,
    # English: government contracts & subsidies
    "fast-track": 0.75, "expedite": 0.70, "accelerate": 0.65,
    "nuclear reactor": 0.75, "SMR": 0.75, "small modular reactor": 0.75,
    "coal power": 0.70, "coal-fired": 0.70, "fossil fuel plant": 0.65,
    "critical minerals": 0.70, "rare earth": 0.75, "rare earths": 0.75,
    "infrastructure contract": 0.75, "defense contract": 0.80,
    "energy contract": 0.75, "power purchase agreement": 0.70,
    "national security": 0.70, "supply chain security": 0.70,
    "domestic production": 0.65, "reshore": 0.65, "onshore": 0.65,
    # English: endorsement / verbal signals
    "touted": 0.75, "praised": 0.70, "urged": 0.70,
    "called for": 0.65, "threw support behind": 0.70,
    "endorsed": 0.75, "backed": 0.70, "vouched for": 0.65,
    "singled out": 0.65, "name-checked": 0.60,
    "said.*is.*the.*future": 0.65, "called.*the.*most.*important": 0.70,
    "hailed": 0.65, "championed": 0.70,
    # English: FDA / drug catalysts
    "FDA approval": 0.75, "FDA clearance": 0.75,
    "accelerated approval": 0.80, "breakthrough therapy": 0.80,
    "priority review": 0.75, "fast track designation": 0.75,
    "NDA": 0.55, "BLA": 0.55, "PDUFA": 0.65,
    # English: strategic investments
    "takes stake in": 0.85, "acquires stake": 0.85,
    "convertible preferred": 0.80, "equity stake": 0.80,
    "strategic investment": 0.75, "anchor investment": 0.75,
    "lead investor": 0.80, "co-invest": 0.75,
}

# Patterns that indicate RETROSPECTIVE / SUMMARY content — not actionable.
# These pull the relevance score DOWN because the event already happened.
_RETROSPECTIVE_PATTERNS = [
    r"从\s*\S+\s*(→|到|升至|跌至|涨至|暴涨|暴跌|飙)",  # "从 $67 → $119"
    r"(蒸发|过山车|回顾|总结)",                          # summary/recap language
    r"(单月|当月|本月|上周|上月|Q\d|H1|H2|季度|年度).{0,10}(蒸发|跌|涨|暴跌|暴涨|累计|流出|流入)",  # period recap
    r"(YTD|今年以来|年初至今)",                          # year-to-date recap
    r"(创.*(?:新高|新低|纪录|记录))",                     # "创历史新高"
    r"(自|从)\d{4}年.{0,15}(以来|起|至今)",                # "自2025年以来" — long historical view
    r"(上市|IPO|定价).{0,30}(?:估值|融资|万亿)",            # IPO retrospective
    r"\d{4}年(?:金融危机|危机|泡沫)",                      # historical event from another era
    # English retrospective patterns
    r"(from|since)\s*\$?\d+.*(→|to)\s*\$?\d+",             # "from $67 → $119"
    r"(plunged|surged|skyrocketed|tumbled|soared)\s*\d+%",  # single-direction recap
    r"(year.to.date|ytd|quarterly|monthly)\s+(review|recap|roundup|wrap)",
    r"(best|worst)\s+(month|quarter|year)\s+(since|in)",    # "worst quarter since 2013"
    r"(market\s+cap|market\s+value)\s+(evaporat|wiped|erased|lost)",
    r"(closed|ended|finished)\s+(the\s+)?(month|quarter|week)\s+(down|up|flat)",
    r"since\s+(the\s+)?start\s+of\s+(the\s+)?(year|quarter|month)",
]

# Patterns that indicate THREAT / PROPOSAL — not yet action.
# These should get a discount because the event hasn't materialized.
_THREAT_PATTERNS = [
    r"(威胁|警告|提议|考虑|可能|计划|拟|将)\s*(征收|对|加征|禁止|限制|制裁|课征)",
    r"(threaten|warn|propose|consider|plan|may|might|could)\s+(impose|levy|ban|restrict|sanction|tariff)",
    r"(尚未|还未|暂未|仍在讨论|有待|等待)\s*(实施|执行|通过|批准)",
    # English threat / proposal patterns
    r"(threaten|warn|propose|consider|plan|may|might|could)\s+(?:to\s+)?(impose|levy|ban|restrict|sanction|tariff|duty)",
    r"(floated|floating)\s+(?:the\s+)?(?:idea|proposal|plan)\s+(?:of|to)",
    r"(mulled|mulling|weighed|weighing)\s+(?:a\s+)?(?:tariff|sanction|ban|restriction)",
    r"(not\s+yet|has\s+not|have\s+not|still\s+(?:under|in))\s+(?:implement|enact|enforce|approve|finalize)",
    r"(could|could\s+potentially|is\s+expected\s+to|is\s+set\s+to)\s+(levy|impose|raise|increase)",
]

# Personnel appointments that lack accompanying policy action
_PERSONNEL_ONLY_PATTERNS = [
    r"(宣誓就任|被任命为|出任|接替|appointed|sworn\sin|named\sas|takes\sover|will\s+become|has\s+been\s+named|to\s+lead|to\s+head)",
]


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

# Exponential decay with event-type-specific half-lives.
# Geopolitical shocks take hours to digest; product launches go stale in minutes.
_DEFAULT_HALF_LIFE = 30           # minutes — default for unclassified news
_BREAKING_BYPASS_MINUTES = 10     # breaking news gets full score for 10 min

# Half-life by event category: how long before the news value drops by 50%.
_EVENT_HALF_LIFE = {
    "geopolitical": 240,     # 4 hours — war, sanctions, regime change take time to assess
    "war": 240,
    "monetary": 90,          # 1.5 hours — FOMC, rate decisions need parsing
    "macro_data": 60,        # 1 hour — CPI, NFP, GDP
    "regulatory": 45,        # 45 min — trade policy, tariffs, FDA
    "corporate": 15,         # 15 min — earnings, product launches (fast-moving)
    "other": 30,             # 30 min — default
}

# Map from common tag names to event categories for half-life lookup.
_TAG_TO_HALF_LIFE_CATEGORY = {
    # geopolitical → 240min
    "geopolitical": "geopolitical", "war": "geopolitical",
    "oil_supply": "geopolitical", "energy_crisis": "geopolitical",
    "sanction": "geopolitical", "trade_war": "geopolitical",
    "defense": "geopolitical",
    # monetary → 90min
    "monetary_policy": "monetary", "fomc": "monetary",
    "rate_hike": "monetary", "rate_cut": "monetary",
    "fed": "monetary", "interest_rate": "monetary",
    "forward_guidance": "monetary", "hawkish": "monetary", "dovish": "monetary",
    "fed_policy": "monetary", "transparency": "monetary",
    # macro_data → 60min
    "macro_data": "macro_data", "inflation": "macro_data",
    "cpi": "macro_data", "gdp": "macro_data", "employment": "macro_data",
    "stagflation_risk": "macro_data",
    # regulatory → 45min
    "tariff": "regulatory", "trade_policy": "regulatory",
    "regulation": "regulatory", "regulatory": "regulatory",
    "china_regulation": "regulatory", "china_stimulus": "regulatory",
    "pboc": "regulatory",
    # corporate → 15min
    "earnings": "corporate", "merger": "corporate", "acquisition": "corporate",
    "ipo": "corporate", "product_launch": "corporate",
    "leadership_change": "corporate",
    "tech_selloff": "corporate", "ai_spending": "corporate",
    "magnificent_seven": "corporate", "sector_rotation": "corporate",
}


def timeliness_factor(
    published_at: Optional[str] = None,
    is_breaking: bool = False,
    event_type: str = "",
) -> float:
    """How timely is this news?  Can I act before the market prices it in?

    Half-life varies by event type:
      - war/geopolitical: 240 min (4 hours — takes time to assess)
      - FOMC/monetary:    90 min (1.5 hours — needs parsing)
      - CPI/macro data:   60 min (1 hour)
      - tariff/regulatory: 45 min
      - earnings/product:  15 min (fast-moving, goes stale quickly)
      - default:           30 min

    Breaking news gets full score for the first 10 minutes.

    Returns 1.0 (just happened) → 0.0 (stale).
    """
    half_life = _EVENT_HALF_LIFE.get(event_type, _DEFAULT_HALF_LIFE) if event_type else _DEFAULT_HALF_LIFE

    if published_at is None:
        return 1.0  # unknown age → assume fresh (don't penalize missing data)

    try:
        if isinstance(published_at, str):
            ts = published_at.replace("T", " ").replace("Z", "")
            pub = datetime.fromisoformat(ts[:19])
        elif isinstance(published_at, datetime):
            pub = published_at
        else:
            return 1.0
    except (ValueError, TypeError):
        return 1.0

    age_minutes = (datetime.now() - pub).total_seconds() / 60
    if age_minutes < 0:
        age_minutes = 0

    if is_breaking and age_minutes <= _BREAKING_BYPASS_MINUTES:
        return 1.0

    decay = 2 ** (-age_minutes / half_life)
    return round(max(decay, 0.05), 3)


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 2 — Novelty (新颖性)        0.0–1.0
# ═══════════════════════════════════════════════════════════════════════════

# Track seen headlines in a simple in-memory LRU set (for dedup-aware novelty).
_SEEN_SIGNATURES: set[int] = set()
_MAX_SEEN = 2000


def _max_semantic_similarity(vector_store, text: str) -> float:
    """Return the cosine similarity to the most similar article in ChromaDB."""
    try:
        return vector_store.max_similarity(text[:1000])
    except Exception:
        return 0.0



def novelty_factor(
    news_text: str = "",
    is_breaking: bool = False,
    macro_tags: str = "",
) -> float:
    """Is this NEW information, or has the market already absorbed it?

    Three-layer detection:
    1. Breaking markers → always novel (1.0)
    2. Semantic dedup via ChromaDB → near-duplicate → 0.1
    3. Title-hash exact duplicate → 0.1
    4. Surprise/novelty keyword scoring
    5. Default: 0.85 (assume novel without evidence)

    Returns 1.0 (completely new) → 0.0 (already known).
    """
    if not news_text:
        return 0.85

    text_lower = news_text.lower()

    # --- Breaking markers → ceiling ---
    if is_breaking:
        return 1.0

    # Note: near-duplicate detection is handled upstream by DedupManager
    # (URL + content-hash + ChromaDB semantic dedup).  Articles that
    # reach this point have already passed dedup — they are at least
    # somewhat novel.  Our job here is to detect:
    #   1. Retrospective/recap content (handled by _content_quality_penalty
    #      in the relevance dimension, not here)
    #   2. Breaking/surprise markers → high novelty
    #   3. Exact title reprints → very low novelty (hash check below)

    # --- Surprise markers → high novelty ---
    surprise_count = sum(1 for kw in _SURPRISE_KEYWORDS if kw.lower() in text_lower)
    if surprise_count >= 2:
        return 1.0
    elif surprise_count == 1:
        return 0.9

    novelty_count = sum(1 for kw in _NOVELTY_KEYWORDS if kw.lower() in text_lower)
    if novelty_count >= 2:
        return 0.85

    # --- Exact duplicate check (fast path via title hash) ---
    sig = hash(news_text[:200])
    if sig in _SEEN_SIGNATURES:
        return 0.1
    _SEEN_SIGNATURES.add(sig)
    if len(_SEEN_SIGNATURES) > _MAX_SEEN:
        _SEEN_SIGNATURES.clear()

    # Default: assume novel
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

    # --- Sector-level signals (gov support, subsidies, FDA, spinoffs) ---
    sector_bonus = 0.0
    for kw, weight in _SECTOR_SIGNALS.items():
        if kw.lower() in text_lower:
            sector_bonus = max(sector_bonus, weight)
    if sector_bonus > 0:
        score = max(score, sector_bonus)

    # --- Content quality penalties ---
    score *= _content_quality_multiplier(text_lower)

    return min(score, 1.5)


def _content_quality_multiplier(text_lower: str) -> float:
    """Penalize retrospective summaries and empty threats.

    Returns 1.0 (no penalty) down to 0.4 (severe penalty).
    """
    penalty = 1.0

    # Retrospective/summary content → not actionable, heavy penalty
    for pat in _RETROSPECTIVE_PATTERNS:
        if re.search(pat, text_lower):
            penalty = min(penalty, 0.5)
            break  # one match is enough

    # Threat/proposal (not yet action) → moderate penalty
    for pat in _THREAT_PATTERNS:
        if re.search(pat, text_lower):
            penalty = min(penalty, 0.65)
            break

    # Personnel appointment alone (no policy action attached) → stronger penalty
    for pat in _PERSONNEL_ONLY_PATTERNS:
        if re.search(pat, text_lower):
            if not re.search(r"(加息|降息|利率|关税|制裁|战争|invest|subsid|fund|grant|ban|restrict|tariff|policy|行政命令|法案)", text_lower):
                penalty = min(penalty, 0.55)  # stronger than before: 0.55 instead of 0.7
            break

    return penalty


# ═══════════════════════════════════════════════════════════════════════════
# Combined signal score (4 dimensions)
# ═══════════════════════════════════════════════════════════════════════════

def _infer_event_type(macro_tags: str, strategic_matches: list | None,
                      news_text: str) -> str:
    """Infer the event category for half-life lookup.

    Checks (in priority order):
    1. StrategicDetector match category
    2. Macro tags matching known high-impact categories
    3. News text keyword scanning
    """
    # 1. Strategic match → map category
    if strategic_matches:
        for m in strategic_matches:
            if m.category in ("gov_intervention",):
                return "regulatory"
            if m.category in ("nvda_endorsement", "nvda_investment", "nvda_competitive_threat"):
                return "corporate"

    # 2. Macro tags → half-life category
    tags_lower = macro_tags.lower()
    for tag, hl_cat in _TAG_TO_HALF_LIFE_CATEGORY.items():
        if tag in tags_lower:
            return hl_cat

    # 3. Text scanning for obvious event types
    text_lower = news_text.lower()
    if any(kw in text_lower for kw in ("war", "military", "invasion", "strike", "conflict", "战争", "军事", "入侵")):
        return "geopolitical"
    if any(kw in text_lower for kw in ("fomc", "fed", "rate hike", "rate cut", "central bank", "加息", "降息", "美联储")):
        return "monetary"
    if any(kw in text_lower for kw in ("cpi", "nfp", "gdp", "inflation", "unemployment", "通胀", "失业")):
        return "macro_data"
    if any(kw in text_lower for kw in ("tariff", "sanction", "trade", "ban", "关税", "制裁", "监管")):
        return "regulatory"
    if any(kw in text_lower for kw in ("earnings", "revenue", "eps", "财报", "营收")):
        return "corporate"

    return ""  # unknown → use default half-life


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

    # Infer event type for half-life lookup
    ev_type = _infer_event_type(macro_tags, strategic_matches, news_text)

    # 1. Timeliness (event-type-specific half-life)
    timely = timeliness_factor(published_at, is_breaking, ev_type)

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
        "event_type": ev_type,
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
