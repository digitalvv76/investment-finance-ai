"""Multi-factor priority score calculator for news items.

Factors:
    1. breaking     — is_breaking flag
    2. macro_tags   — sector/theme tag hits
    3. ticker_hits  — ticker symbol mentions
    4. people       — key people mentions
    5. source       — source authority/trust
    6. resonance    — multi-source confirmation
    7. deviation    — macro data deviation from expectations (NEW)
    8. surprise     — unexpected/shocking events (NEW)
    9. asset_linkage — multi-asset-class impact (NEW)

Extracted from fast_lane.py as a shared module. Used by both the fast lane
rule engine and the deep lane orchestrator.
"""
import logging
import re
from typing import Dict, List, Optional, Set

from storage.models import NewsItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weight constants — tunable via config
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    "breaking": 0.35,
    "macro_per_tag": 0.12,
    "ticker_per_hit": 0.08,
    "people": 0.15,
    "source_authority": 0.10,
    "resonance_max": 0.20,
    "deviation": 0.25,       # NEW: macro data deviation magnitude
    "surprise": 0.15,        # NEW: unexpected/shocking nature
    "asset_linkage": 0.15,   # NEW: cross-asset impact
}

# Source authority scores (higher = more trusted/urgent)
SOURCE_AUTHORITY: Dict[str, float] = {
    # —— Tier 1: English primary sources ——
    "bloomberg": 0.10,
    "bloomberg markets": 0.10,
    "reuters": 0.10,
    "reuters business": 0.10,
    "cnbc": 0.08,
    "cnbc top news": 0.08,
    "cnbc live blog": 0.09,
    "cnbc economy": 0.07,
    "wsj": 0.10,
    "wsj markets": 0.10,
    "marketwatch": 0.06,
    "yahoo finance": 0.05,
    "seeking alpha": 0.04,
    "seeking alpha market outlook": 0.04,
    "investing.com": 0.04,
    "zerohedge": 0.03,
    "sec edgar 8-k": 0.10,
    "fred economic releases": 0.09,
    # Twitter — English accounts (primary)
    "@elerianm": 0.07,
    "@lisaabramowicz1": 0.07,
    "@bespokeinvest": 0.06,
    "@newsquawk": 0.07,
    "@zerohedge": 0.03,
    "@fxhedgers": 0.05,
    "@semianalysis": 0.09,  # Semiconductor/AI supply chain — very high signal
    # —— Tier 2: Chinese supplementary sources ——
    # WallStreetCN is China's best financial newswire — on par with Bloomberg terminal
    # for Chinese markets & macro coverage. Raised from 0.02 to 0.05-0.06.
    "新浪财经·7x24综合快讯": 0.04,
    "新浪财经·7x24全球财经": 0.04,
    "华尔街见闻·全球快讯": 0.06,
    "华尔街见闻·美股": 0.06,
    "华尔街见闻·外汇": 0.05,
    "华尔街见闻·加密货币": 0.05,
    "华尔街见闻·大宗商品": 0.05,
}
# Default for unknown sources: 0.03 (lower than any Tier-1 English source)

# Priority thresholds
URGENT_THRESHOLD = 0.7
IMPORTANT_THRESHOLD = 0.4
FAST_LANE_THRESHOLD = 0.3

# ---------------------------------------------------------------------------
# Deviation detection — macro data vs expectations
# ---------------------------------------------------------------------------

