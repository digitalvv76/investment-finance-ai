"""Tests for watchlist_safety_net pure function (SPEC-safety-net-pipeline.md §6).

Non-event news with a NOTABLE action on a tracked ticker → rescue to silent TG.
"""

import pytest

from engine.event_driven_evaluator import EventAssessment, watchlist_safety_net

TRACKED = {"TSLA", "NVDA", "AAPL"}


def _ea(is_event=False, notable=True, ticker_hint=None):
    return EventAssessment(
        is_event=is_event, notable=notable,
        ticker_hint=ticker_hint if ticker_hint is not None else ["TSLA"],
    )


def test_hit_notable_on_tracked_ticker():
    assert watchlist_safety_net(_ea(), TRACKED) is True


def test_not_notable_passing_mention():
    assert watchlist_safety_net(_ea(notable=False), TRACKED) is False


def test_ticker_not_tracked():
    assert watchlist_safety_net(_ea(ticker_hint=["SOUN"]), TRACKED) is False


def test_is_event_true_goes_normal_path_not_safety_net():
    # A real event routes through the event path, never the safety net.
    assert watchlist_safety_net(_ea(is_event=True), TRACKED) is False


def test_ticker_case_insensitive():
    assert watchlist_safety_net(_ea(ticker_hint=["tsla"]), TRACKED) is True


def test_none_assessment():
    assert watchlist_safety_net(None, TRACKED) is False


def test_empty_ticker_hint():
    assert watchlist_safety_net(_ea(ticker_hint=[]), TRACKED) is False


def test_whitespace_ticker_ignored():
    assert watchlist_safety_net(_ea(ticker_hint=["  ", "NVDA"]), TRACKED) is True


def test_get_tracked_tickers_uppercased_union():
    from engine.relevance import get_tracked_tickers
    tracked = get_tracked_tickers()
    assert all(t == t.upper() for t in tracked)   # all uppercase
    assert isinstance(tracked, set)
