# tests/test_dispatch_event.py
import pytest
from engine.alert_dispatcher import AlertDispatcher, AlertLevel

@pytest.mark.asyncio
async def test_dispatch_event_important_calls_telegram(monkeypatch):
    d = AlertDispatcher()
    sent = []
    async def fake_push(item, disable_notification=True):
        sent.append((item["title"], disable_notification))
    # no pushover creds → pushover skipped, telegram still fires
    res = await d.dispatch_event(
        {"title": "美伊冲突升级", "source_count": 4, "peak_impact": 95},
        AlertLevel.IMPORTANT, telegram_push_fn=fake_push,
    )
    assert "telegram_alert" in res.channels_used
    assert sent and sent[0][1] is False  # not silent

@pytest.mark.asyncio
async def test_dispatch_event_normal_is_silent(monkeypatch):
    d = AlertDispatcher()
    sent = []
    async def fake_push(item, disable_notification=True):
        sent.append(disable_notification)
    res = await d.dispatch_event(
        {"title": "事件降级", "source_count": 4, "peak_impact": 60},
        AlertLevel.NORMAL, telegram_push_fn=fake_push,
    )
    assert sent == [True]  # silent
