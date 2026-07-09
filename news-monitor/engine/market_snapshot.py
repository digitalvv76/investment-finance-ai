"""Point-in-time market delta since a reference time. Reuses yfinance."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime

import yfinance as yf

logger = logging.getLogger(__name__)

_SPX, _VIX, _BRENT = "^GSPC", "^VIX", "BZ=F"


class MarketSnapshot:
    async def _pct_change_since(self, symbol: str, start: datetime) -> float | None:
        """% change of `symbol` from the close/price at `start` to latest."""
        def _fetch():
            hist = yf.Ticker(symbol).history(period="1d", interval="5m")
            if hist is None or hist.empty:
                return None
            after = hist[hist.index >= start.astimezone(hist.index.tz)] if hist.index.tz else hist
            base = after["Close"].iloc[0] if not after.empty else hist["Close"].iloc[0]
            last = hist["Close"].iloc[-1]
            if not base:
                return None
            return round((last - base) / base * 100, 3)
        try:
            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning("MarketSnapshot %s failed: %s", symbol, e)
            return None

    async def since(self, start_time: datetime) -> dict:
        try:
            spx, vix, brent = await asyncio.gather(
                self._pct_change_since(_SPX, start_time),
                self._pct_change_since(_VIX, start_time),
                self._pct_change_since(_BRENT, start_time),
            )
            return {"spx_pct": spx, "vix_pct": vix, "brent_pct": brent}
        except Exception as e:
            logger.warning("MarketSnapshot.since failed: %s", e)
            return {"spx_pct": None, "vix_pct": None, "brent_pct": None}
