import pytest
from unittest.mock import MagicMock, AsyncMock
from engine.event_escalator import EventEscalator
from engine.alert_dispatcher import AlertLevel


@pytest.fixture
def esc():
    db = MagicMock()
    cfg = MagicMock()
    cfg.load_event_escalation.return_value = {
        "alert_trigger": {"min_source_count": 3, "min_peak_impact": 70, "active_window_hours": 12},
        "market_confirm": {"spx_pct": 0.2, "vix_pct": 5.0, "brent_pct": 0.5,
                           "time_aligned": True, "direction_gated": True,
                           "oil_relevant_categories": ["geopolitical", "macro_data"]},
        "close": {"reversal_retrace_pct": 50, "silence_hours": 6},
        "cooldown_hours": 3, "max_pushes_per_event": 3,
    }
    dispatcher = MagicMock()
    dispatcher.dispatch_event = AsyncMock()
    market = MagicMock()
    return EventEscalator(db, dispatcher, market, cfg)


@pytest.mark.asyncio
async def test_alert_trigger_fires(esc):
    esc.db.get_event_members.return_value = [{"id": 1, "source": "A"}, {"id": 2, "source": "B"}, {"id": 3, "source": "C"}]
    esc.db.get_peak_impact_for_news_ids.return_value = (95.0, "geopolitical", "BEARISH")
    event = {"id": 10, "escalation_state": "NONE", "title": "US-Iran", "news_ids": "1,2,3", "source_count": 3}
    transition = await esc.evaluate(event)
    assert transition == "NONE->ALERTED"
    esc.dispatcher.dispatch_event.assert_awaited_once()
    args, kwargs = esc.dispatcher.dispatch_event.call_args
    assert args[1] == AlertLevel.IMPORTANT
    esc.db.update_event_escalation.assert_called()  # state persisted


@pytest.mark.asyncio
async def test_no_alert_below_threshold(esc):
    esc.db.get_event_members.return_value = [{"id": 1, "source": "A"}, {"id": 2, "source": "B"}]
    esc.db.get_peak_impact_for_news_ids.return_value = (95.0, "geopolitical", "BEARISH")
    event = {"id": 11, "escalation_state": "NONE", "title": "x", "news_ids": "1,2", "source_count": 2}
    assert await esc.evaluate(event) is None
    esc.dispatcher.dispatch_event.assert_not_awaited()


from datetime import datetime, timedelta


@pytest.mark.asyncio
async def test_market_confirm_bearish_down(esc):
    esc.market.since = AsyncMock(return_value={"spx_pct": -0.45, "vix_pct": 16.6, "brent_pct": 5.9})
    event = {"id": 10, "escalation_state": "ALERTED", "title": "US-Iran",
             "alerted_at": (datetime.now()-timedelta(hours=1)).isoformat(),
             "dominant_sentiment": "BEARISH", "dominant_category": "geopolitical"}
    transition = await esc.evaluate(event)
    assert transition == "ALERTED->CONFIRMED"
    args, kwargs = esc.dispatcher.dispatch_event.call_args
    assert args[1] == AlertLevel.CRITICAL


@pytest.mark.asyncio
async def test_market_confirm_wrong_direction_blocked(esc):
    # bearish event but market went UP → not confirmed
    esc.market.since = AsyncMock(return_value={"spx_pct": +0.8, "vix_pct": -3.0, "brent_pct": -1.0})
    event = {"id": 10, "escalation_state": "ALERTED", "title": "x",
             "alerted_at": (datetime.now()-timedelta(hours=1)).isoformat(),
             "dominant_sentiment": "BEARISH", "dominant_category": "geopolitical"}
    assert await esc.evaluate(event) is None


@pytest.mark.asyncio
async def test_close_on_silence(esc):
    old = (datetime.now()-timedelta(hours=7)).isoformat()
    event = {"id": 10, "escalation_state": "CONFIRMED", "title": "x",
             "last_updated": old, "source_count": 4, "peak_impact": 95}
    transition = await esc.evaluate(event)
    assert transition and transition.endswith("->CLOSED")
    args, kwargs = esc.dispatcher.dispatch_event.call_args
    assert args[1] == AlertLevel.NORMAL  # telegram only


@pytest.mark.asyncio
async def test_sweep_isolates_errors(esc):
    esc.db.get_active_event_lines.return_value = [
        {"id": 1, "escalation_state": "NONE", "news_ids": "1", "source_count": 1, "title": "a"},
        {"id": 2, "escalation_state": "NONE", "news_ids": "2", "source_count": 1, "title": "b"},
    ]
    async def boom(ev):
        raise RuntimeError("bad event")
    esc.evaluate = boom  # both raise
    await esc.sweep()  # must not raise
    assert True
