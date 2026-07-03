"""Historical event matcher for news impact calibration.

Parses the training dataset (config/training_news_events_2026H1.md) into
structured HistoricalEvent records, then matches incoming news against
them by event category + keyword overlap.

Used by ImpactEvaluator to inject few-shot historical examples into the
LLM prompt, improving impact prediction accuracy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Path to the training dataset (relative to this file)
_TRAINING_DATA = Path(__file__).resolve().parents[1] / "config" / "training_news_events_2026H1.md"

# Map Chinese section headers to event_category values used by ImpactEvaluator.
SECTION_CATEGORY_MAP = {
    "货币政策": "monetary",
    "地缘政治": "geopolitical",
    "宏观经济": "macro_data",
    "科技": "corporate",
    "并购": "corporate",
    "IPO": "corporate",
    "财报": "corporate",
    "贸易政策": "regulatory",
    "银行": "regulatory",
    "能源": "macro_data",
    "加密货币": "macro_data",
    "医疗": "corporate",
}

# Impact level to numeric score
IMPACT_TO_SCORE = {
    "CRITICAL": 90,
    "HIGH": 65,
    "MEDIUM": 40,
    "LOW": 20,
}


@dataclass
class HistoricalEvent:
    """A single historical market event from the training dataset."""
    date: str
    description: str
    impact_level: str          # CRITICAL / HIGH / MEDIUM / LOW
    impact_score: int          # 0-100 numeric
    market_reaction: str       # raw text of market moves
    affected_tickers: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    category: str = ""         # mapped event_category


class EventMatcher:
    """Match incoming news to similar historical events for impact calibration."""

    def __init__(self, data_path: Optional[Path] = None):
        self._events: list[HistoricalEvent] = []
        self._loaded = False
        self._data_path = data_path or _TRAINING_DATA

    # ------------------------------------------------------------------
    # Loading & parsing
    # ------------------------------------------------------------------

    def _ensure_loaded(self):
        if not self._loaded:
            self._events = self._parse_training_file()
            self._loaded = True
            logger.info("EventMatcher: loaded %d historical events", len(self._events))

    def _parse_training_file(self) -> list[HistoricalEvent]:
        """Parse the training markdown file into HistoricalEvent records."""
        if not self._data_path.is_file():
            logger.warning("EventMatcher: training data not found at %s", self._data_path)
            return []

        text = self._data_path.read_text(encoding="utf-8")
        events = []
        current_section = ""
        current_event: Optional[dict] = None

        for line in text.split("\n"):
            line = line.strip()

            # Track section headers (## 一、货币政策...)
            section_match = re.match(r"##\s+[一二三四五六七八九十]+、(.+)", line)
            if section_match:
                section_name = section_match.group(1)
                for key, cat in SECTION_CATEGORY_MAP.items():
                    if key in section_name:
                        current_section = cat
                        break
                continue

            # New event starts with "### N.M"
            if re.match(r"###\s+\d+\.\d+", line):
                if current_event and current_event.get("description"):
                    events.append(self._dict_to_event(current_event, current_section))
                current_event = {"description": ""}
                continue

            if current_event is None:
                continue

            # Parse fields
            if line.startswith("- **日期**:"):
                current_event["date"] = line.split("**:", 1)[-1].strip()
            elif line.startswith("- **事件**:"):
                current_event["description"] = line.split("**:", 1)[-1].strip()
            elif line.startswith("- **影响级别**:"):
                level_text = line.split("**:", 1)[-1].strip()
                # Extract emoji + text: "🔴 CRITICAL" -> "CRITICAL"
                current_event["impact_level"] = _extract_impact_level(level_text)
                current_event["impact_score"] = IMPACT_TO_SCORE.get(
                    current_event["impact_level"], 30
                )
            elif line.startswith("- **市场反应**:"):
                current_event["market_reaction"] = line.split("**:", 1)[-1].strip()
            elif line.startswith("- **受影响标的**:"):
                raw = line.split("**:", 1)[-1].strip()
                current_event["affected_tickers"] = [t.strip() for t in raw.split(",") if t.strip()]
            elif line.startswith("- **分类标签**:"):
                raw = line.split("**:", 1)[-1].strip()
                current_event["tags"] = [t.strip("` ") for t in raw.split(",") if t.strip("` ")]

            # Collect multi-line market reaction
            elif current_event.get("market_reaction") and line.startswith("- "):
                current_event["market_reaction"] += " " + line.lstrip("- ")

        # Don't forget the last event
        if current_event and current_event.get("description"):
            events.append(self._dict_to_event(current_event, current_section))

        return events

    @staticmethod
    def _dict_to_event(d: dict, section_category: str) -> HistoricalEvent:
        return HistoricalEvent(
            date=d.get("date", ""),
            description=d.get("description", ""),
            impact_level=d.get("impact_level", "MEDIUM"),
            impact_score=d.get("impact_score", 30),
            market_reaction=d.get("market_reaction", ""),
            affected_tickers=d.get("affected_tickers", []),
            tags=d.get("tags", []),
            category=section_category,
        )

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match(
        self, news_text: str, event_category: str = "", top_k: int = 3
    ) -> list[HistoricalEvent]:
        """Find the most similar historical events.

        Matching strategy:
        1. Priority boost for same-category events.
        2. Keyword overlap between news_text and event description + tags.
        3. Return top-k, sorted by relevance.

        Args:
            news_text: The news title + snippet to match against.
            event_category: The LLM-classified event type (monetary/geopolitical/...).
            top_k: Number of matches to return.

        Returns:
            Up to top_k HistoricalEvent records, best matches first.
        """
        self._ensure_loaded()
        if not self._events:
            return []

        # Empty or near-empty text → no meaningful match possible
        news_lower = news_text.lower().strip()
        if len(news_lower) < 10:
            return []

        scored = []
        for evt in self._events:
            score = 0.0

            # Category bonus: same category gets +30 base
            if event_category and evt.category == event_category:
                score += 30

            # Keyword overlap: each tag word found in news_text adds points
            for tag in evt.tags:
                if tag.lower() in news_lower:
                    score += 8
            # Word overlap with event description
            desc_words = set(evt.description.lower().split())
            news_words = set(news_lower.split())
            overlap = desc_words & news_words
            score += len(overlap) * 0.5

            # Impact level bonus: CRITICAL events get small boost
            if evt.impact_level == "CRITICAL":
                score += 5

            # Require a minimum score to filter out noise matches
            if score >= 10:
                scored.append((score, evt))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [evt for _, evt in scored[:top_k]]

    def format_for_prompt(self, matches: list[HistoricalEvent]) -> str:
        """Format matched events as a prompt-ready string for LLM injection."""
        if not matches:
            return "No similar historical events found."

        lines = []
        for i, evt in enumerate(matches, 1):
            lines.append(
                f"{i}. [{evt.date}] {evt.impact_level} — {evt.description}"
            )
            if evt.market_reaction:
                lines.append(f"   Market reaction: {evt.market_reaction[:200]}")
            if evt.affected_tickers:
                lines.append(f"   Affected: {', '.join(evt.affected_tickers[:8])}")
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def event_count(self) -> int:
        self._ensure_loaded()
        return len(self._events)

    def get_examples(self, news_text: str, event_category: str = "", top_k: int = 3) -> str:
        """Convenience: match + format in one call. Returns prompt-ready text."""
        matches = self.match(news_text, event_category, top_k=top_k)
        return self.format_for_prompt(matches)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_impact_level(text: str) -> str:
    """Extract plain-text impact level from emoji-prefixed string.

    Examples:
        "🔴 CRITICAL" -> "CRITICAL"
        "🟠 HIGH" -> "HIGH"
        "🟡 MEDIUM" -> "MEDIUM"
        "🟢 LOW" -> "LOW"
    """
    for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if level in text.upper():
            return level
    return "MEDIUM"
