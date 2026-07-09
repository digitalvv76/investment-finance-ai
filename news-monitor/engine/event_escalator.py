"""Event-level escalation state machine (NONE→ALERTED→CONFIRMED→CLOSED)."""
from __future__ import annotations
import logging
from datetime import datetime

from engine.alert_dispatcher import AlertLevel

logger = logging.getLogger(__name__)


class EventEscalator:
    def __init__(self, db, dispatcher, market, config_loader, telegram_push_provider=None):
        self.db = db
        self.dispatcher = dispatcher
        self.market = market
        self._cfg = config_loader.load_event_escalation()
        self._tg_provider = telegram_push_provider  # zero-arg callable -> telegram_push_fn|None

    def _tg(self):
        return self._tg_provider() if self._tg_provider else None

    def compute_momentum(self, event: dict) -> dict:
        members = self.db.get_event_members(event["id"])
        source_count = len({m.get("source", "") for m in members if m.get("source")})
        ids = [m["id"] for m in members if m.get("id")]
        peak, category, sentiment = self.db.get_peak_impact_for_news_ids(ids)
        return {"source_count": max(source_count, event.get("source_count", 0)),
                "peak_impact": peak, "category": category, "sentiment": sentiment}

    async def evaluate(self, event: dict):
        state = event.get("escalation_state", "NONE")
        if state == "NONE":
            return await self._maybe_alert(event)
        # CONFIRMED / CLOSE handled in Task 7 / Task 8
        return None

    async def _maybe_alert(self, event: dict):
        m = self.compute_momentum(event)
        t = self._cfg["alert_trigger"]
        if m["source_count"] >= t["min_source_count"] and m["peak_impact"] >= t["min_peak_impact"]:
            await self.dispatcher.dispatch_event(
                {"title": event.get("title", ""), "source_count": m["source_count"],
                 "peak_impact": m["peak_impact"]},
                AlertLevel.IMPORTANT, telegram_push_fn=self._tg(),
            )
            self.db.update_event_escalation(
                event["id"], escalation_state="ALERTED",
                peak_impact=m["peak_impact"], dominant_category=m["category"],
                dominant_sentiment=m["sentiment"], alerted_at=datetime.now().isoformat(),
            )
            logger.warning("Event #%s ALERTED (src=%d peak=%d)",
                           event["id"], m["source_count"], int(m["peak_impact"]))
            return "NONE->ALERTED"
        return None
