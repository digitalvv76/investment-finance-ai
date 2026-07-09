"""DISPATCH stage: route alert decisions to all registered channels."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem, AlertLevel

if TYPE_CHECKING:
    from pipeline.channel import Channel

logger = logging.getLogger(__name__)


class DispatchStage:
    """Pipeline stage 3: dispatch alerts through all registered channels.

    Each channel receives every item and decides internally whether to
    act based on the alert level. Channel failures are isolated — one
    bad channel never blocks another.
    """

    def __init__(self, channels: list[Channel]) -> None:
        self._channels = channels

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        for item in items:
            decision = item.decision
            disable = decision.alert_level == AlertLevel.NORMAL

            for channel in self._channels:
                try:
                    success = await channel.send(item, decision, disable_notification=disable)
                    if success:
                        logger.debug("DISPATCH: %d sent to %s", item.id, channel.name)
                except Exception:
                    logger.exception("DISPATCH: channel %s failed for id=%d",
                                     channel.name, item.id)

        logger.info("DISPATCH: processed %d items through %d channels",
                     len(items), len(self._channels))
        return items  # Items always pass through
