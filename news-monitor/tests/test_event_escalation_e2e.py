# tests/test_event_escalation_e2e.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta
from storage.database import Database
from storage.models import NewsItem, ImpactAssessment, EventLine
from engine.event_escalator import EventEscalator
from engine.alert_dispatcher import AlertLevel
from config.loader import ConfigLoader

@pytest.mark.asyncio
async def test_us_iran_rolling_event(tmp_path):
    db = Database(str(tmp_path / "e2e.db"))
    db.migrate_event_escalation()
    # 3 家来源、峰值 impact 95 的美伊事件簇
    for i, src in enumerate(["ZeroHedge", "Reuters", "Bloomberg"], start=1):
        db.insert_news(NewsItem(id=i, title="US strikes Iran", source=src, status="fast_pushed"))
        db.insert_assessment(ImpactAssessment(news_id=i, impact_score=95 if i == 1 else 60,
                                              event_category="geopolitical", sentiment="BEARISH"))
    # NOTE: store first_seen/last_updated as local-time ISO to match production
    # convention (cluster.py writes datetime.now(); escalator compares datetime.now()).
    # SQLite datetime('now') is UTC and would skew silence-age math off local tz.
    now_iso = datetime.now().isoformat()
    with db._get_conn() as conn:
        conn.execute("INSERT INTO event_lines (id, title, news_ids, source_count, "
                     "first_seen, last_updated, is_active, escalation_state) VALUES "
                     "(1,'US-Iran','1,2,3',3,?,?,1,'NONE')", (now_iso, now_iso))

    dispatcher = MagicMock(); dispatcher.dispatch_event = AsyncMock()
    market = MagicMock()
    esc = EventEscalator(db, dispatcher, market, ConfigLoader())

    # sweep 1: NONE→ALERTED (响铃)
    await esc.sweep()
    assert dispatcher.dispatch_event.await_args_list[-1].args[1] == AlertLevel.IMPORTANT

    # 模拟市场向下 → sweep 2: ALERTED→CONFIRMED (警笛)
    market.since = AsyncMock(return_value={"spx_pct": -0.5, "vix_pct": 17.0, "brent_pct": 6.0})
    await esc.sweep()
    assert dispatcher.dispatch_event.await_args_list[-1].args[1] == AlertLevel.CRITICAL

    # 把 last_updated 拨到 7h 前 → sweep 3: CONFIRMED→CLOSED (Telegram 收尾)
    with db._get_conn() as conn:
        conn.execute("UPDATE event_lines SET last_updated = ? WHERE id = 1",
                     ((datetime.now()-timedelta(hours=7)).isoformat(),))
    await esc.sweep()
    assert dispatcher.dispatch_event.await_args_list[-1].args[1] == AlertLevel.NORMAL

    # 恰好 3 次推送，不刷屏
    assert dispatcher.dispatch_event.await_count == 3
