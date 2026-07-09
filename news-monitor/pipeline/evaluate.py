"""EVALUATE stage: impact assessment + signal scoring + alert classification."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem, DispatchDecision, AlertLevel

if TYPE_CHECKING:
    from engine.impact_evaluator import ImpactEvaluator
    from engine.alert_dispatcher import AlertDispatcher

logger = logging.getLogger(__name__)

RETRY_DELAYS = [1, 2, 4]  # seconds between LLM retries


class EvaluateStage:
    """Pipeline stage 2: evaluate impact and classify alert level.

    For each item:
      1. Run ImpactEvaluator LLM (with retry + fallback)
      2. Classify alert level via AlertDispatcher
      3. Attach DispatchDecision to item
    """

    def __init__(
        self,
        impact_evaluator: ImpactEvaluator,
        dispatcher: AlertDispatcher,
    ) -> None:
        self._impact = impact_evaluator
        self._dispatcher = dispatcher

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        for item in items:
            try:
                await self._evaluate_one(item)
            except Exception:
                logger.exception("EVALUATE: item %d evaluation failed", item.id)

        logger.info("EVALUATE: processed %d items", len(items))
        return items

    async def _evaluate_one(self, item: PipelineItem) -> None:
        # Step 1: Impact assessment with retry → fallback
        impact = await self._run_with_retry(item)

        # Step 2: Classify alert level
        rel_mult = 1.0
        if item.tickers_found:
            try:
                from engine.relevance import signal_score
                _, rel_mult = signal_score(item.tickers_found.split(","))
            except Exception:
                pass

        has_tickers = bool(item.tickers_found)
        is_macro = bool(item.macro_tags)

        if impact is not None:
            level, reason = self._dispatcher.classify(
                priority_score=item.priority_score,
                strategic_matches=None,
                is_breaking=item.is_breaking,
                impact_assessment=impact,
                rel_mult=rel_mult,
                has_tickers=has_tickers,
                is_macro=is_macro,
            )
        else:
            level, reason = self._dispatcher.classify(
                priority_score=item.priority_score,
                is_breaking=item.is_breaking,
                has_tickers=has_tickers,
                is_macro=is_macro,
            )

        item.decision = DispatchDecision(
            alert_level=level,
            alert_reason=reason,
            impact_score=int(getattr(impact, "impact_score", 0) or 0),
            signal_score=0.0,
            analyst_note=str(getattr(impact, "analyst_note", "") or ""),
            needs_deep=(
                (getattr(impact, "impact_score", 0) or 0) >= 60
                or item.priority_score >= 0.7
            ),
            event_category=str(getattr(impact, "event_category", "") or ""),
        )

    async def _run_with_retry(self, item: PipelineItem):
        """Run impact evaluator with exponential backoff. Returns None on failure."""
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

        for attempt, delay in enumerate(RETRY_DELAYS):
            try:
                return await self._impact.evaluate(news)
            except Exception:
                if attempt < len(RETRY_DELAYS) - 1:
                    logger.warning("EVALUATE: LLM retry %d/%d in %ds for id=%d",
                                   attempt + 1, len(RETRY_DELAYS), delay, item.id)
                    await asyncio.sleep(delay)
                else:
                    logger.error("EVALUATE: LLM failed after %d retries for id=%d — "
                                 "falling back to legacy score", len(RETRY_DELAYS), item.id)
        return None
