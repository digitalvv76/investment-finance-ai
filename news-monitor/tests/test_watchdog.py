"""Watchdog tests — silence disambiguation + debounce/cooldown/heartbeat.

Per project rule (tests-never-send-real-pushes): a FAKE dispatcher is used
everywhere. No real AlertDispatcher is constructed, so nothing can reach
Pushover/Telegram.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from engine.watchdog import (
    HealthSignals,
    HealthState,
    Watchdog,
    evaluate_health,
)


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeDispatcher:
    def __init__(self):
        self.alerts = []

    async def send_system_alert(self, title, message, *, emergency=False, **kw):
        self.alerts.append({"title": title, "message": message, "emergency": emergency})
        return True


class FakeDB:
    """Minimal DB stub exposing only what the watchdog reads."""

    def __init__(self, ingest_1h=10, ingest_24h=200, health=None,
                 last_push_hours=1.0):
        self._ingest_1h = ingest_1h
        self._ingest_24h = ingest_24h
        self._health = health or {"total_assessments_1h": 20,
                                  "health_events_1h": 0, "success_rate": 100.0}
        self._last_push_hours = last_push_hours
        self.health_events = []

    def get_recent_news(self, hours=24, limit=500):
        if hours <= 1:
            n = self._ingest_1h
        else:
            n = self._ingest_24h
        # Build fake rows; first row carries a "pushed" status with a timestamp.
        rows = []
        push_ts = datetime.now() - timedelta(hours=self._last_push_hours)
        for i in range(n):
            rows.append({
                "id": i,
                "status": "deep_pushed" if i == 0 else "archived",
                "captured_at": push_ts.isoformat() if i == 0 else datetime.now().isoformat(),
            })
        return rows

    def get_health_stats(self, hours=1):
        return self._health

    def insert_health_event(self, e):
        self.health_events.append(e)
        return len(self.health_events)


def _signals(**kw):
    base = dict(ingest_1h=10, ingest_floor=3, hours_since_last_push=1.0,
                error_events_1h=0, success_rate=100.0, assessments_1h=20)
    base.update(kw)
    return HealthSignals(**base)


# --------------------------------------------------------------------------
# Pure logic — the four states
# --------------------------------------------------------------------------


class TestEvaluateHealth:
    def test_healthy_normal_throughput(self):
        v = evaluate_health(_signals(ingest_1h=10, ingest_floor=3))
        assert v.state is HealthState.HEALTHY
        assert v.should_alert is False

    def test_stalled_zero_ingest_fires_siren(self):
        v = evaluate_health(_signals(ingest_1h=0, ingest_floor=3))
        assert v.state is HealthState.STALLED
        assert v.should_alert is True
        assert v.emergency is True          # siren

    def test_quiet_ok_below_floor_but_alive_is_not_alert(self):
        # THE key case: silence that is benign, not a bug.
        v = evaluate_health(_signals(ingest_1h=1, ingest_floor=3))
        assert v.state is HealthState.QUIET_OK
        assert v.should_alert is False

    def test_degraded_low_success_rate_fires_non_emergency(self):
        v = evaluate_health(_signals(
            ingest_1h=10, assessments_1h=20, success_rate=30.0, error_events_1h=14))
        assert v.state is HealthState.DEGRADED
        assert v.should_alert is True
        assert v.emergency is False         # high priority, not siren

    def test_degraded_ignored_when_too_few_samples(self):
        # 2 assessments is not enough to trust the success rate.
        v = evaluate_health(_signals(ingest_1h=10, assessments_1h=2, success_rate=0.0))
        assert v.state is HealthState.HEALTHY
        assert v.should_alert is False

    def test_stall_takes_priority_over_degraded(self):
        v = evaluate_health(_signals(ingest_1h=0, ingest_floor=3,
                                     assessments_1h=20, success_rate=10.0))
        assert v.state is HealthState.STALLED


# --------------------------------------------------------------------------
# Watchdog orchestration — debounce, cooldown, heartbeat
# --------------------------------------------------------------------------


class TestWatchdogDebounce:
    @pytest.mark.asyncio
    async def test_single_bad_check_does_not_alert(self):
        db = FakeDB(ingest_1h=0)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {"consecutive_bad_threshold": 2}})
        await wd.check(now_monotonic=0.0)
        assert disp.alerts == []              # held: only 1 consecutive

    @pytest.mark.asyncio
    async def test_two_consecutive_bad_checks_fire(self):
        db = FakeDB(ingest_1h=0)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {"consecutive_bad_threshold": 2}})
        await wd.check(now_monotonic=0.0)
        await wd.check(now_monotonic=1.0)
        assert len(disp.alerts) == 1
        assert disp.alerts[0]["emergency"] is True

    @pytest.mark.asyncio
    async def test_recovery_resets_consecutive_counter(self):
        db = FakeDB(ingest_1h=0)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {"consecutive_bad_threshold": 2}})
        await wd.check(now_monotonic=0.0)     # bad (1)
        db._ingest_1h = 10                    # recovered
        await wd.check(now_monotonic=1.0)     # good → reset
        db._ingest_1h = 0                     # bad again (1, not 2)
        await wd.check(now_monotonic=2.0)
        assert disp.alerts == []              # never reached threshold

    @pytest.mark.asyncio
    async def test_cooldown_prevents_repeat_spam(self):
        db = FakeDB(ingest_1h=0)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {
            "consecutive_bad_threshold": 1, "alert_cooldown_seconds": 3600}})
        await wd.check(now_monotonic=0.0)     # fires
        await wd.check(now_monotonic=60.0)    # within cooldown → held
        assert len(disp.alerts) == 1
        await wd.check(now_monotonic=4000.0)  # past cooldown → fires again
        assert len(disp.alerts) == 2

    @pytest.mark.asyncio
    async def test_verdict_recorded_as_health_event(self):
        db = FakeDB(ingest_1h=0)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {})
        await wd.check(now_monotonic=0.0)
        assert any("watchdog_stalled" in e.event_type for e in db.health_events)


class TestWatchdogHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_fires_once_after_hour(self):
        db = FakeDB(ingest_1h=5, ingest_24h=300)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {"heartbeat_hour": 8}})
        await wd.check(now_monotonic=0.0)
        sent = await wd.maybe_daily_heartbeat(datetime(2026, 7, 11, 9, 0))
        assert sent is True
        assert len(disp.alerts) == 1
        assert "日报" in disp.alerts[0]["title"]

    @pytest.mark.asyncio
    async def test_heartbeat_not_before_configured_hour(self):
        db = FakeDB(ingest_1h=5)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {"heartbeat_hour": 8}})
        sent = await wd.maybe_daily_heartbeat(datetime(2026, 7, 11, 6, 0))
        assert sent is False
        assert disp.alerts == []

    @pytest.mark.asyncio
    async def test_heartbeat_only_once_per_day(self):
        db = FakeDB(ingest_1h=5)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {"heartbeat_hour": 8}})
        await wd.check(now_monotonic=0.0)
        await wd.maybe_daily_heartbeat(datetime(2026, 7, 11, 9, 0))
        second = await wd.maybe_daily_heartbeat(datetime(2026, 7, 11, 14, 0))
        assert second is False
        assert len(disp.alerts) == 1


class TestAlertMuting:
    """DRY_RUN silences watchdog alerts UNLESS WATCHDOG_ALERTS_ENABLED forces them.

    This is what lets the shadow page the operator on a fault while its news
    pushes stay silent for the comparison.
    """

    @pytest.mark.asyncio
    async def test_dry_run_mutes_alert(self, monkeypatch):
        monkeypatch.setenv("DRY_RUN_PUSH", "true")
        monkeypatch.delenv("WATCHDOG_ALERTS_ENABLED", raising=False)
        db = FakeDB(ingest_1h=0)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {"consecutive_bad_threshold": 1}})
        await wd.check(now_monotonic=0.0)
        assert disp.alerts == []           # muted → log only

    @pytest.mark.asyncio
    async def test_forced_flag_alerts_despite_dry_run(self, monkeypatch):
        monkeypatch.setenv("DRY_RUN_PUSH", "true")
        monkeypatch.setenv("WATCHDOG_ALERTS_ENABLED", "true")
        db = FakeDB(ingest_1h=0)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {"consecutive_bad_threshold": 1}})
        await wd.check(now_monotonic=0.0)
        assert len(disp.alerts) == 1       # forced → real send

    @pytest.mark.asyncio
    async def test_no_dry_run_alerts_normally(self, monkeypatch):
        monkeypatch.delenv("DRY_RUN_PUSH", raising=False)
        db = FakeDB(ingest_1h=0)
        disp = FakeDispatcher()
        wd = Watchdog(db, disp, {"watchdog": {"consecutive_bad_threshold": 1}})
        await wd.check(now_monotonic=0.0)
        assert len(disp.alerts) == 1       # production default → real send
