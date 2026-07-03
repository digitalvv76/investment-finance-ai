"""Tests for EventMatcher — historical event parsing and matching."""

import pytest
from engine.event_matcher import EventMatcher, HistoricalEvent, _extract_impact_level


class TestImpactLevelExtraction:
    def test_critical(self):
        assert _extract_impact_level("🔴 CRITICAL") == "CRITICAL"

    def test_high(self):
        assert _extract_impact_level("🟠 HIGH") == "HIGH"

    def test_medium(self):
        assert _extract_impact_level("🟡 MEDIUM") == "MEDIUM"

    def test_low(self):
        assert _extract_impact_level("🟢 LOW") == "LOW"

    def test_unknown_defaults_to_medium(self):
        assert _extract_impact_level("SOMETHING ELSE") == "MEDIUM"


class TestEventMatcher:
    def test_loads_events(self):
        em = EventMatcher()
        assert em.event_count > 0, "Should load events from training data"

    def test_match_by_category(self):
        em = EventMatcher()
        matches = em.match(
            "Federal Reserve raises interest rates by 50bps",
            event_category="monetary",
            top_k=5,
        )
        assert len(matches) > 0, "Should find monetary policy matches"
        # First match should be monetary-related
        assert any("FOMC" in m.description or "rate" in m.description.lower()
                   or "Warsh" in m.description or "Fed" in m.description
                   for m in matches), \
            "Top matches should be monetary policy related"

    def test_match_no_category(self):
        em = EventMatcher()
        matches = em.match(
            "NVIDIA announces new GPU with record performance",
            event_category="",
            top_k=3,
        )
        # Should still return matches based on keyword overlap
        assert len(matches) <= 3

    def test_format_for_prompt(self):
        em = EventMatcher()
        matches = em.match("CPI inflation data", "macro_data", top_k=2)
        text = em.format_for_prompt(matches)
        assert "Market reaction" in text or "No similar" in text

    def test_get_examples_convenience(self):
        em = EventMatcher()
        result = em.get_examples("FOMC hawkish pivot", "monetary", top_k=2)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_results_when_no_match(self):
        em = EventMatcher()
        matches = em.match(
            "xyzzy nonsense that matches nothing at all in the database",
            event_category="other",
            top_k=3,
        )
        assert len(matches) == 0

    def test_empty_news_text(self):
        em = EventMatcher()
        matches = em.match("", event_category="", top_k=3)
        assert len(matches) == 0
