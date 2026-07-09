# tests/test_dispatch_event.py
import pytest
from engine.alert_dispatcher import AlertDispatcher, AlertLevel


@pytest.fixture
def dispatcher():
    """AlertDispatcher with Pushover HARD-DISABLED so tests never send a
    real phone push, even when the local .env has PUSHOVER_* credentials.

    Belt-and-suspenders: force the creds empty AND stub the network methods.
    """
    d = AlertDispatcher()
    # 1) make pushover_available False regardless of environment
    d._pushover_token = ""
    d._pushover_users = []

    # 2) even if a code path tries anyway, stub the actual senders
    async def _no_pushover(item):
        raise AssertionError("Pushover must not be called in tests")

    d._pushover_high = _no_pushover        # type: ignore[assignment]
    d._pushover_emergency = _no_pushover   # type: ignore[assignment]
    return d


@pytest.mark.asyncio
async def test_dispatch_event_important_calls_telegram(dispatcher):
    d = dispatcher
    sent = []
    async def fake_push(item, disable_notification=True):
        sent.append((item["title"], disable_notification))
    # pushover creds forced empty by fixture → pushover skipped, telegram still fires
    res = await d.dispatch_event(
        {"title": "美伊冲突升级", "source_count": 4, "peak_impact": 95},
        AlertLevel.IMPORTANT, telegram_push_fn=fake_push,
    )
    assert "telegram_alert" in res.channels_used
    assert "pushover_high" not in res.channels_used  # pushover disabled in tests
    assert sent and sent[0][1] is False  # not silent


@pytest.mark.asyncio
async def test_dispatch_event_normal_is_silent(dispatcher):
    d = dispatcher
    sent = []
    async def fake_push(item, disable_notification=True):
        sent.append(disable_notification)
    res = await d.dispatch_event(
        {"title": "事件降级", "source_count": 4, "peak_impact": 60},
        AlertLevel.NORMAL, telegram_push_fn=fake_push,
    )
    assert sent == [True]  # silent


@pytest.mark.asyncio
async def test_dispatch_event_body_reaches_render(dispatcher):
    d = dispatcher
    captured = []
    async def fake_push(item, disable_notification=True):
        captured.append(item)
    await d.dispatch_event(
        {"title": "美伊冲突升级", "source_count": 4, "peak_impact": 95, "market_note": "VIX +17%"},
        AlertLevel.IMPORTANT, telegram_push_fn=fake_push,
    )
    assert captured, "telegram push should have been called"
    note = captured[0].get("_flash_note", "")
    assert "4" in note        # source count present
    assert "95" in note       # peak impact present
    assert "VIX +17%" in note # market note present
