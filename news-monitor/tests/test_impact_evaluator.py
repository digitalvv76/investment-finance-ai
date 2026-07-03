"""Smoke tests for ImpactEvaluator — gates, prompt loading, health monitor."""
import json
import pytest
from engine.impact_evaluator import (
    ImpactEvaluator, HealthMonitor, PromptVersionManager,
    _validate_input, _validate_output
)
from storage.models import NewsItem, ImpactAssessment


class TestDataQualityGate:
    def test_valid_item_passes(self):
        item = NewsItem(title="Fed raises rates by 50bp",
                        content_snippet="The Federal Reserve announced a 50 basis point "
                                       "rate hike today, surprising markets that expected 25bp. "
                                       "The decision was unanimous and the forward guidance "
                                       "signaled further tightening ahead.")
        ok, reason = _validate_input(item)
        assert ok is True
        assert reason == "ok"

    def test_empty_title_fails(self):
        item = NewsItem(title="", content_snippet="x" * 100)
        ok, reason = _validate_input(item)
        assert ok is False
        assert "title" in reason

    def test_short_content_fails(self):
        item = NewsItem(title="Some headline", content_snippet="short")
        ok, reason = _validate_input(item)
        assert ok is False
        assert "content" in reason


class TestExplainabilityGate:
    def test_valid_output_passes(self):
        a = ImpactAssessment(
            impact_score=75, confidence=80, event_category="monetary",
            surprise_level="major_surprise", breadth="broad_market",
            reasoning_chain='["s1","s2","s3","s4","s5"]'
        )
        a.reasoning_chain = json.dumps(["step 1", "step 2", "step 3", "step 4", "step 5"])
        ok, issues = _validate_output(a)
        assert ok is True

    def test_cross_asset_low_score_flags(self):
        a = ImpactAssessment(impact_score=15, breadth="cross_asset",
                            reasoning_chain='["1","2","3","4","5"]')
        ok, issues = _validate_output(a)
        assert ok is False
        assert any("cross_asset" in i for i in issues)

    def test_low_confidence_marks_flag(self):
        a = ImpactAssessment(confidence=25, breadth="sector",
                            reasoning_chain='["1","2","3","4","5"]')
        _validate_output(a)
        assert a.low_confidence is True


class TestHealthMonitor:
    def test_initial_healthy(self):
        hm = HealthMonitor()
        assert hm.health["status"] == "healthy"
        assert hm.health["consecutive_failures"] == 0

    def test_consecutive_failures_trigger_degraded(self):
        hm = HealthMonitor()
        for i in range(5):
            hm.record_failure("timeout")
        assert hm.health["consecutive_failures"] == 5
        assert hm.health["status"] == "degraded"


class TestPromptVersionManager:
    def test_load_v1_returns_string(self):
        prompt = PromptVersionManager.load("v1")
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert "hedge fund" in prompt.lower()

    def test_load_missing_falls_back_to_v1(self):
        prompt = PromptVersionManager.load("v9_nonexistent")
        assert isinstance(prompt, str)
        assert len(prompt) > 100


class TestImpactCollector:
    def test_normalize_actual_score_typical(self):
        from engine.impact_collector import ImpactCollector
        c = ImpactCollector.__new__(ImpactCollector)
        score = c._normalize_score(
            spx_change=-2.1, vix_change=18.0,
            sector_count=5, bonds_moved=True, fx_moved=False, commodities_moved=True
        )
        # spx: min(2.1/3,1)*100=70 *0.4 = 28
        # vix: min(18/15,1)*100=100 *0.25 = 25
        # sector: 5/11*100=45.5 *0.2 = 9.1
        # cross: (1+0+1)/3*100=66.7 *0.15 = 10
        # total ≈ 72
        assert 65 < score < 80

    def test_normalize_actual_score_zero(self):
        from engine.impact_collector import ImpactCollector
        c = ImpactCollector.__new__(ImpactCollector)
        score = c._normalize_score(
            spx_change=0, vix_change=0, sector_count=0,
            bonds_moved=False, fx_moved=False, commodities_moved=False
        )
        assert score == 0.0

    def test_normalize_actual_score_max(self):
        from engine.impact_collector import ImpactCollector
        c = ImpactCollector.__new__(ImpactCollector)
        score = c._normalize_score(
            spx_change=-5.0, vix_change=30.0, sector_count=11,
            bonds_moved=True, fx_moved=True, commodities_moved=True
        )
        assert score == 100.0


class TestImpactLearner:
    def test_no_samples_returns_empty_hint(self):
        from engine.impact_learner import ImpactLearner
        learner = ImpactLearner()
        hint = learner._build_hint({})
        assert hint == "No calibration data yet"

    def test_single_category_bias(self):
        from engine.impact_learner import ImpactLearner
        learner = ImpactLearner()
        hint = learner._build_hint({"monetary": 4.0})
        assert "monetary" in hint
        assert "over-estimate" in hint

    def test_bias_below_threshold_not_included(self):
        from engine.impact_learner import ImpactLearner
        learner = ImpactLearner()
        hint = learner._build_hint({"macro_data": 1.5})  # < 2.0 threshold
        assert hint == "No calibration data yet"
