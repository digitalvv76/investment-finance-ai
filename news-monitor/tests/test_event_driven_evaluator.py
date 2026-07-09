"""Smoke tests for EventDrivenEvaluator — JSON parsing + decision logic."""

import pytest
from engine.event_driven_evaluator import EventAssessment


class TestEventAssessmentParsing:
    """JSON parsing correctness — no LLM call needed."""

    def test_full_event_json(self):
        raw = """{"is_event": true, "event_types": [1, 2], "intensity": 5, "sector_tags": ["AI", "Semiconductors"], "headline_signal": "英伟达参股SoundHound", "ticker_hint": ["SOUN"], "risk_snapshot": "投资仅是财务性质"}"""
        ea = EventAssessment.from_json(raw)
        assert ea.is_event is True
        assert ea.event_types == [1, 2]
        assert ea.intensity == 5
        assert ea.sector_tags == ["AI", "Semiconductors"]
        assert ea.headline_signal == "英伟达参股SoundHound"
        assert ea.ticker_hint == ["SOUN"]
        assert ea.risk_snapshot == "投资仅是财务性质"
        assert ea.should_push is True
        assert ea.alert_level == "critical"

    def test_filtered_non_us(self):
        raw = """{"is_event": false, "filter_reason": "纯A股政策，无美股映射"}"""
        ea = EventAssessment.from_json(raw)
        assert ea.is_event is False
        assert ea.should_push is False
        assert "A股" in ea.filter_reason

    def test_no_catalyst_triggered(self):
        raw = """{"is_event": false, "reason": "no catalyst triggered"}"""
        ea = EventAssessment.from_json(raw)
        assert ea.is_event is False
        assert ea.should_push is False
        assert "no catalyst" in ea.filter_reason

    def test_low_intensity_no_push(self):
        raw = """{"is_event": true, "event_types": [4], "intensity": 2, "sector_tags": ["Biotech"], "headline_signal": "FDA批准某器械", "ticker_hint": ["ABC"], "risk_snapshot": "市场规模有限"}"""
        ea = EventAssessment.from_json(raw)
        assert ea.is_event is True
        assert ea.intensity == 2
        assert ea.should_push is False  # intensity < 3

    def test_intensity_3_push(self):
        raw = """{"is_event": true, "event_types": [3], "intensity": 3, "sector_tags": ["EV"], "headline_signal": "马斯克宣布新工厂", "ticker_hint": ["TSLA"], "risk_snapshot": "建厂周期长"}"""
        ea = EventAssessment.from_json(raw)
        assert ea.should_push is True
        assert ea.intensity == 3

    def test_markdown_wrapped_json(self):
        raw = """```json
{"is_event": true, "event_types": [5], "intensity": 4, "sector_tags": ["Meme Stocks"], "headline_signal": "Roaring Kitty发帖", "ticker_hint": ["GME"], "risk_snapshot": "短期炒作"}
```"""
        ea = EventAssessment.from_json(raw)
        assert ea.is_event is True
        assert ea.intensity == 4
        assert ea.ticker_hint == ["GME"]

    def test_empty_input(self):
        ea = EventAssessment.from_json("")
        assert ea.is_event is False
        assert "JSON parse error" in ea.filter_reason

    def test_malformed_json(self):
        ea = EventAssessment.from_json("not json at all")
        assert ea.is_event is False
        assert "JSON parse error" in ea.filter_reason

    def test_string_intensity_coerced(self):
        raw = """{"is_event": true, "event_types": [1], "intensity": "4", "sector_tags": [], "headline_signal": "测试", "ticker_hint": [], "risk_snapshot": ""}"""
        ea = EventAssessment.from_json(raw)
        assert ea.intensity == 4  # coerced from string
        assert ea.should_push is True

    def test_null_fields_default(self):
        raw = "{}"
        ea = EventAssessment.from_json(raw)
        assert ea.is_event is False
        assert ea.intensity == 0
        assert ea.event_types == []
        assert ea.sector_tags == []
        assert ea.should_push is False


class TestDecisionMapping:
    """Alert level mapping from intensity."""

    def test_intensity_5_critical(self):
        ea = EventAssessment(is_event=True, intensity=5)
        assert ea.alert_level == "critical"
        assert ea.should_push is True

    def test_intensity_4_important(self):
        ea = EventAssessment(is_event=True, intensity=4)
        assert ea.alert_level == "important"
        assert ea.should_push is True

    def test_intensity_3_important(self):
        ea = EventAssessment(is_event=True, intensity=3)
        assert ea.alert_level == "important"
        assert ea.should_push is True

    def test_intensity_1_normal(self):
        ea = EventAssessment(is_event=True, intensity=1)
        assert ea.should_push is False
        assert ea.alert_level == "normal"

    def test_not_event_normal(self):
        ea = EventAssessment(is_event=False, filter_reason="noise")
        assert ea.should_push is False
        assert ea.alert_level == "normal"
