"""Multi-channel alert dispatcher with Pushover emergency + Telegram fallback.

Alert levels (in order of severity):
    CRITICAL  — phone call (Twilio, P1) + Pushover emergency + Telegram triple
    IMPORTANT — Pushover high priority + Telegram silent
    NORMAL    — Telegram silent only

Classification considers both priority_score and strategic detector results.
"""

from __future__ import annotations

import asyncio
import logging
import os

import aiohttp
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from engine.strategic_detector import StrategicMatch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alert level
# ---------------------------------------------------------------------------


class AlertLevel(Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    level: AlertLevel
    channels_used: list[str]
    reason: str


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

CRITICAL_PRIORITY = 0.65      # PriorityScorer scores >= this → CRITICAL
IMPORTANT_PRIORITY = 0.50     # "" >= this → IMPORTANT
STRATEGIC_CRITICAL_CONF = 0.70  # Strategic match confidence >= this → CRITICAL
GOV_INTERVENTION_CRITICAL = True  # Any gov_intervention match → auto CRITICAL

# ---------------------------------------------------------------------------
# Pushover config
# ---------------------------------------------------------------------------

PUSHOVER_API = "https://api.pushover.net/1/messages.json"

# Pushover sound options ranked by intensity:
#   spacealarm, alien, siren, incoming, mechanical, heavy, persistent, ...
# See: https://pushover.net/api#sounds
PUSHOVER_SOUNDS = {
    "critical": "spacealarm",   # Emergency: sci-fi alarm, very jarring
    "important": "persistent",  # High priority: insistent beep
    "normal": "none",           # Silent (not used for Pushover)
}

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class AlertDispatcher:
    """Multi-channel alert dispatcher.

    Integration point: call ``dispatch()`` after FastLane processing,
    alongside the existing Telegram ``push_alert()``.  This module
    *augments* the existing Telegram flow — it does NOT replace it.

    Channels by level:

        CRITICAL
            - Pushover emergency (priority=2, repeats every 60s until ack)
            - Telegram triple-push (3 messages 500ms apart → force vibrate)
        IMPORTANT
            - Pushover high priority (priority=1)
            - Telegram standard push
        NORMAL
            - Telegram standard push only (existing behaviour)
    """

    def __init__(self) -> None:
        self._pushover_token = os.environ.get("PUSHOVER_APP_TOKEN", "")
        self._pushover_user = os.environ.get("PUSHOVER_USER_KEY", "")

    @property
    def pushover_available(self) -> bool:
        return bool(self._pushover_token and self._pushover_user)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(
        self,
        priority_score: float,
        strategic_matches: list | None = None,
        is_breaking: bool = False,
        impact_assessment=None,  # ImpactAssessment | None
        rel_mult: float = 1.0,   # relevance multiplier from portfolio/watchlist
    ) -> tuple[AlertLevel, str]:
        """Determine alert level from priority score + strategic signals + impact prediction.

        When impact_assessment is available (from ImpactEvaluator LLM), it takes
        precedence over the legacy priority_score-based classification.  The
        composite formula is: (impact_score × 0.7 + confidence × 0.3) × rel_mult.

        rel_mult ranges 0.3–1.5 based on portfolio/watchlist match (1.0 = neutral).

        Returns (AlertLevel, reason_string).
        """
        strategic_matches = strategic_matches or []

        # --- NEW: impact-prediction-first classification ---
        if impact_assessment is not None:
            impact = getattr(impact_assessment, 'impact_score', 0)
            conf = getattr(impact_assessment, 'confidence', 0)
            composite = round((impact * 0.7 + conf * 0.3) * rel_mult, 1)

            if composite >= CRITICAL_PRIORITY * 100:   # 70
                return AlertLevel.CRITICAL, (
                    f"high_impact: composite={composite} "
                    f"(impact={impact} conf={conf} rel={rel_mult:.1f})"
                )
            elif composite >= IMPORTANT_PRIORITY * 100:  # 50
                return AlertLevel.IMPORTANT, (
                    f"moderate_impact: composite={composite} "
                    f"(impact={impact} conf={conf} rel={rel_mult:.1f})"
                )
            else:
                return AlertLevel.NORMAL, (
                    f"low_impact: composite={composite} "
                    f"(impact={impact} conf={conf} rel={rel_mult:.1f})"
                )

        # --- LEGACY: score + strategic classification (fallback) ---
        gov_matches = [m for m in strategic_matches if m.category == "gov_intervention"]
        if gov_matches:
            top = max(m.confidence for m in gov_matches)
            return AlertLevel.CRITICAL, f"gov_intervention match (conf={top:.2f})"

        # --- auto-CRITICAL: high-confidence NVIDIA strategic event ---
        nvda_critical = [
            m for m in strategic_matches
            if m.category in ("nvda_investment", "nvda_endorsement", "nvda_competitive_threat")
            and m.confidence >= STRATEGIC_CRITICAL_CONF
        ]
        if nvda_critical:
            top = max(m.confidence for m in nvda_critical)
            return AlertLevel.CRITICAL, f"nvda strategic event (conf={top:.2f})"

        # --- score-based classification ---
        # NOTE: priority alone can trigger CRITICAL for systemic events (bailouts, wars, etc.)
        # but earnings drama / CEO commentary without strategic signal stays at IMPORTANT.
        if priority_score >= CRITICAL_PRIORITY:
            return AlertLevel.CRITICAL, f"priority_score={priority_score:.2f} >= {CRITICAL_PRIORITY}"
        elif priority_score >= IMPORTANT_PRIORITY:
            return AlertLevel.IMPORTANT, f"priority_score={priority_score:.2f} >= {IMPORTANT_PRIORITY}"
        else:
            return AlertLevel.NORMAL, "routine news"

    # ------------------------------------------------------------------
    # Channel dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        item: dict,
        priority_score: float,
        strategic_matches: list | None = None,
        telegram_push_fn=None,
    ) -> DispatchResult:
        """Classify and dispatch through appropriate channels.

        Args:
            item: News item dict (with id, title, source, url, tickers_found, ...).
            priority_score: Pre-computed priority score from PriorityScorer.
            strategic_matches: List of StrategicMatch objects, or None.
            telegram_push_fn: async callable(item, disable_notification: bool)
                              Called by *this* method for NORMAL/IMPORTANT Telegram sends.
                              If None, Telegram channel is skipped (testing).

        Returns:
            DispatchResult summarising what was done.
        """
        level, reason = self.classify(priority_score, strategic_matches)
        title = item.get("title", "")[:80]
        channels: list[str] = []

        if level == AlertLevel.CRITICAL:
            logger.warning("CRITICAL alert: %s | reason=%s", title, reason)

            # Pushover emergency (heartbeat until acknowledged)
            if self.pushover_available:
                await self._pushover_emergency(item)
                channels.append("pushover_emergency")

            # Telegram triple-push (force vibration on Android)
            if telegram_push_fn:
                await self._telegram_triple(item, telegram_push_fn)
                channels.append("telegram_triple")

        elif level == AlertLevel.IMPORTANT:
            logger.info("IMPORTANT alert: %s | reason=%s", title, reason)

            if self.pushover_available:
                await self._pushover_high(item)
                channels.append("pushover_high")

            if telegram_push_fn:
                await telegram_push_fn(item, disable_notification=False)
                channels.append("telegram_alert")

        else:  # NORMAL
            if telegram_push_fn:
                await telegram_push_fn(item, disable_notification=True)
                channels.append("telegram_silent")

        return DispatchResult(level=level, channels_used=channels, reason=reason)

    # ------------------------------------------------------------------
    # Pushover channel
    # ------------------------------------------------------------------

    async def _pushover(self, item: dict, priority: int, sound: str, **kwargs) -> bool:
        """Send a Pushover notification.

        Args:
            priority: -2=silent, 0=normal, 1=high, 2=emergency (repeating).
            sound: Sound name from Pushover's sound library.
        """
        title = item.get("title", "")[:250]
        source = item.get("source", "")
        url = item.get("url", "")
        tickers = item.get("tickers_found", "")
        macro = item.get("macro_tags", "")

        # Build message body
        parts = [f"Source: {source}"]
        if tickers:
            parts.append(f"Tickers: {tickers}")
        if macro:
            parts.append(f"Tags: {macro}")
        body = " | ".join(parts)

        payload = {
            "token": self._pushover_token,
            "user": self._pushover_user,
            "title": title,
            "message": body[:1024],
            "priority": priority,
            "sound": sound,
            **kwargs,
        }

        # Emergency priority requires retry + expire
        if priority == 2:
            payload.setdefault("retry", 30)    # retry every 30 seconds (more aggressive)
            payload.setdefault("expire", 3600)  # stop after 1 hour

        # URL for deep link
        if url:
            payload["url"] = url
            payload["url_title"] = "Read full article"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(PUSHOVER_API, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        logger.info("Pushover sent [priority=%d]: %s", priority, title[:60])
                        return True
                    else:
                        body_text = await resp.text()
                        logger.error("Pushover failed [%d]: %s", resp.status, body_text[:200])
                        return False
        except Exception as e:
            logger.error("Pushover error: %s", e)
            return False

    async def _pushover_emergency(self, item: dict) -> bool:
        """Emergency Pushover: repeats every 30s until user acknowledges."""
        return await self._pushover(
            item,
            priority=2,
            sound="spacealarm",
            retry=30,
            expire=3600,
        )

    async def _pushover_high(self, item: dict) -> bool:
        """High-priority Pushover: one-time with loud sound."""
        return await self._pushover(item, priority=1, sound="persistent")

    # ------------------------------------------------------------------
    # Telegram enhanced channel
    # ------------------------------------------------------------------

    @staticmethod
    async def _telegram_triple(item: dict, push_fn) -> None:
        """Send 3 messages 500ms apart → force vibration on Android.

        First message carries a Tasker-compatible tag for optional
        system-level automation on the phone side.
        """
        prefix = item.get("_alert_prefix", "🔴🔴🔴 CRITICAL")
        tasker_tag = item.get("_tasker_tag", "CRITICAL")

        # Message 1: tagged for Tasker monitoring
        await push_fn(
            {**item, "title": f"{prefix} [TAG:{tasker_tag}] {item.get('title', '')}"},
            disable_notification=False,
        )
        await asyncio.sleep(0.5)

        # Message 2: bare title
        await push_fn(
            {**item, "title": item.get("title", "")},
            disable_notification=False,
        )
        await asyncio.sleep(0.5)

        # Message 3: actionable
        source = item.get("source", "")
        url = item.get("url", "")
        await push_fn(
            {
                **item,
                "title": f"🔄 请查看详情 — 来源: {source}",
                "url": url,
            },
            disable_notification=False,
        )

    # ------------------------------------------------------------------
    # Register with an existing bot (convenience wrapper)
    # ------------------------------------------------------------------

    def wrap_telegram_push(self, bot) -> callable:
        """Return an async callable suitable for dispatching through the bot.

        Usage::

            dispatcher = AlertDispatcher()
            tg_push = dispatcher.wrap_telegram_push(bot)

            # Then pass tg_push as ``telegram_push_fn`` to dispatch().
        """

        async def _push(item: dict, disable_notification: bool = True) -> None:
            from bot.formatters import format_fast_alert, build_feedback_keyboard

            chat_id = bot._get_chat_id()
            if not chat_id:
                return

            text = format_fast_alert(item)
            keyboard = build_feedback_keyboard(item.get("id", 0))

            try:
                await bot._app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    disable_notification=disable_notification,
                )
            except Exception as e:
                logger.error("Telegram dispatch failed: %s", e)

        return _push
