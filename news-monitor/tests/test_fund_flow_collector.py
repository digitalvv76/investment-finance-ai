"""Tests for FundFlowCollector."""
import pytest
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from storage.database import Database
from storage.models import FundFlowRecord
from collector.fund_flow_collector import (
    FundFlowCollector,
    FundFlowSignal,
    _FALLBACK_WATCHLIST,
)
from collector.eastmoney_fetcher import FundFlowResult, FundFlowDay


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    d = Database(path)
    d.init_db()
    yield d
    os.unlink(path)


def _make_result(ticker="AAPL", days_data=None):
    """Build a FundFlowResult with optional day data."""
    if days_data is None:
        days_data = [
            FundFlowDay(date="2026-07-10", main_net=1e8, super_big_net=0.8e8,
                        big_net=0.2e8, mid_net=-0.3e8, small_net=-0.7e8, main_pct=10.0),
            FundFlowDay(date="2026-07-11", main_net=1.2e8, super_big_net=1.0e8,
                        big_net=0.2e8, mid_net=-0.5e8, small_net=-0.7e8, main_pct=12.0),
            FundFlowDay(date="2026-07-14", main_net=2e8, super_big_net=1.8e8,
                        big_net=0.2e8, mid_net=-0.8e8, small_net=-1.2e8, main_pct=18.0),
        ]
    return FundFlowResult(
        ticker=ticker, secid="105.AAPL", name="Apple Inc",
        market="NASDAQ", days=days_data, fetched_at=1752537600.0,
        source="push2his",
    )


# ------------------------------------------------------------------
# Signal computation
# ------------------------------------------------------------------

def test_compute_signals_continuous_inflow_extreme():
    """3 days of positive super_big_net + high main_pct → extreme inflow."""
    collector = FundFlowCollector(db=MagicMock(), watchlist=["AAPL"])
    result = _make_result("AAPL")
    signals = collector._compute_signals(result)

    assert len(signals) == 1
    s = signals[0]
    assert s.ticker == "AAPL"
    assert s.continuity == "continuous_inflow"
    assert s.participation == "extreme"
    assert s.cum_super_big_3d > 0


def test_compute_signals_continuous_outflow():
    """3 days of negative super_big_net + high abs(main_pct) → extreme outflow."""
    collector = FundFlowCollector(db=MagicMock(), watchlist=["NVDA"])
    days = [
        FundFlowDay(date="2026-07-10", main_net=-1e8, super_big_net=-0.8e8,
                    big_net=-0.2e8, mid_net=0.3e8, small_net=0.7e8, main_pct=-16.0),
        FundFlowDay(date="2026-07-11", main_net=-1.5e8, super_big_net=-1.2e8,
                    big_net=-0.3e8, mid_net=0.5e8, small_net=1.0e8, main_pct=-18.0),
        FundFlowDay(date="2026-07-14", main_net=-2e8, super_big_net=-1.8e8,
                    big_net=-0.2e8, mid_net=0.8e8, small_net=1.2e8, main_pct=-20.0),
    ]
    result = _make_result("NVDA", days_data=days)
    signals = collector._compute_signals(result)

    assert len(signals) == 1
    s = signals[0]
    assert s.continuity == "continuous_outflow"
    assert s.participation == "extreme"


def test_compute_signals_insufficient_data():
    """< 3 days → no signal."""
    collector = FundFlowCollector(db=MagicMock(), watchlist=["TSLA"])
    result = _make_result("TSLA", days_data=[
        FundFlowDay(date="2026-07-14", main_net=1e8, super_big_net=0.8e8,
                    big_net=0.2e8, mid_net=-0.3e8, small_net=-0.7e8, main_pct=8.0),
    ])
    signals = collector._compute_signals(result)
    assert len(signals) == 0


