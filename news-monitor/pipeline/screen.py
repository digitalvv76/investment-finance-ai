"""SCREEN stage: wraps FastLane for entity extraction + priority scoring."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem

if TYPE_CHECKING:
    from engine.fast_lane import FastLane

logger = logging.getLogger(__name__)

SCREEN_THRESHOLD = 0.40  # Minimum priority_score to continue


class ScreenStage:
    """Pipeline stage 1: fast-rule screening via FastLane.

    Runs entity extraction, content quality filter, geo-market filter,
    priority scoring, and strategic event detection. Items with
    priority_score < 0.3 are dropped (not worth further processing).
    """

    def __init__(self, fast_lane: FastLane) -> None:
        self._fl = fast_lane

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        # Convert PipelineItem → NewsItem for FastLane compatibility
        from storage.models import NewsItem
        from datetime import datetime

        news_items = []
        for it in items:
            news = NewsItem(
                id=it.id,
                title=it.title,
                source=it.source,
                url=it.url,
                content_snippet=it.snippet,
                tickers_found=it.tickers_found or ",".join(it.raw_tickers),
                macro_tags=it.macro_tags,
                published_at=datetime.now(),
            )
            news_items.append(news)

        try:
            enriched_list = self._fl.process(news_items)
        except Exception:
            logger.exception("SCREEN: FastLane.process batch failure")
            return []

        # Merge enriched fields back into PipelineItems
        results: list[PipelineItem] = []
        for enriched in enriched_list:
            try:
                item_id = enriched.id or 0
                match = next((it for it in items if it.id == item_id), None)
                if match is None:
                    continue

                match.priority_score = float(getattr(enriched, "priority_score", 0) or 0)
                match.tickers_found = str(getattr(enriched, "tickers_found", "") or "")
                match.macro_tags = str(getattr(enriched, "macro_tags", "") or "")
                match.is_breaking = bool(getattr(enriched, "is_breaking", False))
                match.people_tier = int(getattr(enriched, "_people_tier", 0) or 0)

                if match.priority_score >= SCREEN_THRESHOLD:
                    results.append(match)
            except Exception:
                logger.exception("SCREEN: per-item enrichment failed for id=%s",
                                 getattr(enriched, "id", "?"))

        logger.info("SCREEN: %d in → %d out (threshold=%.2f)",
                     len(items), len(results), SCREEN_THRESHOLD)
        return results
