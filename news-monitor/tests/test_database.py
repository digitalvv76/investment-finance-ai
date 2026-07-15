"""Tests for database module."""
import pytest
import os
import tempfile
from datetime import datetime
from storage.database import Database
from storage.models import NewsItem, FeedbackRecord, FundFlowRecord


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    d = Database(path)
    d.init_db()
    yield d
    os.unlink(path)


def test_init_db_creates_tables(db):
    db.init_db()  # idempotent
    # If no exception, tables exist


def test_insert_and_retrieve_news(db):
    item = NewsItem(
        title="Test breaking news",
        url="https://example.com/test1",
        source="Bloomberg",
        content_snippet="Test content",
        tickers_found="NVDA",
        is_breaking=True,
        priority_score=0.85,
        status="fast_pushed"
    )
    news_id = db.insert_news(item)
    assert news_id > 0

    result = db.get_news_by_id(news_id)
    assert result["title"] == "Test breaking news"
    assert result["source"] == "Bloomberg"
    assert result["tickers_found"] == "NVDA"
    assert result["priority_score"] == 0.85


def test_insert_duplicate_url_ignored(db):
    item1 = NewsItem(title="First", url="https://example.com/dup", source="CNBC")
    item2 = NewsItem(title="Second", url="https://example.com/dup", source="Reuters")

    id1 = db.insert_news(item1)
    id2 = db.insert_news(item2)

    assert id1 > 0
    assert id2 == 0  # IGNORE due to unique constraint


def test_update_news_status(db):
    item = NewsItem(title="Test", url="https://example.com/upd", source="Test")
    news_id = db.insert_news(item)

    db.update_news_status(news_id, "deep_pushed", sentiment="bullish", sentiment_score=0.75)

    result = db.get_news_by_id(news_id)
    assert result["status"] == "deep_pushed"
    assert result["sentiment"] == "bullish"
    assert float(result["sentiment_score"]) == 0.75


def test_feedback_crud(db):
    item = NewsItem(title="Test", url="https://example.com/fb", source="Test")
    news_id = db.insert_news(item)

    fb = FeedbackRecord(news_id=news_id, reaction="thumbs_up")
    fb_id = db.insert_feedback(fb)
    assert fb_id > 0

    feedbacks = db.get_feedback_for_news(news_id)
    assert len(feedbacks) == 1
    assert feedbacks[0]["reaction"] == "thumbs_up"


def test_preferences_crud(db):
    db.set_preference("source_weight:bloomberg", "0.85")
    val = db.get_preference("source_weight:bloomberg")
    assert val == "0.85"

    db.set_preference("source_weight:bloomberg", "0.90")
    val = db.get_preference("source_weight:bloomberg")
    assert val == "0.90"


def test_get_recent_news(db):
    items = [
        NewsItem(title=f"News {i}", url=f"https://example.com/{i}", source="Test")
        for i in range(5)
    ]
    for item in items:
        db.insert_news(item)

    recent = db.get_recent_news(hours=24)
    assert len(recent) == 5


def test_health_stats_excludes_watchdog_records(db):
    """Watchdog's own observability records must NOT count as errors —
    else the watchdog pollutes its own success_rate → false 'degraded'."""
    from storage.models import HealthEvent
    # Two real assessments would exist; simulate only health_events here.
    db.insert_health_event(HealthEvent(event_type="watchdog_healthy", detail="ok"))
    db.insert_health_event(HealthEvent(event_type="watchdog_stalled", detail="x"))
    db.insert_health_event(HealthEvent(event_type="llm_timeout", detail="real error"))
    # Wide window so a few-hours local/UTC offset can't exclude just-inserted rows;
    # the point under test is the watchdog_ exclusion, not the time window.
    stats = db.get_health_stats(hours=24)
    # Only the real llm_timeout counts as an error, not the 2 watchdog_ records.
    assert stats["health_events_1h"] == 1


def test_get_recent_news_window_matches_local_captured_at(db):
    """captured_at is stored in local time; the recent-news window must compare
    in local time AND parse the stored separator ('T' or space). Regression for
    the watchdog false-STALLED bug: a UTC window under-counted on non-UTC hosts,
    and an isoformat 'T' separator broke string comparison against space-format
    datetime(). Uses real datetime objects (the actual insert path).
    """
    from datetime import timedelta
    now = datetime.now()
    recent = NewsItem(title="recent", url="https://ex/recent", source="t",
                      captured_at=now)
    old = NewsItem(title="old", url="https://ex/old", source="t",
                   captured_at=now - timedelta(hours=2))
    db.insert_news(recent)
    db.insert_news(old)

    titles = {r["title"] for r in db.get_recent_news(hours=1)}
    assert "recent" in titles          # within the 1h window
    assert "old" not in titles         # 2h-old must be excluded


# ------------------------------------------------------------------
# Fund flow table
# ------------------------------------------------------------------

def test_fund_flow_table_exists(db):
    """init_db() creates the fund_flow table."""
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='fund_flow'"
        ).fetchone()
    assert row is not None


def test_upsert_fund_flow_insert(db):
    record = FundFlowRecord(
        ticker="AAPL", date="2026-07-14",
        main_net=5000000, super_big_net=3000000, big_net=2000000,
        mid_net=-1000000, small_net=-4000000, main_pct=8.5,
        source="push2his", fetched_at=1752537600.0,
    )
    rid = db.upsert_fund_flow(record)
    assert rid > 0
    assert record.id == rid


def test_upsert_fund_flow_replace(db):
    """Same ticker+date upserts → replace, not duplicate."""
    r1 = FundFlowRecord(
        ticker="AAPL", date="2026-07-14",
        main_net=5000000, super_big_net=3000000,
        source="push2his", fetched_at=1.0,
    )
    db.upsert_fund_flow(r1)

    r2 = FundFlowRecord(
        ticker="AAPL", date="2026-07-14",
        main_net=9999999, super_big_net=8888888,
        source="ff", fetched_at=2.0,
    )
    db.upsert_fund_flow(r2)

    rows = db.get_fund_flow("AAPL", days=5)
    assert len(rows) == 1
    assert rows[0]["main_net"] == 9999999
    assert rows[0]["source"] == "ff"


def test_get_fund_flow_ordering(db):
    """get_fund_flow returns rows in chronological order (oldest first)."""
    for i, date in enumerate(["2026-07-10", "2026-07-11", "2026-07-14"]):
        db.upsert_fund_flow(FundFlowRecord(
            ticker="NVDA", date=date,
            main_net=float(i), source="push2his", fetched_at=float(i),
        ))
    rows = db.get_fund_flow("NVDA", days=20)
    assert len(rows) == 3
    assert rows[0]["date"] == "2026-07-10"
    assert rows[-1]["date"] == "2026-07-14"


def test_get_latest_fund_flow_date(db):
    assert db.get_latest_fund_flow_date("TSLA") is None

    db.upsert_fund_flow(FundFlowRecord(
        ticker="TSLA", date="2026-07-13",
        source="push2his", fetched_at=1.0,
    ))
    db.upsert_fund_flow(FundFlowRecord(
        ticker="TSLA", date="2026-07-14",
        source="push2his", fetched_at=2.0,
    ))
    assert db.get_latest_fund_flow_date("TSLA") == "2026-07-14"


def test_get_db_stats_includes_fund_flow(db):
    db.upsert_fund_flow(FundFlowRecord(
        ticker="AAPL", date="2026-07-14",
        source="push2his", fetched_at=1.0,
    ))
    stats = db.get_db_stats()
    assert stats.get("fund_flow_count", 0) >= 1
