"""MacroStage — pipeline stage for macro-economic news evaluation.

Inserted between IngestStage and ScreenStage.  Macro news is detected via
title whitelist, evaluated by MacroAgent (LLM), and routed directly to
Dispatch.  Non-macro items pass through untouched.
"""
from __future__ import annotations

import logging
from typing import List

from engine.macro_agent import MacroAgent
from pipeline.item import PipelineItem, DispatchDecision, AlertLevel

logger = logging.getLogger(__name__)

# String → AlertLevel mapping
_LEVEL_MAP = {
    "critical": AlertLevel.CRITICAL,
    "important": AlertLevel.IMPORTANT,
    "notable": AlertLevel.NOTABLE,
    "normal": AlertLevel.NORMAL,
}


class MacroStage:
    """Pipeline stage: detect + evaluate macro-economic indicator releases.

    Items matching a macro indicator are evaluated by LLM.  If a push is
    warranted, a DispatchDecision is attached and the item is marked
    ``_macro_routed = True`` so downstream stages (Screen, Evaluate) skip it.

    Non-macro items and items where the agent fails pass through unchanged.
    """

    def __init__(self, macro_agent: MacroAgent | None = None):
        self._agent = macro_agent or MacroAgent()

    async def process(self, items: List[PipelineItem]) -> List[PipelineItem]:
        """Process items: detect macro, evaluate, route or pass through."""
        for item in items:
            title = getattr(item, "title", "") or ""
            content = getattr(item, "snippet", "") or ""

            indicator = self._agent.detect(title, content)
            if indicator is None:
                continue  # not macro → pass through

            logger.info("MacroStage: %s detected — evaluating via LLM", indicator)
            assessment = await self._agent.evaluate(title, content)

            if assessment is None or not assessment.is_macro:
                continue  # evaluation failed or not a release → pass through

            # Attach decision
            item._macro_routed = True
            item.decision = DispatchDecision(
                alert_level=_LEVEL_MAP.get(assessment.alert_level, AlertLevel.NORMAL),
                impact_score=0,
                headline_signal=assessment.headline_signal,
                risk_snapshot=assessment.risk_snapshot,
                event_types=[],
                intensity=0,
            )
            logger.info(
                "MacroStage: %s tier=%s deviation=%s → %s",
                assessment.indicator, assessment.tier,
                assessment.deviation, assessment.alert_level,
            )

        return items
