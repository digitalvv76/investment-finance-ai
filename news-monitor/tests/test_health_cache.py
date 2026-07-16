"""Tests for /health endpoint DB cache (routes._cached_db_ok).

These verify the three key behaviours introduced by the memory-cache fix:
1. ``refresh_cached_db_health`` sets the flag on success / clears it on failure.
2. ``health_check`` returns ``"ok"`` when the flag is True, ``"degraded"`` when False.
3. The globals are reset between tests so the order of test runs doesn't matter.
"""

from __future__ import annotations

import pytest
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
    """When the cache flag is True, status=ok + db=ok."""
    routes._cached_db_ok = True
    req = _make_request()

    resp = await routes.health_check(req)
    body = resp.body if hasattr(resp, "body") else resp.text
    import json
    data = json.loads(body)

    assert data["status"] == "ok"
    assert data["db"] == "ok"


@pytest.mark.asyncio
async def test_health_check_degraded_when_cache_false():
    """When the cache flag is False, status=degraded + db=error."""
    routes._cached_db_ok = False
    req = _make_request()

    resp = await routes.health_check(req)
    body = resp.body if hasattr(resp, "body") else resp.text
    import json
    data = json.loads(body)

    assert data["status"] == "degraded"
    assert data["db"] == "error"
