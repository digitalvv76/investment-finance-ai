"""EVALUATE stage: impact assessment + signal scoring + alert classification."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem, DispatchDecision, AlertLevel

if TYPE_CHECKING:
    from engine.impact_evaluator import ImpactEvaluator
    from engine.alert_dispatcher import AlertDispatcher
    from engine.actionability_review import ActionabilityReviewer

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
        actionability_reviewer: ActionabilityReviewer | None = None,
        db=None,
    ) -> None:
        self._impact = impact_evaluator
        self._dispatcher = dispatcher
        self._reviewer = actionability_reviewer
        self._db = db

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

        # Persist the detailed assessment for threshold calibration + audit
        # trail. Guard on item.id so we never write a dangling FK for an
        # unpersisted item (id=0).
        if impact is not None and self._db is not None and item.id:
            try:
                impact.news_id = item.id
                self._db.insert_assessment(impact)
            except Exception:
                logger.exception(
                    "EVALUATE: failed to persist assessment for #%d", item.id)

        # Step 2: Compute signal score (relevance + timeliness for gates)
        rel_mult = 1.0
        timeliness = None
        if item.tickers_found:
            try:
                from engine.relevance import signal_score as _signal_score
                sig = _signal_score(
                    news_tickers=item.tickers_found,
                    news_text=(item.title or "") + " " + (item.snippet or ""),
                    macro_tags=item.macro_tags or "",
                    strategic_matches=[],
                    is_breaking=item.is_breaking,
                    published_at=None,
                )
                rel_mult = sig.get("composite", 1.0)
                timeliness = sig.get("timeliness")
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
                timeliness=timeliness,
            )
        else:
            level, reason = self._dispatcher.classify(
                priority_score=item.priority_score,
                is_breaking=item.is_breaking,
                has_tickers=has_tickers,
                is_macro=is_macro,
            )

        # Step 3: Actionability Review — LLM second opinion for borderline cases.
        # Only runs when signal_score is in the grey zone (0.30–0.70) AND the
        # alert is above NORMAL.  ~5-10 calls/day, 10s timeout each.
        if (self._reviewer is not None
                and level != AlertLevel.NORMAL
                and self._reviewer.should_review(rel_mult)):
            try:
                review_result = await self._reviewer.review(
                    self._to_news_item(item), sig, impact_assessment=impact,
                )
                if review_result == "NOT_ACTIONABLE":
                    logger.info(
                        "EVALUATE: actionability review downgrades #%d %s → NORMAL — %s",
                        item.id, level.value, (item.title or "")[:60],
                    )
                    level = AlertLevel.NORMAL
                    reason = f"llm_review_not_actionable (was: {reason})"
            except Exception:
                logger.debug("EVALUATE: actionability review failed for #%d — "
                             "keeping original decision", item.id)

        # Build dispatch decision with all LLM-enriched fields
        impact_score = int(getattr(impact, "impact_score", 0) or 0)
        urgency = str(getattr(impact, "urgency", "") or "").upper()
        sentiment = str(getattr(impact, "sentiment", "") or "").upper()
        greed_index = int(getattr(impact, "greed_index", 50) or 50)
        flash_note = str(getattr(impact, "flash_note", "") or "")
        analyst_note = str(getattr(impact, "analyst_note", "") or "")
        key_points = str(getattr(impact, "key_points", "") or "")
        risk_flags = str(getattr(impact, "risk_flags", "") or "")
        event_category = str(getattr(impact, "event_category", "") or "")

        item.decision = DispatchDecision(
            alert_level=level,
            alert_reason=reason,
            impact_score=impact_score,
            signal_score=rel_mult,
            urgency=urgency,
            sentiment=sentiment,
            greed_index=greed_index,
            analyst_note=analyst_note,
            flash_note=flash_note,
            key_points=key_points,
            risk_flags=risk_flags,
            needs_deep=(
                impact_score >= 60
                or item.priority_score >= 0.7
                or urgency in ("FLASH", "ALERT")
            ),
            event_category=event_category,
        )

    @staticmethod
    def _to_news_item(item: PipelineItem):
        """Convert PipelineItem to NewsItem for ActionabilityReview compatibility."""
        from storage.models import NewsItem
        from datetime import datetime
        return NewsItem(
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
