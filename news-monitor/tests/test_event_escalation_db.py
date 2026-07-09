import pytest
from storage.database import Database
from storage.models import NewsItem, EventLine, ImpactAssessment

@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    d.migrate_event_escalation()
    return d

def test_migration_adds_columns(db):
    with db._get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_lines)").fetchall()}
    assert {"escalation_state", "peak_impact", "dominant_category",
            "dominant_sentiment", "alerted_at"} <= cols

def test_migration_idempotent(db):
    db.migrate_event_escalation()  # second call must not raise
    assert True

def test_update_and_read_escalation(db):
    with db._get_conn() as conn:
        conn.execute("INSERT INTO event_lines (title, news_ids, source_count, "
                     "first_seen, last_updated, is_active) VALUES "
                     "('US-Iran', '1,2,3', 3, datetime('now'), datetime('now'), 1)")
    db.update_event_escalation(1, escalation_state="ALERTED", peak_impact=95.0)
    rows = db.get_active_event_lines(active_window_hours=12)
    assert rows[0]["escalation_state"] == "ALERTED"
    assert rows[0]["peak_impact"] == 95.0

def test_peak_impact_for_news_ids(db):
    a = ImpactAssessment(news_id=1, impact_score=40, event_category="geopolitical", sentiment="BEARISH")
    b = ImpactAssessment(news_id=2, impact_score=95, event_category="geopolitical", sentiment="BEARISH")
    db.insert_assessment(a); db.insert_assessment(b)
    peak, cat, sent = db.get_peak_impact_for_news_ids([1, 2])
    assert peak == 95
    assert cat == "geopolitical"
    assert sent == "BEARISH"