# Patterns for extracting "X vs Y expected" deviations
_DEVIATION_PATTERNS = [
    # "CPI 2.9% vs 2.7% expected" or "175K vs 190K expected"
    re.compile(
        r"(?P<actual>[\d,.]+[KMB%]?)\s*(?:vs|versus|vs\.)\s*(?P<expected>[\d,.]+[KMB%]?)\s*(?:expected|forecast|estimate|est\.?)",
        re.IGNORECASE,
    ),
    # "2.9% (expected 2.7%)"
    re.compile(
        r"(?P<actual>[\d,.]+%?)\s*\(?(?:expected|forecast|est\.?)\s*(?P<expected>[\d,.]+%?)",
        re.IGNORECASE,
    ),
    # "beat expectations of 2.7%" / "below forecasts of 200K"
    re.compile(
        r"(?:beat|beats|beating|above|below|miss|misses|missed)\s+(?:expectations|forecasts?|estimates?)\s+(?:of\s+)?(?P<expected>[\d,.]+[KMB%]?)",
        re.IGNORECASE,
    ),
    # "surged 285K vs 200K expected"
    re.compile(
        r"(?:surged?|rose|fell|dropped?|added?|gained?|lost)\s+(?P<actual>[\d,.]+[KMB%]?)\s+(?:vs|versus|vs\.)\s+(?P<expected>[\d,.]+[KMB%]?)\s*(?:expected|forecast)",
        re.IGNORECASE,
    ),
    # "fell 0.8% vs expected 0.2% gain"
    re.compile(
        r"(?:fell|dropped?|rose|gained?|added?)\s+(?P<actual>-?[\d,.]+%?)\s+(?:vs|versus|vs\.)\s+(?:expected|forecast)\s+(?P<expected>[+\-]?[\d,.]+%?)",
        re.IGNORECASE,
    ),
    # "beat estimates" / "missed forecasts" without numbers
    re.compile(
        r"(?P<direction>beat|beats|beating|miss|misses|missed|above|below|exceed[s]?|topped)\s+(?:the\s+)?(?:expectations|forecasts?|estimates?|consensus)",
        re.IGNORECASE,
    ),
    # —— Chinese deviation patterns ——
    # "高于预期2.5%" / "超出市场预估190K"
    re.compile(
        r"(?P<actual>[\d,.]+[KMB%万亿]?)\s*(?:高于|超出|超过|好于|强于)\s*(?:市场|一致)?(?:预期|预估|预测|估计)\w*(?:的\s*)?(?P<expected>[\d,.]+[KMB%]?)?",
    ),
    # "低于预期" / "不及市场预估"
    re.compile(
        r"(?P<actual>[\d,.]+[KMB%万亿]?)\s*(?:低于|不及|弱于|差于|逊于)\s*(?:市场|一致)?(?:预期|预估|预测|估计)\w*(?:的\s*)?(?P<expected>[\d,.]+[KMB%]?)?",
    ),
    # "预期2.5%实际2.7%" / "市场预估190K结果285K"
    re.compile(
        r"(?:市场|一致)?(?:预期|预估|预测|估计)\s*(?P<expected>[\d,.]+[KMB%]?)\s*(?:实际|结果|公布|录得|报)\s*(?P<actual>[\d,.]+[KMB%万亿]?)",
    ),
    # "大超预期" / "远低预期" — qualitative only (direction, no numbers)
    re.compile(
        r"(?P<direction>大超|远超|大幅?超|大幅?高[于出]|大幅?低[于出]|远低[于出]|不及|逊于)\s*(?:市场|一致)?(?:预期|预估)",
    ),
]

# ---------------------------------------------------------------------------
# Surprise factor — unexpected/shocking keywords
# ---------------------------------------------------------------------------

