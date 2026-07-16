"""Channel Protocol and built-in implementations (Pushover, Telegram, Web SSE)."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable, TYPE_CHECKING

from pipeline.item import PipelineItem, DispatchDecision, AlertLevel

if TYPE_CHECKING:
    from bot.telegram_bot import NewsBot

logger = logging.getLogger(__name__)


# ── Protocol ──────────────────────────────────────────────────────────

@runtime_checkable
class Channel(Protocol):
    """Pluggable dispatch channel. Each implementation handles one destination."""

    name: str

    async def send(
        self,
        item: PipelineItem,
        decision: DispatchDecision,
        disable_notification: bool = False,
    ) -> bool:
        """Send alert to this channel. Returns True on success."""
        ...


# ── Pushover Channel ──────────────────────────────────────────────────

class PushoverChannel:
    """Pushover push notification channel."""

    name = "pushover"

    def __init__(self, dispatcher) -> None:
        self._dispatcher = dispatcher

    async def send(
        self,
        item: PipelineItem,
        decision: DispatchDecision,
        disable_notification: bool = False,
    ) -> bool:
        if not self._dispatcher.pushover_available:
            return False

        raw = {
            "id": item.id, "title": item.title, "source": item.source,
            "url": item.url, "tickers_found": item.tickers_found,
            "macro_tags": item.macro_tags,
            "_analyst_note": decision.flash_note or decision.analyst_note,
            "_event_category": decision.event_category,
            "_impact_score": str(decision.impact_score),
            "_urgency": decision.urgency,
            "_sentiment": decision.sentiment,
            "_greed_index": str(decision.greed_index),
            "_confidence": "0",
        }

        try:
            if decision.alert_level == AlertLevel.CRITICAL:
                return await self._dispatcher._pushover_emergency(raw)
            elif decision.alert_level == AlertLevel.IMPORTANT:
                return await self._dispatcher._pushover_high(raw)
            return False
        except Exception:
            logger.exception("PushoverChannel: send failed for id=%d", item.id)
            return False


# ── Telegram Channel ──────────────────────────────────────────────────

class TelegramChannel:
    """Telegram Bot push notification channel."""

    name = "telegram"

    def __init__(self, bot: NewsBot) -> None:
        self._bot = bot

    async def send(
        self,
        item: PipelineItem,
        decision: DispatchDecision,
        disable_notification: bool = False,
    ) -> bool:
        if not self._bot._app:
            return False

        alert_dict = {
            "id": item.id,
            "title": item.title,
            "source": item.source,
            "url": item.url,
            "tickers_found": item.tickers_found,
            "macro_tags": item.macro_tags,
            "priority_score": item.priority_score,
            "_urgency": decision.urgency,
            "_sentiment": decision.sentiment,
            "_greed_index": decision.greed_index,
            "_key_points": decision.key_points,
            "_risk_flags": decision.risk_flags,
        }

        try:
            await self._bot.push_alert(
                alert_dict,
                # 📌 headline_signal: Path A uses LLM trading signal, Path B falls back to flash_note
                headline_signal=decision.headline_signal or decision.flash_note,
                # 📊 analyst_note: always the detailed analysis (NOT flash_note — that's for Pushover)
                analyst_note=decision.analyst_note,
                event_category=decision.event_category,
                impact_score=decision.impact_score,
                confidence=80,
                disable_notification=disable_notification,
                urgency=decision.urgency,
                sentiment=decision.sentiment,
                greed_index=decision.greed_index,
                key_points=decision.key_points,
                risk_flags=decision.risk_flags,
            )
            return True
        except Exception:
            logger.exception("TelegramChannel: send failed for id=%d", item.id)
            return False


# ── Web SSE Channel ───────────────────────────────────────────────────

class WebSSEChannel:
    """Web dashboard Server-Sent Events broadcast channel."""

    name = "web_sse"

    def __init__(self, sse_manager=None) -> None:
        self._sse = sse_manager

    async def send(
        self,
        item: PipelineItem,
        decision: DispatchDecision,
        disable_notification: bool = False,
    ) -> bool:
        if self._sse is None:
            return False
        try:
            await self._sse.broadcast({
                "id": item.id,
                "title": item.title,
                "source": item.source,
                "url": item.url,
                "tickers": item.tickers_found,
                "macro": item.macro_tags,
                "priority": item.priority_score,
                "level": decision.alert_level.value,
                "impact": decision.impact_score,
                "note": decision.analyst_note,
            })
            return True
        except Exception:
            logger.exception("WebSSEChannel: broadcast failed for id=%d", item.id)
            return False