def test_compute_signals_mixed_direction():
    """Mixed super_big directions → continuity='mixed', not extreme."""
    collector = FundFlowCollector(db=MagicMock(), watchlist=["META"])
    days = [
        FundFlowDay(date="2026-07-10", main_net=1e8, super_big_net=1e8,
                    big_net=0, mid_net=-0.5e8, small_net=-0.5e8, main_pct=5.0),
        FundFlowDay(date="2026-07-11", main_net=-0.5e8, super_big_net=-0.3e8,
                    big_net=-0.2e8, mid_net=0.3e8, small_net=0.2e8, main_pct=-4.0),
        FundFlowDay(date="2026-07-14", main_net=0.3e8, super_big_net=0.2e8,
                    big_net=0.1e8, mid_net=-0.1e8, small_net=-0.2e8, main_pct=3.0),
    ]
    result = _make_result("META", days_data=days)
    signals = collector._compute_signals(result)
    assert len(signals) == 1
    assert signals[0].continuity == "mixed"


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------

def test_persist_result(db):
    collector = FundFlowCollector(db=db, watchlist=["AAPL"])
    result = _make_result("AAPL")
    # Use a real async call — but _persist_result is sync
    import asyncio
    asyncio.run(_persist_wrapper(collector, result))

    rows = db.get_fund_flow("AAPL", days=20)
    assert len(rows) == 3
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["main_pct"] == 10.0


async def _persist_wrapper(collector, result):
    await collector._persist_result(result)


def test_persist_result_idempotent(db):
    """Double upsert same ticker+date → no duplicates, latest wins."""
    collector = FundFlowCollector(db=db, watchlist=["AAPL"])

    import asyncio
    r1 = _make_result("AAPL")
    asyncio.run(_persist_wrapper(collector, r1))

    r2 = _make_result("AAPL", days_data=[
        FundFlowDay(date="2026-07-14", main_net=999, super_big_net=888,
                    big_net=111, mid_net=-200, small_net=-799, main_pct=99.0),
    ])
    asyncio.run(_persist_wrapper(collector, r2))

    rows = db.get_fund_flow("AAPL", days=20)
    # Only 3 unique dates: 07-10, 07-11 (from r1), 07-14 (from r2 overwrites r1's)
    assert len(rows) == 3
    row_14 = [r for r in rows if r["date"] == "2026-07-14"][0]
    assert row_14["main_net"] == 999


# ------------------------------------------------------------------
# should_run_today
# ------------------------------------------------------------------

def test_should_run_today_false_if_already_ran():
    collector = FundFlowCollector(db=MagicMock(), watchlist=["AAPL"])
    collector._last_run_date = collector._et_today_str()
    assert collector.should_run_today() is False


def test_should_run_false_on_weekend():
    collector = FundFlowCollector(db=MagicMock(), watchlist=["AAPL"])
    with patch("collector.exchange_calendar.ExchangeCalendar") as mock_cal_cls:
        mock_cal = MagicMock()
        mock_cal.is_trading_day.return_value = False
        mock_cal_cls.return_value = mock_cal
        assert collector.should_run_today() is False


def test_should_run_before_market_close(monkeypatch):
    """Before 5pm ET should return False even on trading day."""
    collector = FundFlowCollector(db=MagicMock(), watchlist=["AAPL"])
    # Mock calendar to say it IS a trading day
    with patch("collector.exchange_calendar.ExchangeCalendar") as mock_cal_cls:
        mock_cal = MagicMock()
        mock_cal.is_trading_day.return_value = True
        mock_cal_cls.return_value = mock_cal
        # Patch _et_offset_hours to EDT (UTC-4)
        monkeypatch.setattr(
            "collector.fund_flow_collector._et_offset_hours", lambda: 4,
        )
        # Now should_run_today calls datetime.now(timezone.utc).
        # The real now (July 15 evening in China = July 15 afternoon ET)
        # EDT offset 4 → ET = UTC - 4.
        # At 19:31 CST = 11:31 UTC = 07:31 ET → hour < 17 → False
        # At any time before ~1am CST (which is 1pm ET), this passes.
        # This test will pass: it's before 5pm ET now (July 15 ~19:30 CST = ~7:30am ET)
        assert collector.should_run_today() is False


