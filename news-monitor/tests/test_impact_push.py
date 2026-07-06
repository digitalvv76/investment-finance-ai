"""Tests for impact-based push decision logic."""

import pytest
from unittest.mock import MagicMock
from engine.alert_dispatcher import AlertDispatcher, AlertLevel


class StubImpactAssessment:
    """Minimal stub that mimics ImpactAssessment for classify() tests."""

    def __init__(self, impact_score: int, confidence: int):
        self.impact_score = impact_score
        self.confidence = confidence


class TestImpactPushClassification:
    def setup_method(self):
        self.dispatcher = AlertDispatcher()

    # --- impact-first path ---

    def test_high_impact_triggers_critical(self):
        """impact=90, conf=80, rel=1.0 → composite=87 → CRITICAL"""
        assessment = StubImpactAssessment(impact_score=90, confidence=80)
        level, reason = self.dispatcher.classify(
            0.5, [], impact_assessment=assessment, rel_mult=1.0,
        )
        assert level == AlertLevel.CRITICAL
        assert "high_impact" in reason
        assert "87" in reason  # composite ≈ 87

    def test_moderate_impact_triggers_important(self):
        """impact=50, conf=55, rel=1.0 → composite=51.5 → IMPORTANT"""
        assessment = StubImpactAssessment(impact_score=50, confidence=55)
        level, reason = self.dispatcher.classify(
            0.4, [], impact_assessment=assessment, rel_mult=1.0,
        )
        assert level == AlertLevel.IMPORTANT
        assert "moderate_impact" in reason

    def test_low_impact_stays_normal(self):
        """impact=30, conf=40, rel=1.0 → composite=33 → NORMAL"""
        assessment = StubImpactAssessment(impact_score=30, confidence=40)
        level, reason = self.dispatcher.classify(
            0.3, [], impact_assessment=assessment, rel_mult=1.0,
        )
        assert level == AlertLevel.NORMAL
        assert "low_impact" in reason

    # --- relevance multiplier ---

    def test_relevance_boosts_impact(self):
        """impact=50, conf=60, rel=1.4 → composite=74 → CRITICAL (pushed up)"""
        assessment = StubImpactAssessment(impact_score=50, confidence=60)
        level, reason = self.dispatcher.classify(
            0.4, [], impact_assessment=assessment, rel_mult=1.4,
        )
        # 50*0.7 + 60*0.3 = 53, *1.4 = 74 → CRITICAL
        assert level == AlertLevel.CRITICAL

    def test_relevance_demotes_impact(self):
        """impact=80, conf=80, rel=0.3 → composite=24 → NORMAL (demoted)"""
        assessment = StubImpactAssessment(impact_score=80, confidence=80)
        level, reason = self.dispatcher.classify(
            0.5, [], impact_assessment=assessment, rel_mult=0.3,
        )
        # 80*0.7 + 80*0.3 = 80, *0.3 = 24 → NORMAL
        assert level == AlertLevel.NORMAL

    # --- legacy fallback (no impact_assessment) ---

    def test_legacy_critical_by_score(self):
        level, reason = self.dispatcher.classify(0.70, [])
        assert level == AlertLevel.CRITICAL

    def test_legacy_critical_by_gov_intervention(self):
        from engine.strategic_detector import StrategicMatch
        match = StrategicMatch(category="gov_intervention", confidence=0.90,
                               matched_text="US invests in Intel")
        level, reason = self.dispatcher.classify(0.30, [match])
        assert level == AlertLevel.CRITICAL

    def test_legacy_nvda_critical(self):
        from engine.strategic_detector import StrategicMatch
        match = StrategicMatch(category="nvda_investment", confidence=0.75,
                               matched_text="NVIDIA acquires startup")
        level, reason = self.dispatcher.classify(0.30, [match])
        assert level == AlertLevel.CRITICAL
