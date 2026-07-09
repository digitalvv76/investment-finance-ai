# tests/test_market_snapshot.py
import pytest
from datetime import datetime, timedelta
from engine.market_snapshot import MarketSnapshot

@pytest.mark.asyncio
async def test_since_returns_pct_dict(monkeypatch):
    ms = MarketSnapshot()
    async def fake_change(symbol, start):
        return {"^GSPC": -0.45, "^VIX": 16.6, "BZ=F": 5.9}[symbol]
    monkeypatch.setattr(ms, "_pct_change_since", fake_change)
    out = await ms.since(datetime.now() - timedelta(hours=1))
    assert out["spx_pct"] == -0.45
    assert out["vix_pct"] == 16.6
    assert out["brent_pct"] == 5.9

@pytest.mark.asyncio
async def test_since_handles_fetch_failure(monkeypatch):
    ms = MarketSnapshot()
    async def boom(symbol, start):
        raise RuntimeError("yfinance down")
    monkeypatch.setattr(ms, "_pct_change_since", boom)
    out = await ms.since(datetime.now())
    assert out == {"spx_pct": None, "vix_pct": None, "brent_pct": None}
