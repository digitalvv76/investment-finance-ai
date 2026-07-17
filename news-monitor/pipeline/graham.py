"""GRAHAM stage: pre-dispatch value-investing safety net.

Inserted between Evaluate and Dispatch.  Every non-NORMAL item passes
through Graham's 5-question checklist.  Graham can only DOWNGRADE —
never upgrade.  He is the brake, not the accelerator.

Fails open: LLM timeout / error → item passes through unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem, AlertLevel

if TYPE_CHECKING:
    from engine.graham_reviewer import GrahamReviewer

logger = logging.getLogger(__name__)

# Downgrade matrix: (verdict, failures_count) → new AlertLevel
# - PUSH / 0-1 failures  → maintain original level
# - 2 failures           → NOTABLE (silent TG only)
# - 3+ failures          → NORMAL (no push)
# Graham can NEVER upgrade — his job is to filter noise, not amplify signal.

_DOWNGRADE_MAP: dict[str, AlertLevel] = {
    "PUSH":    None,       # maintain
    "SILENT":  AlertLevel.NOTABLE,
    "DROP":    AlertLevel.NORMAL,
}


class GrahamStage:
    """Pipeline stage: Benjamin Graham value-investing review.

    Runs after Evaluate (which sets alert_level) and before Dispatch
    (which sends to channels).  Graham reviews every non-NORMAL item
    and may downgrade the alert_level, but never upgrades.
    """

    def __init__(self, reviewer: GrahamReviewer) -> None:
        self._reviewer = reviewer

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        for item in items:
            decision = item.decision
            if decision.alert_level == AlertLevel.NORMAL:
                continue

            verdict = await self._reviewer.review(
                title=item.title or "",
                snippet=item.snippet or "",
                source=item.source or "",
                tickers=item.tickers_found or "",
                macro_tags=item.macro_tags or "",
            )

            if verdict is None:
                # Fail-open: LLM error → pass through
                continue

            n_fail = len(verdict.failures)

            # Two-failure threshold: 0-1 maintain, 2 → SILENT, 3+ → DROP
            if n_fail >= 3:
                new_level = AlertLevel.NORMAL
                action = "DROP"
            elif n_fail >= 2:
                new_level = AlertLevel.NOTABLE
                action = "SILENT"
            else:
                new_level = None
                action = "PASS"

            if new_level is not None and new_level != decision.alert_level:
                old = decision.alert_level.value
                logger.info(
                    "Graham: %s #%d %s→%s (failures=%s: %s) — %s",
                    action, item.id or 0,
                    old, new_level.value,
                    verdict.failures, verdict.note,
                    (item.title or "")[:80],
                )
                decision.alert_level = new_level
            elif n_fail > 0:
                # 1 failure: maintain but log
                logger.debug(
                    "Graham: PASS(warn) #%d (1 failure=%s: %s) — %s",
                    item.id or 0, verdict.failures, verdict.note,
                    (item.title or "")[:80],
                )

        return items
