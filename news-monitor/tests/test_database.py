"""Tests for database module."""
import pytest
import os
import tempfile
from datetime import datetime
from storage.database import Database
from storage.models import NewsItem, FeedbackRecord


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
