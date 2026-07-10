"""System liveness watchdog — resolves the "silence ambiguity".

A quiet push stream is ambiguous: either the market is genuinely calm
(silence is CORRECT) or the pipeline has stalled (silence is a BUG).
Operators cannot tell these apart by eye, so they only notice failures
when they remember to check — which is unreliable.

This watchdog measures UPSTREAM liveness (ingestion rate, error rate)
*independently* of push output, disambiguates the two cases, and
proactively alerts the operator only when silence is anomalous. It also
emits a daily "still alive" heartbeat so long quiet periods are known-good.

Architecture note: the watchdog runs as an INDEPENDENT asyncio task, NOT
inside the collection scheduler. If the scheduler loop hangs, a watchdog
living inside it would hang too and never fire — defeating the purpose.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from storage.models import HealthEvent

logger = logging.getLogger(__name__)


def _alerts_muted() -> bool:
    """Whether watchdog alerts should be logged-only instead of really sent.

    Watchdog alerts respect DRY_RUN_PUSH by default (shadow silence), BUT
    WATCHDOG_ALERTS_ENABLED=true forces real alerts even under DRY_RUN — this
    is how the shadow can still page the operator on a fault while its NEWS
    pushes stay silent for the V1-vs-V2 comparison.
    """
    dry = os.environ.get("DRY_RUN_PUSH", "").lower() in ("1", "true", "yes")
    forced = os.environ.get("WATCHDOG_ALERTS_ENABLED", "").lower() in ("1", "true", "yes")
    return dry and not forced


class HealthState(Enum):
    """The four states the watchdog can resolve silence into."""
    HEALTHY = "healthy"      # ingestion flowing, activity normal
    QUIET_OK = "quiet_ok"    # ingest alive but low / no push — genuinely calm
    STALLED = "stalled"      # ingestion dried up — pipeline broken → ALERT
    DEGRADED = "degraded"    # errors spiking / low success rate → ALERT


@dataclass
class HealthSignals:
    """Independent liveness measurements (all upstream of push decisions)."""
    ingest_1h: int              # news items captured in last hour
    ingest_floor: int           # minimum expected per hour (market-aware)
    hours_since_last_push: float  # for heartbeat context, not alerting
    error_events_1h: int        # health_events logged in last hour
    success_rate: float         # % assessments without errors
    assessments_1h: int         # LLM evaluations in last hour


@dataclass
class Verdict:
    state: HealthState
    reason: str                 # Chinese, operator-facing
    should_alert: bool          # fault requiring attention
    emergency: bool             # siren (P2) vs high-priority (P1)


def evaluate_health(
    s: HealthSignals,
    *,
    degraded_success_floor: float = 50.0,
    min_assessments_for_rate: int = 5,
) -> Verdict:
    """Pure disambiguation logic — the heart of the watchdog.

    Order matters: a hard stall (zero ingestion) is the most severe and
    most common real failure, checked first. Degradation (errors despite
    activity) second. Everything else is benign silence.
    """
    # 1. STALLED — ingestion dried up entirely == pipeline broken.
    #    This is the case that most often masquerades as "quiet market".
    if s.ingest_floor > 0 and s.ingest_1h <= 0:
        return Verdict(
            HealthState.STALLED,
            f"过去1小时零采集（正常应≥{s.ingest_floor}条/时），疑似采集管道故障或全部源失效",
            should_alert=True,
            emergency=True,
        )

    # 2. DEGRADED — enough activity to judge, but error rate spiking.
    if s.assessments_1h >= min_assessments_for_rate and s.success_rate < degraded_success_floor:
        return Verdict(
            HealthState.DEGRADED,
            f"处理成功率跌至 {s.success_rate}%（近1h {s.error_events_1h} 次错误），疑似 LLM 超时或规则异常",
            should_alert=True,
            emergency=False,
        )

    # 3. QUIET_OK — ingest alive but below floor. Pipeline works, market calm.
    #    THIS is the answer to the operator's confusion: silence is benign.
    if s.ingest_1h < s.ingest_floor:
        return Verdict(
            HealthState.QUIET_OK,
            f"采集量偏低（{s.ingest_1h} 条/时）但管道存活，判定为市场平静、非故障",
            should_alert=False,
            emergency=False,
        )

    # 4. HEALTHY — normal throughput.
    return Verdict(
        HealthState.HEALTHY,
        f"采集正常（{s.ingest_1h} 条/时），系统健康",
        should_alert=False,
        emergency=False,
    )


class Watchdog:
    """Runs the health check on a loop and drives alerts + daily heartbeat."""

    def __init__(self, db, alert_dispatcher, settings: Optional[dict] = None) -> None:
        self.db = db
        self.dispatcher = alert_dispatcher
        cfg = (settings or {}).get("watchdog", {}) if settings else {}
        self._interval = int(cfg.get("check_interval_seconds", 1800))       # 30 min
        self._floor = int(cfg.get("ingest_floor_per_hour", 3))
        self._weekend_multiplier = float(cfg.get("weekend_floor_multiplier", 0.34))
        self._consecutive_threshold = int(cfg.get("consecutive_bad_threshold", 2))
        self._cooldown = int(cfg.get("alert_cooldown_seconds", 3600))       # 1h
        self._heartbeat_hour = int(cfg.get("heartbeat_hour", 8))            # local hour
        self._startup_grace = int(cfg.get("startup_grace_seconds", 300))   # 5 min warmup
        self._running = False

        # State for debounce / cooldown / once-a-day heartbeat
        self._consecutive_bad = 0
        self._last_alert_monotonic = -1e18
        self._last_heartbeat_date: Optional[str] = None
        self.last_verdict: Optional[Verdict] = None
        self.last_signals: Optional[HealthSignals] = None
        self.last_check_at: Optional[datetime] = None

    # -- signal gathering ---------------------------------------------------

    def _ingest_floor(self) -> int:
        """Weekend/holiday markets are quiet — lower the floor to avoid false alarms."""
        try:
            from collector.market_calendar import is_weekend_mode  # optional
            if is_weekend_mode():
                return max(1, int(self._floor * self._weekend_multiplier))
        except Exception:
            pass
        # Fallback: plain weekend check
        if datetime.now().weekday() >= 5:
            return max(1, int(self._floor * self._weekend_multiplier))
        return self._floor

    def _hours_since_last_push(self) -> float:
        """Look up the most recent pushed item (status contains 'pushed')."""
        try:
            recent = self.db.get_recent_news(hours=72, limit=500)
            for row in recent:  # get_recent_news is DESC by captured_at
                if "pushed" in str(row.get("status", "")):
                    ts = row.get("captured_at")
                    if isinstance(ts, str):
                        ts = datetime.fromisoformat(ts)
                    if isinstance(ts, datetime):
                        return round((datetime.now() - ts).total_seconds() / 3600, 1)
            return 999.0  # nothing pushed in the window
        except Exception:
            return -1.0

    def gather_signals(self) -> HealthSignals:
        ingest = len(self.db.get_recent_news(hours=1, limit=2000))
        health = self.db.get_health_stats(hours=1)
        return HealthSignals(
            ingest_1h=ingest,
            ingest_floor=self._ingest_floor(),
            hours_since_last_push=self._hours_since_last_push(),
            error_events_1h=int(health.get("health_events_1h", 0)),
            success_rate=float(health.get("success_rate", 100.0)),
            assessments_1h=int(health.get("total_assessments_1h", 0)),
        )

    # -- one check cycle ----------------------------------------------------

    async def check(self, *, now_monotonic: Optional[float] = None) -> Verdict:
        signals = self.gather_signals()
        verdict = evaluate_health(signals)
        self.last_signals = signals
        self.last_verdict = verdict
        self.last_check_at = datetime.now()

        # Record every verdict for observability (feeds the /health page).
        try:
            self.db.insert_health_event(HealthEvent(
                event_type=f"watchdog_{verdict.state.value}",
                detail=verdict.reason,
            ))
        except Exception:
            logger.exception("Watchdog: failed to record health event")

        now = now_monotonic if now_monotonic is not None else asyncio.get_event_loop().time()
        if verdict.should_alert:
            self._consecutive_bad += 1
            debounced = self._consecutive_bad >= self._consecutive_threshold
            cooled = (now - self._last_alert_monotonic) >= self._cooldown
            if debounced and cooled:
                await self._fire_alert(verdict)
                self._last_alert_monotonic = now
            else:
                logger.info(
                    "Watchdog: %s held (consecutive=%d/%d, cooldown=%s)",
                    verdict.state.value, self._consecutive_bad,
                    self._consecutive_threshold, not cooled,
                )
        else:
            self._consecutive_bad = 0

        return verdict

    async def _fire_alert(self, verdict: Verdict) -> None:
        title = "🔴 新闻监控异常" if verdict.emergency else "🟠 新闻监控降级"
        message = f"{verdict.reason}\n\n请检查 ECS 容器 / 数据源 / LLM 服务。"
        if _alerts_muted():
            logger.info("DRY_RUN WOULD-ALERT | %s | %s", title, verdict.reason)
            return
        try:
            await self.dispatcher.send_system_alert(
                title, message, emergency=verdict.emergency,
            )
        except Exception:
            logger.exception("Watchdog: failed to send system alert")

    # -- daily heartbeat ----------------------------------------------------

    async def maybe_daily_heartbeat(self, now_dt: Optional[datetime] = None) -> bool:
        """Send one 'still alive, market quiet' report per day at the configured hour."""
        now_dt = now_dt or datetime.now()
        today = now_dt.strftime("%Y-%m-%d")
        if now_dt.hour < self._heartbeat_hour or self._last_heartbeat_date == today:
            return False

        self._last_heartbeat_date = today
        sig = self.last_signals or self.gather_signals()
        ingest_24h = len(self.db.get_recent_news(hours=24, limit=5000))
        quiet_note = "，市场平静无推送" if sig.hours_since_last_push >= 12 else ""
        title = "✅ 新闻监控日报 · 系统正常"
        message = (
            f"过去24h采集 {ingest_24h} 条，近1h {sig.ingest_1h} 条/时"
            f"{quiet_note}。管道存活，无需处理。"
        )
        if _alerts_muted():
            logger.info("DRY_RUN WOULD-HEARTBEAT | %s | %s", title, message)
            return True
        try:
            await self.dispatcher.send_system_alert(title, message, emergency=False, quiet=True)
        except Exception:
            logger.exception("Watchdog: failed to send heartbeat")
        return True

    # -- independent loop ---------------------------------------------------

    async def run_loop(self) -> None:
        self._running = True
        logger.info(
            "Watchdog started — interval=%ds, floor=%d/h, siren after %d consecutive, grace=%ds",
            self._interval, self._floor, self._consecutive_threshold, self._startup_grace,
        )
        # Startup grace: a fresh container has an empty DB (ingest=0). Wait for
        # collectors to warm up before the first judgment, else cold start
        # looks like a stall.
        if self._startup_grace > 0:
            await asyncio.sleep(self._startup_grace)
        while self._running:
            try:
                verdict = await self.check()
                await self.maybe_daily_heartbeat()
                logger.info("Watchdog: %s — %s", verdict.state.value, verdict.reason)
            except Exception:
                logger.exception("Watchdog: check cycle failed")
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        self._running = False
