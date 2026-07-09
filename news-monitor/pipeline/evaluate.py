"""EVALUATE stage: event-driven assessment + signal scoring + alert classification."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem, DispatchDecision, AlertLevel

if TYPE_CHECKING:
    from engine.impact_evaluator import ImpactEvaluator
    from engine.event_driven_evaluator import EventDrivenEvaluator
    from engine.alert_dispatcher import AlertDispatcher
    from engine.actionability_review import ActionabilityReviewer

logger = logging.getLogger(__name__)

RETRY_DELAYS = [1, 2, 4]  # seconds between LLM retries


class EvaluateStage:
    """Pipeline stage 2: evaluate impact and classify alert level.

    Two evaluation paths (tried in order):
      A) EventDrivenEvaluator — structured catalyst detection (primary)
      B) ImpactEvaluator LLM — legacy free-form scoring (fallback)

    Path A produces is_event + intensity + headline_signal etc.
    Path B falls back only when A is not configured or its LLM is unavailable.
    """

    def __init__(
        self,
        impact_evaluator: ImpactEvaluator,
        dispatcher: AlertDispatcher,
        actionability_reviewer: ActionabilityReviewer | None = None,
        db=None,
        event_evaluator: EventDrivenEvaluator | None = None,
    ) -> None:
        self._impact = impact_evaluator
        self._event_eval = event_evaluator
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
        # ── Path A: Event-driven evaluation (primary) ──
        event_assessment = None
        if self._event_eval is not None:
            try:
                event_assessment = await self._event_eval.evaluate(
                    self._to_news_item(item)
                )
            except Exception:
                logger.exception("EVALUATE: event-driven eval failed for #%d", item.id)

        if event_assessment is not None and event_assessment.should_push:
            # ── Event-driven path: direct push decision from structured output ──
            self._apply_event_assessment(item, event_assessment)
            return

        # ── Path B: Legacy impact evaluation (fallback) ──
        impact = await self._run_with_retry(item)

        # Persist the detailed assessment for threshold calibration + audit
        if impact is not None and self._db is not None and item.id:
            try:
                impact.news_id = item.id
                self._db.insert_assessment(impact)
            except Exception:
                logger.exception(
                    "EVALUATE: failed to persist assessment for #%d", item.id)

        # If event-driven ran but said "no push", use its filter reason
        if event_assessment is not None:
            item.decision = DispatchDecision(
                alert_level=AlertLevel.NORMAL,
                alert_reason=event_assessment.filter_reason or "no catalyst triggered",
                filter_reason=event_assessment.filter_reason,
                headline_signal=event_assessment.headline_signal,
                risk_snapshot=event_assessment.risk_snapshot,
                event_types=event_assessment.event_types,
                intensity=event_assessment.intensity,
                sector_tags=event_assessment.sector_tags,
                ticker_hint=event_assessment.ticker_hint,
            )
            return

        # Compute signal score (relevance + timeliness for gates)
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

        # Actionability Review — LLM second opinion for borderline cases.
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

    # ------------------------------------------------------------------
    # Event-driven evaluation helpers
    # ------------------------------------------------------------------

    def _apply_event_assessment(self, item: PipelineItem, ea) -> None:
        """Apply event-driven assessment directly to item.decision."""
        from engine.event_driven_evaluator import EventAssessment

        # Map intensity to alert level
        if ea.intensity >= 5:
            level = AlertLevel.CRITICAL
        elif ea.intensity >= 4:
            level = AlertLevel.IMPORTANT
        else:
            level = AlertLevel.IMPORTANT  # intensity 3, per user spec

        reason = f"event_driven: catalyst_types={ea.event_types} intensity={ea.intensity}"

        item.decision = DispatchDecision(
            alert_level=level,
            alert_reason=reason,
            event_types=ea.event_types,
            intensity=ea.intensity,
            sector_tags=ea.sector_tags,
            headline_signal=ea.headline_signal,
            ticker_hint=ea.ticker_hint,
            risk_snapshot=ea.risk_snapshot,
            needs_deep=(ea.intensity >= 4),
            urgency="FLASH" if ea.intensity >= 5 else "ALERT",
            flash_note=ea.headline_signal,      # reuse for push formatter
            analyst_note=ea.risk_snapshot,       # reuse for risk context
            signal_score=ea.intensity / 5.0,     # normalize for downstream gates
            impact_score=ea.intensity * 20,      # 1-5 → 20-100 for backward compat
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
