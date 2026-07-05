"""Market data collector — measures actual impact after LLM assessment.

Fetches real price data via yfinance (free, no API key) for assessments
that have been pushed, then computes a normalized actual impact score.

Collection windows: 15m | 1h | 4h (time since the assessment was created).
Results feed back into calibration_state for ongoing threshold tuning.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

from storage.models import ImpactAssessment, ImpactOutcome

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Collection windows — when to measure after push
# ---------------------------------------------------------------------------
_WINDOWS = {
    "15m": timedelta(minutes=15),
    "1h":  timedelta(hours=1),
    "4h":  timedelta(hours=4),
}

# Major indices for breadth measurement
_SPX_SYMBOL = "^GSPC"
_VIX_SYMBOL = "^VIX"

# Sector ETFs mapped in the system (from keywords.yaml / sector ETF mapping)
_SECTOR_ETFS = {
    "Technology":       "XLK",
    "Financials":        "XLF",
    "Energy":           "XLE",
    "Healthcare":       "XLV",
    "Industrials":      "XLI",
    "Consumer Staples": "XLP",
    "Utilities":        "XLU",
    "Consumer Disc":    "XLY",
    "Communication":    "XLC",
    "Real Estate":      "XLRE",
    "Materials":        "XLB",
}

# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class ImpactCollector:
    """Collects actual market impact data after LLM assessment.

    Uses yfinance for price data (free, no API key required).  Falls back
    gracefully when data is unavailable (e.g. weekend, pre-market).
    """

    async def collect(self, assessment: ImpactAssessment,
                      window: str, db) -> Optional[ImpactOutcome]:
        """Collect market data for one assessment at the given window.

        Returns an ImpactOutcome with actual_score computed from post-event
        price movements, or None if data collection failed.
        """
        # Determine which tickers/assets to measure
        tickers = self._parse_tickers(assessment)
        expected_moves = self._parse_expected_moves(assessment)

        try:
            spx_chg, vix_chg = await self._fetch_index_changes(assessment.created_at)
            sector_chgs = await self._fetch_sector_changes(
                assessment.created_at, expected_moves
            )
            ticker_chgs = await self._fetch_ticker_changes(
                tickers, assessment.created_at
            )

            actual_score = self._normalize_score(
                spx_change=spx_chg,
                vix_change=vix_chg,
                sector_changes=sector_chgs,
                ticker_changes=ticker_chgs,
                breadth=assessment.breadth,
            )

            outcome = ImpactOutcome(
                assessment_id=assessment.id,
                collection_window=window,
                spx_change_pct=round(spx_chg, 3),
                vix_change_pct=round(vix_chg, 3),
                sector_changes=json.dumps(sector_chgs, ensure_ascii=False),
                actual_score=actual_score,
            )

            # Persist
            if db:
                db.insert_outcome(outcome)
                # Update calibration state for this event category
                self._update_calibration(db, assessment.event_category, assessment.impact_score, actual_score)

            logger.info(
                "ImpactCollector[%s]: assessment #%s predicted=%s actual=%s (ΔSPX=%.2f%%)",
                window, assessment.id, assessment.impact_score, actual_score, spx_chg,
            )
            return outcome

        except Exception as e:
            logger.warning(
                "ImpactCollector[%s]: failed for assessment #%s: %s",
                window, assessment.id, e,
            )
            return None

    async def collect_pending(self, db, window: str, limit: int = 20) -> int:
        """Fetch market data for all assessments without outcomes for `window`.

        Only collects assessments whose created_at is old enough for the
        window (e.g. "1h" window only collects assessments ≥1h old).

        Returns count of outcomes collected.
        """
        pending = db.get_assessments_without_outcomes(window, limit=limit)
        count = 0

        for row in pending:
            assessment = ImpactAssessment(
                id=row["id"],
                news_id=row.get("news_id", 0),
                impact_score=row.get("impact_score", 0.0),
                confidence=row.get("confidence", 0.0),
                event_category=row.get("event_category", ""),
                breadth=row.get("breadth", ""),
                expected_moves=row.get("expected_moves", "{}"),
                created_at=self._parse_created_at(row.get("created_at", "")),
            )

            # Guard: don't collect if not enough time has passed
            min_age = _WINDOWS.get(window, timedelta(hours=1))
            age = datetime.now() - assessment.created_at
            if age < min_age:
                continue

            outcome = await self.collect(assessment, window, db)
            if outcome:
                count += 1

        if count:
            logger.info("ImpactCollector[%s]: %d outcomes collected", window, count)
        return count

    # ------------------------------------------------------------------
    # Market data fetching (async wrappers around sync yfinance)
    # ------------------------------------------------------------------

    async def _fetch_index_changes(self, since: datetime) -> tuple[float, float]:
        """Fetch SPX and VIX % change since `since`. Returns (spx_pct, vix_pct)."""
        try:
            spx, vix = await asyncio.to_thread(
                self._fetch_multi_change, [_SPX_SYMBOL, _VIX_SYMBOL], since
            )
            return spx, vix
        except Exception:
            return 0.0, 0.0

    async def _fetch_sector_changes(self, since: datetime,
                                     expected_moves: dict) -> dict[str, float]:
        """Fetch % change for sector ETFs, filtered to affected sectors."""
        affected_sectors = set(expected_moves.get("expected_sectors_affected", []))
        if not affected_sectors:
            return {}

        etfs_to_fetch = []
        for sector in affected_sectors:
            etf = _SECTOR_ETFS.get(sector)
            if etf:
                etfs_to_fetch.append(etf)

        if not etfs_to_fetch:
            return {}

        try:
            changes = await asyncio.to_thread(
                self._fetch_multi_change, etfs_to_fetch, since
            )
            return dict(zip(etfs_to_fetch, changes))
        except Exception:
            return {}

    async def _fetch_ticker_changes(self, tickers: list[str],
                                     since: datetime) -> dict[str, float]:
        """Fetch % change for specific tickers mentioned in the news."""
        if not tickers:
            return {}

        # Filter valid tickers (yfinance needs clean symbols)
        valid = [t.upper().strip() for t in tickers if t and t.isalpha() and 1 <= len(t) <= 5]
        if not valid:
            return {}

        try:
            changes = await asyncio.to_thread(
                self._fetch_multi_change, valid, since
            )
            return dict(zip(valid, changes))
        except Exception:
            return {}

    @staticmethod
    def _fetch_multi_change(symbols: list[str], since: datetime) -> list[float]:
        """Fetch % change for multiple symbols since a given time.  Synchronous.

        Downloads daily bars for the range [since, today] and computes
        the % change from the earliest available close to the latest.
        Tries yfinance first, falls back to Alpha Vantage if rate-limited.
        Returns [0.0, ...] on total failure (graceful degradation).
        """
        if not symbols:
            return []

        start = since - timedelta(days=3)  # pad for weekends/holidays
        end = datetime.now() + timedelta(days=1)

        # Try yfinance (free, no key, but rate-limited)
        try:
            data = yf.download(
                symbols, start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False, auto_adjust=True,
            )
            if data is not None and not data.empty:
                return ImpactCollector._extract_changes(data, symbols)
        except Exception:
            pass

        # Fallback: Alpha Vantage (needs API key, 25 calls/day on free tier)
        av_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        if av_key and len(symbols) == 1:
            try:
                import requests
                sym = symbols[0]
                url = (
                    f"https://www.alphavantage.co/query"
                    f"?function=TIME_SERIES_DAILY&symbol={sym}&apikey={av_key}"
                    f"&outputsize=compact"
                )
                resp = requests.get(url, timeout=10)
                data = resp.json()
                ts = data.get("Time Series (Daily)", {})
                if ts:
                    sorted_dates = sorted(ts.keys(), reverse=True)
                    if len(sorted_dates) >= 2:
                        close_today = float(ts[sorted_dates[0]]["4. close"])
                        close_yesterday = float(ts[sorted_dates[1]]["4. close"])
                        if close_yesterday != 0:
                            return [round((close_today - close_yesterday) / close_yesterday * 100, 2)]
            except Exception:
                pass

        return [0.0] * len(symbols)

    @staticmethod
    def _extract_changes(data, symbols: list[str]) -> list[float]:
        """Extract % changes from a yfinance download DataFrame."""
        results = []
        for sym in symbols:
            try:
                if len(symbols) == 1:
                    closes = data["Close"]
                else:
                    closes = data["Close"][sym]
                closes = closes.dropna()
                if len(closes) < 2:
                    results.append(0.0)
                else:
                    start_price = float(closes.iloc[0])
                    end_price = float(closes.iloc[-1])
                    if start_price == 0:
                        results.append(0.0)
                    else:
                        results.append(round((end_price - start_price) / start_price * 100, 2))
            except (KeyError, IndexError, TypeError):
                results.append(0.0)
        return results

    # ------------------------------------------------------------------
    # Score normalization
    # ------------------------------------------------------------------

    def _normalize_score(self, *, spx_change: float, vix_change: float,
                          sector_changes: dict[str, float],
                          ticker_changes: dict[str, float],
                          breadth: str = "") -> float:
        """Compute normalized actual impact score (0–100).

        Weights by breadth (cross_asset > broad_market > sector > single_stock)
        and magnitude of price movement across all affected assets.
        """
        # SPX magnitude (scaled: 3% move = max score)
        spx_mag = min(abs(spx_change) / 3.0, 1.0)

        # VIX magnitude (15 point move = max)
        vix_mag = min(abs(vix_change) / 15.0, 1.0)

        # Sector breadth: how many sectors moved >0.5%
        sectors_moved = sum(1 for chg in sector_changes.values() if abs(chg) > 0.5)
        sector_breadth = min(sectors_moved / 6.0, 1.0)  # 6+ sectors = max

        # Ticker magnitude: average absolute move of mentioned tickers
        if ticker_changes:
            avg_ticker_move = sum(abs(v) for v in ticker_changes.values()) / len(ticker_changes)
            ticker_mag = min(avg_ticker_move / 8.0, 1.0)  # 8% avg move = max
        else:
            ticker_mag = 0.0

        # Breadth multiplier — wider impact = higher ceiling
        breadth_mult = {
            "cross_asset":   1.0,
            "broad_market":  0.85,
            "sector":        0.65,
            "single_stock":  0.45,
        }.get(breadth, 0.7)

        raw = (
            spx_mag * 0.35 +
            vix_mag * 0.20 +
            sector_breadth * 0.20 +
            ticker_mag * 0.25
        ) * 100 * breadth_mult

        return round(min(raw, 100.0), 1)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def _update_calibration(self, db, category: str,
                             predicted: float, actual: float):
        """Update running calibration bias for an event category.

        Positive bias = LLM over-estimates. Negative = under-estimates.
        This feeds into the calibration_hint on future evaluate() calls.
        """
        existing = db.get_calibration(category)
        if existing:
            old = existing[0]
            old_bias = old["bias"]
            old_count = old["sample_count"]
            new_count = old_count + 1
            # Exponential moving average of bias
            alpha = 0.3
            new_bias = round(old_bias * (1 - alpha) + (predicted - actual) * alpha, 2)
        else:
            new_count = 1
            new_bias = round(predicted - actual, 2)

        db.upsert_calibration(category, new_bias, new_count)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_tickers(assessment: ImpactAssessment) -> list[str]:
        """Extract tickers from expected_moves JSON and assessment metadata."""
        tickers = []
        try:
            moves = json.loads(assessment.expected_moves) if assessment.expected_moves else {}
        except (json.JSONDecodeError, TypeError):
            moves = {}
        # expected_moves can have per-ticker entries
        for key in ["equities", "tickers"]:
            val = moves.get(key, "")
            if isinstance(val, str) and val:
                tickers.extend(t.strip() for t in val.split(",") if t.strip())
        return tickers

    @staticmethod
    def _parse_expected_moves(assessment: ImpactAssessment) -> dict:
        try:
            return json.loads(assessment.expected_moves) if assessment.expected_moves else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def _parse_created_at(raw) -> datetime:
        """Parse created_at from various formats."""
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]:
                try:
                    return datetime.strptime(raw.replace("Z", ""), fmt)
                except ValueError:
                    continue
        return datetime.now()
