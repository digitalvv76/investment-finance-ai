"""Tests for the watchlist/portfolio safety-net push gate.

When the event sentinel judges a news item is_event=false (not a wealth-effect
catalyst), we still want a *silent Telegram* ping if the LLM flagged a
substantive action (notable=true) on a ticker the user tracks. The phone stays
strict — this path never buzzes it.
"""

import pytest

from engine.event_driven_evaluator import EventAssessment, watchlist_safety_net


class TestWatchlistSafetyNet:
    def test_fires_for_notable_action_on_tracked_ticker(self):
        ea = EventAssessment(is_event=False, notable=True, ticker_hint=["TSLA"])
        assert watchlist_safety_net(ea, {"TSLA", "NVDA"}) is True

    def test_silent_when_not_notable(self):
        # Passing mention of a tracked name — no substantive action → no ping.
        ea = EventAssessment(is_event=False, notable=False, ticker_hint=["TSLA"])
        assert watchlist_safety_net(ea, {"TSLA"}) is False

    def test_silent_when_ticker_not_tracked(self):
        # Real move but on a name the user does not follow.
        ea = EventAssessment(is_event=False, notable=True, ticker_hint=["AMAT"])
        assert watchlist_safety_net(ea, {"TSLA", "NVDA"}) is False

    def test_does_not_fire_when_is_event(self):
        # Real catalysts flow through the normal event path, not the safety net.
        ea = EventAssessment(is_event=True, notable=True, ticker_hint=["TSLA"], intensity=2)
        assert watchlist_safety_net(ea, {"TSLA"}) is False

    def test_case_insensitive_match(self):
        ea = EventAssessment(is_event=False, notable=True, ticker_hint=["tsla"])
        assert watchlist_safety_net(ea, {"TSLA"}) is True

    def test_none_assessment(self):
        assert watchlist_safety_net(None, {"TSLA"}) is False

    def test_empty_ticker_hint(self):
        ea = EventAssessment(is_event=False, notable=True, ticker_hint=[])
        assert watchlist_safety_net(ea, {"TSLA"}) is False


class TestTrackedTickers:
    def test_union_of_watchlist_and_portfolio(self, monkeypatch):
        import engine.relevance as rel
        monkeypatch.setattr(rel, "_get_portfolio", lambda: {"AAPL"})
        monkeypatch.setattr(rel, "_get_watchlist", lambda: {"nvda", "TSLA"})
        assert rel.get_tracked_tickers() == {"AAPL", "NVDA", "TSLA"}
