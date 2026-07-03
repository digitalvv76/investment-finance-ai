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