_SURPRISE_KEYWORDS = [
    # Strong surprise
    ("unexpectedly", 1.0),
    ("shock", 1.0),
    ("shocks", 1.0),
    ("surprise", 0.8),
    ("surprises", 0.8),
    ("record high", 0.7),
    ("record low", 0.7),
    ("all-time high", 0.7),
    ("all-time low", 0.7),
    ("plunge", 0.8),
    ("plunges", 0.8),
    ("surge", 0.7),
    ("surges", 0.7),
    ("tumble", 0.7),
    ("tumbles", 0.7),
    ("soar", 0.7),
    ("soars", 0.7),
    ("crash", 0.9),
    ("crashes", 0.9),
    ("panic", 0.9),
    ("meltdown", 0.9),
    # Moderate surprise
    ("slump", 0.6),
    ("slumps", 0.6),
    ("rout", 0.7),
    ("jump", 0.5),
    ("jumps", 0.5),
    ("leap", 0.5),
    ("spike", 0.6),
    ("spikes", 0.6),
    # Policy surprise
    ("unexpected", 0.8),
    ("abruptly", 0.7),
    ("sudden", 0.6),
    ("dramatically", 0.6),
    # —— Chinese surprise keywords ——
    ("意外", 0.8), ("出乎意料", 0.8), ("出人意料", 0.8),
    ("震惊", 0.9), ("震惊全球", 1.0),
    ("暴跌", 0.8), ("暴涨", 0.7), ("闪崩", 0.9), ("熔断", 0.9),
    ("创纪录", 0.7), ("创历史新高", 0.7), ("创历史新低", 0.7),
    ("历史新高", 0.7), ("历史新低", 0.7), ("历史最高", 0.7),
    ("崩盘", 0.9), ("恐慌", 0.9), ("恐慌性", 0.9),
    ("黑天鹅", 0.9), ("灰犀牛", 0.7),
    ("突然", 0.6), ("骤然", 0.6), ("急剧", 0.6),
    ("大跌", 0.6), ("大涨", 0.5), ("飙升", 0.7), ("骤降", 0.7),
    ("大幅跳涨", 0.7), ("大幅跳水", 0.8),
    ("史诗级", 0.8), ("历史性", 0.7),
]

# ---------------------------------------------------------------------------
# Asset linkage — multi-asset-class keywords
# ---------------------------------------------------------------------------

_ASSET_CLASSES = {
    "equities": [
        "s&p", "nasdaq", "dow", "stock", "stocks", "equity", "equities",
        "index", "indices", "nvidia", "apple", "tesla", "semiconductor",
        "费城半导体", "板块", "领跌", "领涨", "普跌", "普涨",
        "auto", "autos", "automaker", "automakers", "automotive",
        "clean energy", "solar", "ev ", "electric vehicle",
        "tech", "big tech", "chip", "chips",
    ],
    "bonds": [
        "bond", "bonds", "treasury", "treasuries", "yield", "yields",
        "10y", "10-year", "2-year", "30-year", "收益率", "国债",
        "basis point", "bp", "bps", "fed funds",
    ],
    "currencies": [
        "dollar", "usd", "eur", "jpy", "gbp", "fx", "forex",
        "currency", "currencies", "dxy", "美元", "汇率",
        "dollar index",
    ],
    "commodities": [
        "oil", "crude", "brent", "wti", "gold", "silver", "copper",
        "commodity", "commodities", "opec", "原油", "黄金", "大宗商品",
        "natural gas", "energy",
    ],
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto",
        "比特币", "以太坊", "digital asset",
    ],
}


