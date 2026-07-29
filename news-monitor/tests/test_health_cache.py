"""Tests for /health endpoint DB cache (routes._cached_db_ok) + freshness gate.

These verify the key behaviours introduced by the memory-cache fix:
1. ``refresh_cached_db_health`` sets the flag on success / clears it on failure.
2. ``health_check`` returns ``"ok"`` when the flag is True, ``"degraded"`` when False.
3. The globals are reset between tests so the order of test runs doesn't matter.

And the freshness gate (2026-07-29):
4. Stale watchdog (>2× interval since last check) → ``state: stale, ok: False``
5. Fresh watchdog → normal verdict
6. Edge case: exactly at 2× threshold is still ok
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest import mock

from web import routes


# ————————————————————————————————————————————————
# Helpers — reset module global before each test
# ————————————————————————————————————————————————

@pytest.fixture(autouse=True)
def _reset_cache():
    routes._cached_db_ok = True


# ————————————————————————————————————————————————
# refresh_cached_db_health
# ————————————————————————————————————————————————

@pytest.mark.asyncio
async def test_refresh_db_ok_stays_true():
    """Healthy DB → flag stays True."""
    db = mock.Mock()
    db.get_db_stats.return_value = {"news_count": 42}

    await routes.refresh_cached_db_health(db)
    assert routes._cached_db_ok is True


@pytest.mark.asyncio
async def test_refresh_db_error_sets_false():
    """Broken DB → flag becomes False."""
    db = mock.Mock()
    db.get_db_stats.side_effect = RuntimeError("disk full")

    await routes.refresh_cached_db_health(db)
    assert routes._cached_db_ok is False


@pytest.mark.asyncio
async def test_refresh_then_error_then_ok_toggles_correctly():
    """Flag toggles with DB health, not sticky."""
    db = mock.Mock()

    db.get_db_stats.side_effect = None
    db.get_db_stats.return_value = {"news_count": 1}
    await routes.refresh_cached_db_health(db)
    assert routes._cached_db_ok is True

    db.get_db_stats.side_effect = RuntimeError("locked")
    await routes.refresh_cached_db_health(db)
    assert routes._cached_db_ok is False

    db.get_db_stats.side_effect = None
    db.get_db_stats.return_value = {"news_count": 1}
    await routes.refresh_cached_db_health(db)
    assert routes._cached_db_ok is True


# ————————————————————————————————————————————————
# health_check response
# ————————————————————————————————————————————————

def _make_request():
    """Minimal aiohttp Request stub with the three app keys health_check reads."""
    app = {
        "db": mock.Mock(),
        "sse_manager": mock.Mock(client_count=0),
        "watchdog": None,  # no watchdog → uses the "unavailable" snapshot path
    }
    req = mock.Mock(spec=["app"])
    req.app = app
    return req


@pytest.mark.asyncio
async def test_health_check_ok_when_cache_true():
    """When the cache flag is True, status=ok + db=ok + HTTP 200."""
    routes._cached_db_ok = True
    req = _make_request()

    resp = await routes.health_check(req)
    body = resp.body if hasattr(resp, "body") else resp.text
    import json
    data = json.loads(body)

    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert resp.status == 200


@pytest.mark.asyncio
async def test_health_check_degraded_when_cache_false():
    """When the cache flag is False, status=degraded + db=error + HTTP 503."""
    routes._cached_db_ok = False
    req = _make_request()

    resp = await routes.health_check(req)
    body = resp.body if hasattr(resp, "body") else resp.text
    import json
    data = json.loads(body)

    assert data["status"] == "degraded"
    assert data["db"] == "error"
    assert resp.status == 503


# ————————————————————————————————————————————————
# Freshness gate — watchdog staleness detection
# ————————————————————————————————————————————————

def _make_watchdog_mock(last_check_at, interval=1800, state='healthy'):
    """Build a minimal Watchdog mock for snapshot testing."""
    wd = mock.Mock()
    wd.last_verdict = mock.Mock()
    wd.last_verdict.state.value = state
    wd.last_signals = mock.Mock()
    wd.last_signals.ingest_1h = 100
    wd.last_signals.ingest_floor = 3
    wd.last_signals.hours_since_last_push = 0.5
    wd.last_signals.error_events_1h = 0
    wd.last_signals.success_rate = 100.0
    wd.last_signals.assessments_1h = 10
    wd.last_check_at = last_check_at
    wd._interval = interval
    return wd


def test_fresh_watchdog_returns_healthy():
    """Watchdog checked just now → healthy/ok=True."""
    wd = _make_watchdog_mock(last_check_at=datetime.now())
    snap = routes._watchdog_snapshot(wd)
    assert snap["state"] == "healthy"
    assert snap["ok"] is True


def test_stale_watchdog_returns_stale():
    """Watchdog last checked 2 hours ago (>2× 30min interval) → stale/ok=False."""
    wd = _make_watchdog_mock(
        last_check_at=datetime.now() - timedelta(seconds=7200),
        interval=1800,  # max_age = 3600s
    )
    snap = routes._watchdog_snapshot(wd)
    assert snap["state"] == "stale"
    assert snap["ok"] is False
    assert snap["emergency"] is True
    assert "3600" in snap["reason"]  # max_age mentioned
    assert "7200" in snap["reason"]  # actual age mentioned


def test_edge_at_threshold_stays_healthy():
    """Watchdog at exactly 2× interval → still ok (not over threshold)."""
    wd = _make_watchdog_mock(
        last_check_at=datetime.now() - timedelta(seconds=1800),
        interval=1800,  # max_age = 3600s, age = 1800s → not stale
    )
    snap = routes._watchdog_snapshot(wd)
    assert snap["state"] == "healthy"
    assert snap["ok"] is True


def test_no_watchdog_returns_unavailable():
    """wd=None → unavailable/unknown."""
    snap = routes._watchdog_snapshot(None)
    assert snap["available"] is False
    assert snap["state"] == "unknown"


def test_stale_but_ingest_was_healthy_still_flags_stale():
    """Even if the last cached verdict was healthy, staleness overrides it.

    This is the exact scenario from 2026-07-29: the watchdog cached a healthy
    verdict at 23:19 UTC, then the event loop blocked. The health endpoint
    kept returning that stale "healthy" for 4+ hours. After the fix, a stale
    last_check_at always produces stale/degraded regardless of cached verdict.
    """
    wd = _make_watchdog_mock(
        last_check_at=datetime.now() - timedelta(seconds=7200),
        interval=1800,
        state='healthy',  # last verdict was healthy — but it's stale!
    )
    snap = routes._watchdog_snapshot(wd)
    assert snap["state"] == "stale"
    assert snap["ok"] is False
