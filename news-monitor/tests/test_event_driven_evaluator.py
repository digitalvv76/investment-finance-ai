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

    def test_intensity_3_notable(self):
        """SPEC-intensity-scale-bear-bias §4b: intensity 3 → notable (silent TG,
        no phone). Phone threshold raised to ≥4."""
        ea = EventAssessment(is_event=True, intensity=3)
        assert ea.alert_level == "notable"
        assert ea.should_push is True  # still pushed, just TG-only

    def test_intensity_1_normal(self):
        ea = EventAssessment(is_event=True, intensity=1)
        assert ea.should_push is False


class TestDirectionAwareChannel:
    """SPEC-intensity-scale-bear-bias §4/§4b — direction-aware channel + bearish
    escalation. event_channel_level is the single source of truth used by both
    EventAssessment.alert_level (base) and the pipeline (with tracked)."""

    def test_bearish_unconfirmed_notable(self):
        """FAIL-SAFE: reportedly bearish ★5 → notable (silent TG, never phone),
        even at high intensity — the source-confidence gate."""
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(5, "down") == "notable"           # confirmed defaults False
        assert event_channel_level(4, "down", confirmed=False) == "notable"

    def test_bearish_confirmed_caps_at_important(self):
        """Confirmed bearish (not hitting tracked) → important (channel B, no siren)."""
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(5, "down", confirmed=True) == "important"
        assert event_channel_level(4, "down", confirmed=True) == "important"

    def test_bullish_5_critical(self):
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(5, "up") == "critical"

    def test_neutral_direction_caps_at_important(self):
        """FAIL-SAFE #2: neutral/unknown direction never sirens — caps at important."""
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(5, "neutral") == "important"
        assert event_channel_level(5, "") == "important"
        assert event_channel_level(5, "DOWN ") == "notable"  # stripped+lowered → down, unconfirmed

    def test_intensity_3_notable_both_directions(self):
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(3, "up") == "notable"
        assert event_channel_level(3, "down", confirmed=True) == "notable"

    def test_bearish_escalates_when_tracked_and_confirmed(self):
        """Bearish 5 hitting a tracked name AND confirmed → critical (siren)."""
        from engine.event_driven_evaluator import event_channel_level
        lvl = event_channel_level(5, "down", confirmed=True,
                                  losers={"GOOGL"}, tracked={"GOOGL", "AAPL"})
        assert lvl == "critical"

    def test_bearish_rumor_stays_off_phone(self):
        """cal-01 trap: bearish hits tracked GOOGL but reportedly → notable (off phone),
        NOT important — fail-safe closes the multi-source-to-phone leak."""
        from engine.event_driven_evaluator import event_channel_level
        lvl = event_channel_level(5, "down", confirmed=False,
                                  losers={"GOOGL"}, tracked={"GOOGL"})
        assert lvl == "notable"

    def test_bearish_confirmed_not_tracked_important(self):
        from engine.event_driven_evaluator import event_channel_level
        lvl = event_channel_level(5, "down", confirmed=True,
                                  losers={"XYZ"}, tracked={"GOOGL"})
        assert lvl == "important"

    def test_intensity_3_bearish_never_escalates(self):
        """A ★3 bearish stays notable even if tracked+confirmed (escalation is ★4/5)."""
        from engine.event_driven_evaluator import event_channel_level
        lvl = event_channel_level(3, "down", confirmed=True,
                                  losers={"GOOGL"}, tracked={"GOOGL"})
        assert lvl == "notable"

    def test_direction_confirmed_parsed_from_json(self):
        raw = """{"is_event": true, "event_types": [], "intensity": 3, "direction": "down", "confirmed": false, "ticker_hint": ["GOOGL","MSFT"], "headline_signal": "x", "risk_snapshot": "y"}"""
        ea = EventAssessment.from_json(raw)
        assert ea.direction == "down"
        assert ea.confirmed is False
        assert ea.alert_level == "notable"  # ★3 → notable regardless of direction

    def test_direction_defaults_up_when_absent(self):
        """Backward compat: no direction field → 'up' (old bullish behavior)."""
        raw = """{"is_event": true, "event_types": [1], "intensity": 5, "ticker_hint": ["INTC"], "headline_signal": "x", "risk_snapshot": "y"}"""
        ea = EventAssessment.from_json(raw)
        assert ea.direction == "up"
        assert ea.confirmed is False  # fail-safe default (bullish path ignores it)
        assert ea.alert_level == "critical"

    def test_not_event_normal(self):
        ea = EventAssessment(is_event=False, filter_reason="noise")
        assert ea.should_push is False
        assert ea.alert_level == "normal"

    # ── Opinion-based event type cap ──

    def test_institutional_flow_4_notable(self):
        """ARK增持/基金调仓等 event_type 3 ★4 → notable, no phone.
        User policy: 别人的操作/观点 → TG only."""
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(4, "up", event_types=[3]) == "notable"
        assert event_channel_level(4, "up", confirmed=True, event_types=[3]) == "notable"

    def test_institutional_flow_5_critical(self):
        """Event type 3 ★5 → critical (phone siren) — massive flow still gets through."""
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(5, "up", event_types=[3]) == "critical"

    def test_institutional_flow_3_notable(self):
        """★3 is already notable; event_type 3 doesn't change that."""
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(3, "up", event_types=[3]) == "notable"

    def test_mixed_event_types_not_capped(self):
        """Event types [1, 3] (earnings + flow) → NOT pure opinion → normal rules apply."""
        from engine.event_driven_evaluator import event_channel_level
        # Mixed: includes hard event type 1, so opinion cap doesn't trigger
        assert event_channel_level(4, "up", event_types=[1, 3]) == "important"

    def test_hard_event_types_unchanged(self):
        """Event types 1, 2, 4 (earnings, policy, macro) unchanged by opinion cap."""
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(4, "up", event_types=[1]) == "important"
        assert event_channel_level(4, "up", event_types=[2]) == "important"
        assert event_channel_level(4, "up", event_types=[4]) == "important"
        assert event_channel_level(5, "up", event_types=[1]) == "critical"

    def test_no_event_types_backward_compat(self):
        """event_types=None (legacy path) → normal rules, no opinion cap."""
        from engine.event_driven_evaluator import event_channel_level
        assert event_channel_level(4, "up") == "important"