class PriorityScorer:
    """Compute priority scores for news items.

    Priority formula (9 factors):
        breaking × 0.35 + macro(tag × 0.12) + ticker(hit × 0.08)
        + people × 0.15 + source_authority × 0.10
        + resonance + deviation + surprise + asset_linkage

    Supports dynamic weight overrides from Learner engine.
    """

    def __init__(self, weights: dict = None):
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self._source_weights: dict = {}  # Learner-populated
        self._threshold: float = FAST_LANE_THRESHOLD  # Learner-adjustable

    def set_source_weights(self, weights: dict):
        """Override source authority scores (called by Learner)."""
        self._source_weights = {k.lower(): v for k, v in weights.items()}

    def set_threshold(self, threshold: float):
        """Override fast lane threshold (called by Learner)."""
        self._threshold = max(0.15, min(0.50, threshold))

    @property
    def threshold(self) -> float:
        return self._threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        item: NewsItem,
        tickers: Set[str] = None,
        macro_tags: Set[str] = None,
        has_people: bool = False,
        similar_count: int = 0,
    ) -> float:
        """Compute the priority score for a news item."""
        score = 0.0
        text = getattr(item, "title", "") or ""

        # 1. Breaking news bonus
        if getattr(item, "is_breaking", False):
            score += self.weights["breaking"]

        # 2. Macro tag hits
        if macro_tags:
            score += min(0.36, len(macro_tags) * self.weights["macro_per_tag"])

        # 3. Ticker hits
        if tickers:
            score += min(0.24, len(tickers) * self.weights["ticker_per_hit"])

        # 4. Key people mentions (tiered)
        if has_people:
            score += self._people_score(getattr(item, "_people_tier", 1))

        # 5. Source authority
        source = getattr(item, "source", "") or getattr(item, "source_name", "") or ""
        score += self._source_authority(source)

        # 6. Multi-source resonance
        if similar_count:
            score += self._resonance_bonus(similar_count)

        # ---- NEW FACTORS ----

        # 7. Deviation magnitude (macro data vs expectations)
        score += self._deviation_score(text)

        # 8. Surprise factor
        score += self._surprise_score(text)

        # 9. Asset linkage (cross-asset impact)
        score += self._asset_linkage_score(text)

        return round(score, 4)

    def score_batch(
        self,
        items: List[NewsItem],
        tickers_map: Dict[int, Set[str]] = None,
        macro_map: Dict[int, Set[str]] = None,
        people_map: Dict[int, bool] = None,
    ) -> List[NewsItem]:
        """Score a batch of items, updating their priority_score in place."""
        pushed = []
        for idx, item in enumerate(items):
            # Use item.id when available (persisted items), fall back to list
            # index for newly-created items that haven't been assigned a DB id.
            key = item.id if item.id is not None else idx
            tickers = (tickers_map or {}).get(key, set())
            macros = (macro_map or {}).get(key, set())
            has_people = (people_map or {}).get(key, False)

            item.priority_score = self.score(item, tickers, macros, has_people)

            if item.priority_score >= self._threshold:
                item.status = 'fast_pushed'
                pushed.append(item)

        logger.info(
            "PriorityScorer: %d/%d items pass fast lane threshold",
            len(pushed), len(items),
        )
        return pushed

    def classify(self, score: float) -> str:
        """Classify a priority score into urgency level."""
        if score >= URGENT_THRESHOLD:
            return "urgent"
        elif score >= IMPORTANT_THRESHOLD:
            return "important"
        elif score >= FAST_LANE_THRESHOLD:
            return "notable"
        else:
            return "general"

    # ------------------------------------------------------------------
    # NEW: Deviation magnitude (预期差幅度)
    # ------------------------------------------------------------------

    def _deviation_score(self, text: str) -> float:
        """Score how much a macro data point deviates from expectations.

        Detects patterns like "2.9% vs 2.7% expected" and computes
        the magnitude of surprise. Larger deviations → higher score.
        """
        if not text:
            return 0.0

        max_deviation = 0.0

        for pattern in _DEVIATION_PATTERNS:
            for m in pattern.finditer(text):
                groups = m.groupdict()

                # Case 1: directional beat/miss without numbers
                direction = groups.get("direction")
                if direction and not groups.get("actual"):
                    if direction in ("beat", "beats", "beating", "exceed", "exceeds", "topped", "above"):
                        max_deviation = max(max_deviation, 0.4)
                    elif direction in ("miss", "misses", "missed", "below"):
                        max_deviation = max(max_deviation, 0.5)
                    continue

                # Case 2: numeric comparison
                actual_str = groups.get("actual")
                expected_str = groups.get("expected")
                if not actual_str or not expected_str:
                    continue

                try:
                    actual = self._parse_number(actual_str)
                    expected = self._parse_number(expected_str)
                except ValueError:
                    continue

                if expected == 0:
                    continue

                # Compute relative deviation
                deviation = abs(actual - expected) / abs(expected)

                # Score based on deviation magnitude (macro-sensitive thresholds)
                # Macro data: even small % deviations are significant
                # e.g. CPI 2.9% vs 2.7% = 7.4% deviation → major event
                if deviation >= 0.40:    # e.g. -0.8% vs +0.2% → 500% deviation
                    max_deviation = max(max_deviation, 1.0)
                elif deviation >= 0.15:
                    max_deviation = max(max_deviation, 0.9)
                elif deviation >= 0.07:   # CPI 2.9% vs 2.7% = 7.4%
                    max_deviation = max(max_deviation, 0.7)
                elif deviation >= 0.04:
                    max_deviation = max(max_deviation, 0.5)
                elif deviation >= 0.02:
                    max_deviation = max(max_deviation, 0.35)
                else:
                    max_deviation = max(max_deviation, 0.2)

        return round(max_deviation * self.weights["deviation"], 4)

    # ------------------------------------------------------------------
    # NEW: Surprise factor (意外性)
    # ------------------------------------------------------------------

    def _surprise_score(self, text: str) -> float:
        """Score based on surprise/shock keywords in the text.

        Returns a weighted score based on the strongest surprise signal found.
        """
        if not text:
            return 0.0

        text_lower = text.lower()
        max_intensity = 0.0

        for keyword, intensity in _SURPRISE_KEYWORDS:
            if keyword in text_lower:
                max_intensity = max(max_intensity, intensity)

        return round(max_intensity * self.weights["surprise"], 4)

    # ------------------------------------------------------------------
    # NEW: Asset linkage (资产联动)
    # ------------------------------------------------------------------

    def _asset_linkage_score(self, text: str) -> float:
        """Score based on how many asset classes are mentioned together.

        More asset classes = broader market impact = higher priority.
        """
        if not text:
            return 0.0

        text_lower = text.lower()
        classes_hit = 0

        for class_name, keywords in _ASSET_CLASSES.items():
            if any(kw in text_lower for kw in keywords):
                classes_hit += 1

        # Scale: 0 classes → 0, 1 → 0.3, 2 → 0.6, 3+ → 1.0
        if classes_hit >= 4:
            factor = 1.0
        elif classes_hit == 3:
            factor = 0.9
        elif classes_hit == 2:
            factor = 0.6
        elif classes_hit == 1:
            factor = 0.3
        else:
            factor = 0.0

        return round(factor * self.weights["asset_linkage"], 4)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _source_authority(self, source: str) -> float:
        """Get authority score for a source name."""
        if not source:
            return 0.0
        key = source.lower()
        if key in self._source_weights:
            return self._source_weights[key]
        return SOURCE_AUTHORITY.get(key, 0.03)

    def _resonance_bonus(self, similar_count: int) -> float:
        """Compute resonance bonus based on number of similar articles."""
        if similar_count >= 5:
            return self.weights["resonance_max"]
        elif similar_count >= 3:
            return self.weights["resonance_max"] * 0.75
        elif similar_count >= 2:
            return self.weights["resonance_max"] * 0.5
        return 0.0

    # ------------------------------------------------------------------
    # People scoring (tiered)
    # ------------------------------------------------------------------

    # Default weights per tier — overridable via set_people_weights()
    _PEOPLE_TIER_WEIGHTS = {1: 0.15, 2: 0.10, 3: 0.03}

    def set_people_weights(self, tier1: float = 0.15, tier2: float = 0.10,
                           tier3: float = 0.03):
        """Override people tier weights (called from FastLane on init)."""
        self._PEOPLE_TIER_WEIGHTS = {1: tier1, 2: tier2, 3: tier3}

    def _people_score(self, tier: int = 1) -> float:
        """Return the people bonus for a given tier.

        Tier 1 = market pricer (Jensen Huang, Powell, Warsh) → full weight
        Tier 2 = market influencer (Musk, Buffett) → reduced
        Tier 3 = political figure (Trump, Xi) → minimal
        """
        return self._PEOPLE_TIER_WEIGHTS.get(tier, self.weights["people"])

    @staticmethod
    def _parse_number(s: str) -> float:
        """Parse a numeric string, handling K/M/B suffixes and percentages."""
        s = s.strip().replace(",", "").replace("+", "").replace("−", "-")
        multiplier = 1.0
        if s.upper().endswith("K"):
            multiplier = 1000
            s = s[:-1]
        elif s.upper().endswith("M"):
            multiplier = 1000000
            s = s[:-1]
        elif s.upper().endswith("B"):
            multiplier = 1000000000
            s = s[:-1]
        if s.endswith("%"):
            s = s[:-1]
        return float(s) * multiplier
