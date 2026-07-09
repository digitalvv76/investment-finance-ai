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
        if state == "ALERTED":
            closed = await self._maybe_close(event)
            return closed or await self._maybe_confirm(event)
        if state == "CONFIRMED":
            return await self._maybe_close(event)
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

    async def _maybe_confirm(self, event: dict):
        confirmed, note = await self._market_confirmed(event)
        if not confirmed:
            return None
        await self.dispatcher.dispatch_event(
            {"title": event.get("title", ""), "source_count": event.get("source_count", 0),
             "peak_impact": event.get("peak_impact", 0), "market_note": note},
            AlertLevel.CRITICAL, telegram_push_fn=self._tg(),
        )
        self.db.update_event_escalation(event["id"], escalation_state="CONFIRMED")
        logger.warning("Event #%s CONFIRMED by market (%s)", event["id"], note)
        return "ALERTED->CONFIRMED"

    async def _market_confirmed(self, event: dict) -> tuple[bool, str]:
        alerted_at = event.get("alerted_at")
        if not alerted_at:
            return (False, "")
        start = datetime.fromisoformat(alerted_at)
        mc = self._cfg["market_confirm"]
        snap = await self.market.since(start)
        sent = (event.get("dominant_sentiment") or "").upper()
        bearish = "BEAR" in sent  # BEARISH / CAUTIOUSLY_BEARISH
        spx, vix, oil = snap.get("spx_pct"), snap.get("vix_pct"), snap.get("brent_pct")
        # VIX up = risk-off, direction-agnostic to bull/bear
        if vix is not None and vix >= mc["vix_pct"]:
            return (True, f"VIX +{vix:.1f}%")
        if spx is not None:
            if bearish and spx <= -mc["spx_pct"]:
                return (True, f"SPX {spx:.2f}%")
            if not bearish and spx >= mc["spx_pct"]:
                return (True, f"SPX +{spx:.2f}%")
        if oil is not None and event.get("dominant_category") in mc["oil_relevant_categories"]:
            if bearish and oil >= mc["brent_pct"]:  # supply-risk → oil up
                return (True, f"Brent +{oil:.1f}%")
        return (False, "")

    async def _maybe_close(self, event: dict):
        last = event.get("last_updated")
        if not last:
            return None
        silence_h = self._cfg["close"]["silence_hours"]
        age = (datetime.now() - datetime.fromisoformat(str(last))).total_seconds() / 3600
        if age >= silence_h:
            await self.dispatcher.dispatch_event(
                {"title": f"事件收尾 — {event.get('title','')}",
                 "source_count": event.get("source_count", 0),
                 "peak_impact": event.get("peak_impact", 0),
                 "market_note": f"静默{int(age)}h，事件降温"},
                AlertLevel.NORMAL, telegram_push_fn=self._tg(),
            )
            prev = event.get("escalation_state", "")
            self.db.update_event_escalation(event["id"], escalation_state="CLOSED", is_active=0)
            logger.info("Event #%s CLOSED (silence %.1fh)", event["id"], age)
            return f"{prev}->CLOSED"
        return None

    async def sweep(self) -> None:
        try:
            window = self._cfg["alert_trigger"]["active_window_hours"]
            events = self.db.get_active_event_lines(active_window_hours=window)
        except Exception as e:
            logger.error("EventEscalator.sweep list failed: %s", e)
            return
        for ev in events:
            try:
                await self.evaluate(ev)
            except Exception as e:
                logger.error("EventEscalator evaluate failed for #%s: %s", ev.get("id"), e)
