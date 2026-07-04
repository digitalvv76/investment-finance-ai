"""Fast lane rule engine — detects breaking/urgent news < 5 seconds.

Refactored: delegates entity extraction to EntityExtractor and
priority scoring to PriorityScorer. FastLane is now a thin orchestration
layer that coordinates extraction + scoring + filtering.
"""
import logging
import re
from typing import List, Optional

from storage.models import NewsItem
from config.loader import ConfigLoader
from engine.entity_extractor import EntityExtractor
from engine.priority import PriorityScorer
from engine.strategic_detector import StrategicDetector
from engine.content_filter import geo_market_filter, content_quality_filter

logger = logging.getLogger(__name__)


class FastLane:
    """Rule-based engine that processes news items through fast-lane filters.

    Detects breaking news markers, extracts tickers from watchlist,
    identifies macro-economic tags and key people mentions, then
    computes a priority score. Only items at or above the threshold
    (0.3) are returned as push-worthy.

    Delegates to:
        EntityExtractor — tickers, companies, people, indicators, sectors
        PriorityScorer — multi-factor priority score computation

    Uses optional VectorStore for semantic multi-source resonance detection.
    Falls back to word-overlap Jaccard similarity when VectorStore is unavailable.
    """

    def __init__(self, config: ConfigLoader, db, watchlist_tickers: List[str] = None, vector_store=None):
        self.db = db

        # Sub-modules
        self._extractor = EntityExtractor(config)
        self._scorer = PriorityScorer()
        self._vector_store = vector_store
        self._strategic = StrategicDetector()

        # People tiers (loaded from keywords.yaml)
        self._people_tiers: dict[str, int] = {}  # name_lower → tier (1/2/3)
        self._load_people_tiers(config)

        # Breaking markers (kept here for fast _is_breaking check)
        keywords = {}
        try:
            keywords = config.load_keywords()
        except Exception:
            pass
        self._breaking_patterns = [
            re.compile(re.escape(w), re.IGNORECASE)
            for w in keywords.get('breaking_markers', [
                'BREAKING', 'URGENT', 'ALERT', 'JUST IN', 'FLASH', 'DEVELOPING', 'EXCLUSIVE'
            ])
        ]

        # Watchlist
        self.watchlist = watchlist_tickers or self._load_watchlist()

    def _load_watchlist(self) -> List[str]:
        """Load watchlist tickers from memory file."""
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
        try:
            from pathlib import Path
            path = Path("../../.claude/memory/watchlist-state.md")
            if path.exists():
                text = path.read_text()
                found = re.findall(r'\|\s*([A-Z]{1,5})\s*\|', text)
                tickers = [t for t in found if t.isalpha() and 1 <= len(t) <= 5]
        except Exception:
            pass
        return tickers

    def _load_people_tiers(self, config: ConfigLoader):
        """Load tiered key_people from keywords.yaml.

        Builds a name→tier lookup for use in _detect_people_tier().
        Falls back gracefully if keywords are unavailable.
        """
        try:
            keywords = config.load_keywords()
            for name in keywords.get('key_people_tier1', []):
                self._people_tiers[name.lower()] = 1
            for name in keywords.get('key_people_tier2', []):
                self._people_tiers[name.lower()] = 2
            for name in keywords.get('key_people_tier3', []):
                self._people_tiers[name.lower()] = 3
        except Exception:
            pass
        # Also populate from legacy key_people as tier 3 (safe default)
        try:
            keywords = config.load_keywords()
            for name in keywords.get('key_people', []):
                if name.lower() not in self._people_tiers:
                    self._people_tiers[name.lower()] = 3
        except Exception:
            pass

    def _detect_people_tier(self, text: str, entities: dict) -> tuple[bool, int]:
        """Detect the highest-tier person mentioned in the text.

        Returns (has_people: bool, highest_tier: int).
        Tier 1 = market pricer, Tier 2 = influencer, Tier 3 = political.
        Default tier 1 if person found but not in known list.
        """
        people = entities.get('people', [])
        if not people:
            # Also check raw text for known names (more robust)
            text_lower = text.lower()
            best_tier = 3
            found_any = False
            for name, tier in self._people_tiers.items():
                if name.lower() in text_lower:
                    found_any = True
                    best_tier = min(best_tier, tier)
            return (found_any, best_tier) if found_any else (False, 1)

        # spaCy found people entities
        best_tier = 1  # default: unknown person → assume high tier
        for person_name in people:
            tier = self._people_tiers.get(person_name.lower(), 1)
            # Unknown names get tier 1 (safe: don't penalize unrecognized people)
            best_tier = min(best_tier, tier)
        return (True, best_tier)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, items: List[NewsItem]) -> List[NewsItem]:
        """Process news items through fast lane rules.

        For each item:
        1. Extract entities via EntityExtractor
        2. Detect people tier (tiered: 1=mkt pricer, 2=influencer, 3=political)
        3. Content filter — demote non-US-political/single-stock/propaganda
        4. Score via PriorityScorer (with tiered people bonus)
        5. Strategic detection — government / NVIDIA investment (always pass)
        6. Urgent keyword interrupt
        7. Return items that meet fast lane threshold (>= 0.3)
        """
        pushed = []

        for item in items:
            text = f"{item.title or ''} {item.content_snippet or ''}"

            # 1. Entity extraction
            entities = self._extractor.extract(text)
            tickers = set(entities.get('tickers', []))
            macro_tags = set(entities.get('indicators', []))

            # 2. Detect people tier (tiered: replaces flat has_people boolean)
            has_people, people_tier = self._detect_people_tier(text, entities)
            item._people_tier = people_tier

            # 2.5. Content quality & geo-market filter (NEW)
            # Runs BEFORE scoring to suppress noise before it gets any points.
            source = getattr(item, 'source', '') or getattr(item, 'source_name', '') or ''
            tickers_str = item.tickers_found or ','.join(tickers) if tickers else ''

            geo_mult = geo_market_filter(text, source)
            quality_mult = content_quality_filter(text, tickers_str)
            item._filter_mult = round(geo_mult * quality_mult, 3)

            # 3. Breaking detection
            item.is_breaking = self._is_breaking(text)

            # 4. Tag the item with extracted entities
            item.tickers_found = ','.join(tickers) if tickers else ''
            item.macro_tags = ','.join(macro_tags) if macro_tags else ''

            # 5. Priority scoring (with tiered people)
            resonance = self._check_multi_source(text)
            raw_score = self._scorer.score(
                item,
                tickers=tickers,
                macro_tags=macro_tags,
                has_people=has_people,
                similar_count=resonance,
            )

            # Apply content filter multiplier AFTER raw scoring
            item.priority_score = round(raw_score * item._filter_mult, 4)

            # 6. Strategic event detection — government / NVIDIA investment
            # Strategic events BYPASS the content filter (forced score=1.0)
            strategic = self._strategic.detect(text)
            if strategic:
                best = strategic[0]
                # Strategic events override ALL filtering
                item.priority_score = max(item.priority_score, 1.0)
                item._filter_mult = 1.0
                item.macro_tags = (item.macro_tags + f',STRATEGIC_{best.category.upper()}').strip(',')
                # Extract target company tickers near the match
                related = self._strategic.extract_mentioned_tickers(text, set(self.watchlist))
                if related:
                    item.tickers_found = ','.join(set(
                        item.tickers_found.split(',') + list(related)
                    )).strip(',')

            # 7. Urgent keyword interrupt — bypasses scoring threshold
            is_urgent = self._check_urgent_keywords(text)
            if is_urgent:
                item.priority_score = max(item.priority_score, 0.95)
                item.macro_tags = (item.macro_tags + ',URGENT').strip(',')

            # Log demotions for debugging
            if item._filter_mult < 0.5:
                logger.debug(
                    "Content filter: ×%.2f → score=%.3f (raw=%.3f) — %s",
                    item._filter_mult, item.priority_score, raw_score,
                    (item.title or '')[:80],
                )

            if item.priority_score >= 0.3:  # Fast lane threshold
                item.status = 'fast_pushed'
                pushed.append(item)

        logger.info("Fast lane: %d/%d items pass threshold", len(pushed), len(items))
        return pushed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_breaking(self, text: str) -> bool:
        """Check if text contains breaking news markers."""
        for pattern in self._breaking_patterns:
            if pattern.search(text):
                return True
        return False

    def _check_urgent_keywords(self, text: str) -> bool:
        """Check if text matches any user-set urgent interrupt keywords.

        These keywords bypass the normal scoring threshold — matching news
        is automatically elevated to priority 0.95 and force-pushed.
        """
        try:
            urgent_raw = self.db.get_preference("urgent_keywords") or ""
            if not urgent_raw:
                return False
            keywords = [k.strip() for k in urgent_raw.split(",") if k.strip()]
            text_lower = text.lower()
            for kw in keywords:
                if kw.lower() in text_lower:
                    logger.info("Fast lane: urgent keyword '%s' matched — force push", kw)
                    return True
        except Exception:
            pass
        return False

    def _check_multi_source(self, text: str) -> int:
        """Count how many similar articles appeared recently.

        Uses vector store semantic search when available; falls back to
        word-overlap heuristics when ChromaDB is not configured.

        Returns the count of similar articles (used for resonance scoring).
        """
        if not text.strip():
            return 0

        # Primary: semantic similarity via VectorStore
        if self._vector_store and self._vector_store.is_ready:
            try:
                similar_ids = self._vector_store.find_similar(
                    text, threshold=0.82, max_results=10
                )
                return len(similar_ids)
            except Exception as e:
                logger.debug("VectorStore resonance check failed: %s", e)

        # Fallback: word-overlap heuristic
        try:
            recent = self.db.get_recent_news(hours=0.083)  # ~5 minutes
            similar_count = 0
            for item in recent:
                words1 = set(text.lower().split())
                words2 = set(item.get('title', '').lower().split())
                overlap = len(words1 & words2)
                if overlap > len(words1) * 0.3:  # 30% word overlap
                    similar_count += 1
            return similar_count
        except Exception:
            return 0
