"""DEEP stage: async DeepLane analysis for high-impact items (fire-and-forget)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem

if TYPE_CHECKING:
    from engine.deep_lane import DeepLane

logger = logging.getLogger(__name__)


class DeepStage:
    """Pipeline stage 4: deep LLM analysis for high-impact items.

    Runs asynchronously — does NOT block the main pipeline chain.
    Items with needs_deep=False are silently passed through.
    Failures are silently logged and discarded after one retry.
    """

    def __init__(self, deep_lane: DeepLane) -> None:
        self._dl = deep_lane
        self._pending: set[asyncio.Task] = set()

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        deep_items = [it for it in items if it.decision.needs_deep]
        if deep_items:
            logger.info("DEEP: spawning %d analysis tasks", len(deep_items))
            for item in deep_items:
                task = asyncio.create_task(self._analyze_one(item))
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)

        return items  # Always return immediately — DEEP is fire-and-forget

    async def _analyze_one(self, item: PipelineItem) -> None:
        """Run deep analysis on one item. Retry once on failure."""
        from storage.models import NewsItem
        from datetime import datetime

        news = NewsItem(
            id=item.id,
            title=item.title,
            source=item.source,
            url=item.url,
            content_snippet=item.snippet,
            tickers_found=item.tickers_found,
            macro_tags=item.macro_tags,
            priority_score=item.priority_score,
            published_at=datetime.now(),
        )
        try:
            await self._dl.process(news)
            logger.info("DEEP: analysis complete for id=%d", item.id)
        except Exception:
            try:
                await asyncio.sleep(2)
                await self._dl.process(news)
                logger.info("DEEP: analysis complete for id=%d (after retry)", item.id)
            except Exception:
                logger.exception("DEEP: analysis failed for id=%d", item.id)
