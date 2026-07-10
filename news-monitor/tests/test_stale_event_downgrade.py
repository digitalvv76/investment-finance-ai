"""Tests for stale-event push downgrade — SPEC-stale-event-downgrade.md

IMPORTANT events with event_line first_seen > 60min → downgrade to NOTABLE (silent TG).
CRITICAL exempt; unknown age keeps original level.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

from pipeline.item import AlertLevel


# ══════════════════════════════════════════════════════════════════════════
# Pure function tests — _downgrade_if_stale
# ══════════════════════════════════════════════════════════════════════════

class TestDowngradeIfStale:
    """6 cases from SPEC §6."""

    @pytest.fixture(autouse=True)
    def _import_func(self):
        from pipeline.evaluate import _downgrade_if_stale
        self.fn = _downgrade_if_stale

    def test_stale_important_becomes_notable(self):
        """Case 1: main bug scenario — old IMPORTANT → NOTABLE (Micron case)."""
        assert self.fn(AlertLevel.IMPORTANT, 90) == AlertLevel.NOTABLE

    def test_fresh_important_stays(self):
        """Case 2: fresh (< threshold) stays IMPORTANT."""
        assert self.fn(AlertLevel.IMPORTANT, 30) == AlertLevel.IMPORTANT

    def test_unknown_age_keeps_original(self):
        """Case 3: age unknown (None) → no penalty."""
        assert self.fn(AlertLevel.IMPORTANT, None) == AlertLevel.IMPORTANT

    def test_critical_exempt(self):
        """Case 4: CRITICAL always exempt, no matter how old."""
        assert self.fn(AlertLevel.CRITICAL, 999) == AlertLevel.CRITICAL

    def test_notable_passthrough(self):
        """Case 5: non-IMPORTANT levels pass through unchanged."""
        assert self.fn(AlertLevel.NOTABLE, 999) == AlertLevel.NOTABLE

    def test_boundary_exact_60_not_downgraded(self):
        """Case 6: age == 60 is NOT downgraded (>60 is, =60 is not)."""
        assert self.fn(AlertLevel.IMPORTANT, 60) == AlertLevel.IMPORTANT

    def test_normal_passthrough(self):
        """NORMAL passes through unchanged."""
        assert self.fn(AlertLevel.NORMAL, 999) == AlertLevel.NORMAL

    def test_just_over_threshold_downgrades(self):
        """61 minutes → downgraded."""
        assert self.fn(AlertLevel.IMPORTANT, 61) == AlertLevel.NOTABLE

    def test_very_stale_many_hours(self):
        """Many hours old → still downgraded to NOTABLE, not lower."""
        assert self.fn(AlertLevel.IMPORTANT, 600) == AlertLevel.NOTABLE

    # ── Multi-source exemption (方案B) ──

    def test_multi_source_exempt_stale(self):
        """Multi-source (≥3) confirmed event exempt from stale downgrade."""
        assert self.fn(AlertLevel.IMPORTANT, 600, multi_source=True) == AlertLevel.IMPORTANT

    def test_single_source_stale_still_downgraded(self):
        """Single-source stale event (Micron case) still downgraded."""
        assert self.fn(AlertLevel.IMPORTANT, 90, multi_source=False) == AlertLevel.NOTABLE

    def test_multi_source_default_false(self):
        """multi_source defaults to False (backward compat)."""
        assert self.fn(AlertLevel.IMPORTANT, 90) == AlertLevel.NOTABLE

    def test_multi_source_fresh_stays_important(self):
        """Multi-source fresh event stays IMPORTANT (no change)."""
        assert self.fn(AlertLevel.IMPORTANT, 30, multi_source=True) == AlertLevel.IMPORTANT


# ══════════════════════════════════════════════════════════════════════════
# DB helper tests — _event_line_age_minutes
# ══════════════════════════════════════════════════════════════════════════

class TestEventLineAge:
    """Verify the SQL query and edge cases."""

    @pytest.fixture
    def stage(self):
        from pipeline.evaluate import EvaluateStage
        db = MagicMock()
        db._get_conn = MagicMock()
        return EvaluateStage(impact_evaluator=MagicMock(), dispatcher=MagicMock(), db=db)

    def test_returns_none_when_no_db(self):
        from pipeline.evaluate import EvaluateStage
        s = EvaluateStage(impact_evaluator=MagicMock(), dispatcher=MagicMock(), db=None)
        assert s._event_line_age_minutes(1) is None

    def test_returns_none_when_no_news_id(self, stage):
        assert stage._event_line_age_minutes(0) is None
        assert stage._event_line_age_minutes(None) is None

    def test_returns_none_when_no_matching_row(self, stage):
        stage._db._get_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = None
        assert stage._event_line_age_minutes(999) is None

    def test_returns_age_from_db(self, stage):
        stage._db._get_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {
            "age_min": "45.5"
        }
        assert stage._event_line_age_minutes(1) == 45.5

    def test_negative_clamped_to_zero(self, stage):
        """Clock skew should not produce negative age."""
        stage._db._get_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {
            "age_min": "-5.0"
        }
        assert stage._event_line_age_minutes(1) == 0.0

    def test_db_exception_returns_none(self, stage):
        stage._db._get_conn.side_effect = Exception("DB down")
        assert stage._event_line_age_minutes(1) is None


# ══════════════════════════════════════════════════════════════════════════
# Integration: _apply_event_assessment downgrade wiring
# ══════════════════════════════════════════════════════════════════════════

class TestApplyEventAssessmentDowngrade:
    """Verify the downgrade is wired into _apply_event_assessment."""

    @pytest.fixture
    def stage(self):
        from pipeline.evaluate import EvaluateStage
        db = MagicMock()
        db._get_conn = MagicMock()
        return EvaluateStage(impact_evaluator=MagicMock(), dispatcher=MagicMock(), db=db)

    @pytest.fixture
    def item(self):
        return __import__('pipeline.item', fromlist=['PipelineItem']).PipelineItem(
            id=3340, title="美光2500亿美元押注推动芯片复苏",
            source="globenewswire", url="http://x.com/1",
            priority_score=0.75, tickers_found="MU", is_breaking=False,
        )

    @pytest.fixture
    def event_assessment(self):
        from engine.event_driven_evaluator import EventAssessment
        return EventAssessment(
            is_event=True,
            intensity=4,
            event_types=[1],
            sector_tags=["semiconductors"],
            headline_signal="美光$250B投资推动芯片复苏",
            ticker_hint=["MU"],
            risk_snapshot="事件已被市场消化",
            filter_reason="",
        )

    def test_stale_important_event_downgraded(self, stage, item, event_assessment):
        """Integration: old IMPORTANT event → DispatchDecision has NOTABLE."""
        # Simulate DB returning 90 min age
        stage._db._get_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {
            "age_min": "90.0"
        }

        stage._apply_event_assessment(item, event_assessment)

        assert item.decision.alert_level == AlertLevel.NOTABLE
        assert "stale_downgrade" in item.decision.alert_reason

    def test_fresh_event_not_downgraded(self, stage, item, event_assessment):
        """Fresh event (15 min) stays IMPORTANT."""
        stage._db._get_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {
            "age_min": "15.0"
        }

        stage._apply_event_assessment(item, event_assessment)

        assert item.decision.alert_level == AlertLevel.IMPORTANT
        assert "stale_downgrade" not in item.decision.alert_reason

    def test_no_db_keeps_original(self, item, event_assessment):
        """Without DB, the downgrade is skipped gracefully."""
        from pipeline.evaluate import EvaluateStage
        stage = EvaluateStage(impact_evaluator=MagicMock(), dispatcher=MagicMock(), db=None)

        stage._apply_event_assessment(item, event_assessment)

        assert item.decision.alert_level == AlertLevel.IMPORTANT

    def test_critical_exempt_integration(self, stage, item, event_assessment):
        """CRITICAL (intensity 5) never downgraded."""
        event_assessment.intensity = 5

        stage._db._get_conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {
            "age_min": "999.0"
        }

        stage._apply_event_assessment(item, event_assessment)

        assert item.decision.alert_level == AlertLevel.CRITICAL

    def test_multi_source_stale_exempt_integration(self, stage, item, event_assessment):
        """方案B: multi-source (≥3) stale event exempt from downgrade.

        A story still developing at 90min with 3+ sources escalates to
        intensity 5 (CRITICAL) via multi-source +1, and even if it were
        IMPORTANT the multi_source flag would exempt it.
        """
        # source_count=3 → escalation +1 (intensity 4→5 CRITICAL) AND multi_source exempt
        stage._get_event_source_count = MagicMock(return_value=3)
        stage._event_line_age_minutes = MagicMock(return_value=90.0)

        stage._apply_event_assessment(item, event_assessment)

        # intensity 4 + multi-source +1 = 5 → CRITICAL, never downgraded
        assert item.decision.alert_level == AlertLevel.CRITICAL
        assert "stale_downgrade" not in item.decision.alert_reason

    def test_multi_source_important_stale_exempt(self, stage, item, event_assessment):
        """Multi-source event that stays IMPORTANT (intensity capped) still exempt.

        Simulate an event already at intensity 5 pre-escalation so +1 is
        skipped (cap), but source_count≥3 → multi_source exempt keeps it as-is.
        Use intensity=3 with 3 sources → escalates to 4 (IMPORTANT), exempt.
        """
        event_assessment.intensity = 3  # → +1 = 4 IMPORTANT (not CRITICAL)
        stage._get_event_source_count = MagicMock(return_value=3)
        stage._event_line_age_minutes = MagicMock(return_value=200.0)

        stage._apply_event_assessment(item, event_assessment)

        # IMPORTANT but multi-source → NOT downgraded despite 200min age
        assert item.decision.alert_level == AlertLevel.IMPORTANT
        assert "stale_downgrade" not in item.decision.alert_reason


# ══════════════════════════════════════════════════════════════════════════
# Real SQLite timezone tests — closes the mock-string blind spot (CONCERN-2)
# ══════════════════════════════════════════════════════════════════════════

class TestRealSqliteTimezone:
    """Run the actual age SQL against a real in-memory SQLite DB.

    The unit tests above mock the DB and feed pre-computed string ages, so they
    never exercise the julianday timezone math. This class does — it is the only
    guard against the 'captured_at timezone' trap (local first_seen vs UTC now).
    """

    @pytest.fixture
    def stage_with_real_db(self):
        """Build a stage whose db._get_conn yields a real SQLite conn."""
        from pipeline.evaluate import EvaluateStage

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE event_lines (id INTEGER PRIMARY KEY, "
            "first_seen TIMESTAMP, is_active INTEGER DEFAULT 1)"
        )
        conn.execute(
            "CREATE TABLE news (id INTEGER PRIMARY KEY, event_line_id INTEGER)"
        )

        db = MagicMock()

        @contextmanager
        def _get_conn():
            yield conn

        db._get_conn = _get_conn
        stage = EvaluateStage(
            impact_evaluator=MagicMock(), dispatcher=MagicMock(), db=db,
        )
        return stage, conn

    def test_local_first_seen_90min_ago(self, stage_with_real_db):
        """first_seen written as LOCAL naive datetime (cluster.py:206 path).

        This is the ONLY write path in production. Age must be ~90, NOT ~570
        (which would mean the localtime/UTC mismatch bug had returned).
        """
        stage, conn = stage_with_real_db
        local_90 = datetime.now() - timedelta(minutes=90)
        conn.execute("INSERT INTO event_lines (id, first_seen) VALUES (1, ?)",
                     (local_90.isoformat(),))
        conn.execute("INSERT INTO news (id, event_line_id) VALUES (10, 1)")

        age = stage._event_line_age_minutes(10)
        assert age is not None
        assert 88 <= age <= 92, f"expected ~90, got {age} (timezone bug?)"

    def test_local_first_seen_space_separator(self, stage_with_real_db):
        """first_seen with space separator (not T) must also parse correctly."""
        stage, conn = stage_with_real_db
        local_90 = datetime.now() - timedelta(minutes=90)
        conn.execute("INSERT INTO event_lines (id, first_seen) VALUES (1, ?)",
                     (local_90.strftime("%Y-%m-%d %H:%M:%S"),))
        conn.execute("INSERT INTO news (id, event_line_id) VALUES (10, 1)")

        age = stage._event_line_age_minutes(10)
        assert age is not None
        assert 88 <= age <= 92, f"expected ~90, got {age}"

    def test_fresh_local_first_seen_not_stale(self, stage_with_real_db):
        """A just-created event line → age ~0 → not stale."""
        stage, conn = stage_with_real_db
        conn.execute("INSERT INTO event_lines (id, first_seen) VALUES (1, ?)",
                     (datetime.now().isoformat(),))
        conn.execute("INSERT INTO news (id, event_line_id) VALUES (10, 1)")

        age = stage._event_line_age_minutes(10)
        assert age is not None
        assert age < 2, f"expected ~0, got {age}"

    def test_null_event_line_id_returns_none(self, stage_with_real_db):
        """news row with NULL event_line_id → no JOIN match → None (safe)."""
        stage, conn = stage_with_real_db
        conn.execute("INSERT INTO news (id, event_line_id) VALUES (10, NULL)")

        assert stage._event_line_age_minutes(10) is None

    def test_inactive_event_line_returns_none(self, stage_with_real_db):
        """is_active=0 event line → filtered out → None."""
        stage, conn = stage_with_real_db
        local_90 = datetime.now() - timedelta(minutes=90)
        conn.execute(
            "INSERT INTO event_lines (id, first_seen, is_active) VALUES (1, ?, 0)",
            (local_90.isoformat(),))
        conn.execute("INSERT INTO news (id, event_line_id) VALUES (10, 1)")

        assert stage._event_line_age_minutes(10) is None
