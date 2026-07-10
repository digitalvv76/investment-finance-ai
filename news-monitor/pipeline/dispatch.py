"""DISPATCH stage: route alert decisions to all registered channels."""

from __future__ import annotations

import logging
import os
from collections import deque
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
        # Ring buffer of recent PUSHED decisions (NOTABLE/IMPORTANT/CRITICAL),
        # for the /health/decisions observability panel. NORMAL is skipped.
        self.recent_decisions: deque = deque(maxlen=50)

    def _record(self, item: PipelineItem, level: AlertLevel, silent: bool) -> None:
        d = item.decision
        self.recent_decisions.appendleft({
            "id": item.id,
            "title": (item.title or "")[:120],
            "level": level.value,
            "silent": silent,
            "ticker_hint": d.ticker_hint,
            "headline_signal": d.headline_signal,
            "reason": getattr(d, "alert_reason", ""),
        })

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        for item in items:
            decision = item.decision
            level = decision.alert_level

            # NORMAL = not worth a push. Skip ALL push channels (dashboard/DB
            # still have it). This is the "少而精" tightening: non-events no
            # longer flood Telegram. NOTABLE (watchlist safety net) → silent TG.
            if level == AlertLevel.NORMAL:
                continue
            silent = level == AlertLevel.NOTABLE
            self._record(item, level, silent)

            if _DRY_RUN:
                self._log_push(item, decision, silent)
                continue

            for channel in self._channels:
                try:
                    success = await channel.send(item, decision, disable_notification=silent)
                    if success:
                        logger.debug("DISPATCH: %d sent to %s", item.id, channel.name)
                except Exception:
                    logger.exception("DISPATCH: channel %s failed for id=%d",
                                     channel.name, item.id)

        logger.info("DISPATCH: processed %d items through %d channels%s",
                     len(items), len(self._channels), " [DRY_RUN]" if _DRY_RUN else "")
        return items  # Items always pass through

    @staticmethod
    def _log_push(item: PipelineItem, decision, silent: bool) -> None:
        """Log what would have been pushed in dry-run mode.

        NORMAL items never reach here (skipped upstream). NOTABLE logs as a
        silent would-push so the shadow comparison can see safety-net hits.
        """
        d = decision
        logger.info(
            "DRY_RUN WOULD-PUSH | level=%s%s intensity=%d | %s | tickers=%s | signal=%s | risk=%s",
            d.alert_level.value, " (silent)" if silent else "", d.intensity,
            (item.title or "")[:80],
            d.ticker_hint, d.headline_signal, d.risk_snapshot,
        )