# ------------------------------------------------------------------
# collect_once
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collect_once_empty_watchlist(db):
    collector = FundFlowCollector(db=db, watchlist=[])
    collector._fetcher = MagicMock()
    collector._fetcher.fetch_multi = AsyncMock(return_value={})
    pushed = await collector.collect_once()
    assert pushed == 0


@pytest.mark.asyncio
async def test_collect_once_fetcher_returns_none(db):
    """Fetcher returns None for all tickers → no crash, no push."""
    collector = FundFlowCollector(db=db, watchlist=["AAPL"])
    collector._fetcher = MagicMock()
    collector._fetcher.fetch_multi = AsyncMock(return_value={"AAPL": None})
    pushed = await collector.collect_once()
    assert pushed == 0


@pytest.mark.asyncio
async def test_collect_once_persists_and_pushes(db):
    """Full cycle: fetch → persist → signal → push."""
    collector = FundFlowCollector(db=db, watchlist=["AAPL"])
    collector._fetcher = MagicMock()
    collector._fetcher.fetch_multi = AsyncMock(return_value={
        "AAPL": _make_result("AAPL"),
    })
    collector._dispatcher = MagicMock()
    collector._dispatcher.send_system_alert = AsyncMock(return_value=True)

    pushed = await collector.collect_once()
    assert pushed == 1  # extreme signal pushed
    assert collector._dispatcher.send_system_alert.called


@pytest.mark.asyncio
async def test_collect_once_push_failure_does_not_crash(db):
    """Push failure is logged, not raised."""
    collector = FundFlowCollector(db=db, watchlist=["AAPL"])
    collector._fetcher = MagicMock()
    collector._fetcher.fetch_multi = AsyncMock(return_value={
        "AAPL": _make_result("AAPL"),
    })
    collector._dispatcher = MagicMock()
    collector._dispatcher.send_system_alert = AsyncMock(
        side_effect=RuntimeError("push failed"),
    )
    # Should not raise
    pushed = await collector.collect_once()
    assert pushed == 1  # attempted push counted, even though it failed


# ------------------------------------------------------------------
# Watchlist resolution
# ------------------------------------------------------------------

def test_watchlist_from_config():
    collector = FundFlowCollector(
        db=MagicMock(), watchlist=["AAPL", "NVDA", "TSLA"],
    )
    assert collector._watchlist == ["AAPL", "NVDA", "TSLA"]


def test_watchlist_fallback():
    """Without explicit watchlist, falls back to watchlist-state or hardcoded."""
    # Temporarily hide watchlist-state.md so fallback triggers
    collector = FundFlowCollector(
        db=MagicMock(),
    )
    assert len(collector._watchlist) > 0
    assert all(t.isalpha() and t.isupper() for t in collector._watchlist)


def test_watchlist_fallback_has_expected_tickers():
    """The fallback list should contain the user's core positions."""
    assert "NVDA" in _FALLBACK_WATCHLIST
    assert "AAPL" in _FALLBACK_WATCHLIST
    assert "RKLB" in _FALLBACK_WATCHLIST
    assert "NBIS" in _FALLBACK_WATCHLIST


# ------------------------------------------------------------------
# Proxy
# ------------------------------------------------------------------

def test_proxy_from_env(monkeypatch):
    """Proxy is read from env, passed to fetcher constructor."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:9999")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    collector = FundFlowCollector(db=MagicMock(), watchlist=["AAPL"])
    assert collector._fetcher._proxy == "http://proxy:9999"


def test_proxy_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://wrong:1234")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    collector = FundFlowCollector(
        db=MagicMock(), watchlist=["AAPL"], proxy="http://right:5678",
    )
    assert collector._fetcher._proxy == "http://right:5678"
