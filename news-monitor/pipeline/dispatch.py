"""DISPATCH stage: route alert decisions to all registered channels."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem, AlertLevel

if TYPE_CHECKING:
    from pipeline.channel import Channel

logger = logging.getLogger(__name__)

_DRY_RUN = os.environ.get("DRY_RUN_PUSH", "").lower() in ("1", "true", "yes")


class DispatchStage:
    """Pipeline stage 3: dispatch alerts through all registered channels.

    Each channel receives every item and decides internally whether to
    act based on the alert level. Channel failures are isolated — one
    bad channel never blocks another.

    DRY_RUN_PUSH=true → log push decisions, never send to real channels.
    """

    def __init__(self, channels: list[Channel]) -> None:
        self._channels = channels

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        for item in items:
            decision = item.decision
            disable = decision.alert_level == AlertLevel.NORMAL

            if _DRY_RUN:
                self._log_push(item, decision, disable)
                continue

            for channel in self._channels:
                try:
                    success = await channel.send(item, decision, disable_notification=disable)
                    if success:
                        logger.debug("DISPATCH: %d sent to %s", item.id, channel.name)
                except Exception:
                    logger.exception("DISPATCH: channel %s failed for id=%d",
                                     channel.name, item.id)

        logger.info("DISPATCH: processed %d items through %d channels%s",
                     len(items), len(self._channels), " [DRY_RUN]" if _DRY_RUN else "")
        return items  # Items always pass through

    @staticmethod
    def _log_push(item: PipelineItem, decision, disable: bool) -> None:
        """Log what would have been pushed in dry-run mode."""
        if disable:
            return
        d = decision
        logger.info(
            "DRY_RUN WOULD-PUSH | level=%s intensity=%d | %s | tickers=%s | signal=%s | risk=%s",
            d.alert_level.value, d.intensity,
            (item.title or "")[:80],
            d.ticker_hint, d.headline_signal, d.risk_snapshot,
        )
