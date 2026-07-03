"""Market data collector — measures actual impact after LLM assessment."""

import logging
from typing import Optional

from storage.models import ImpactAssessment, ImpactOutcome

logger = logging.getLogger(__name__)


class ImpactCollector:
    async def collect(self, assessment: ImpactAssessment,
                      window: str, db) -> Optional[ImpactOutcome]:
        """Collect market data for one assessment at the given window.

        In production, this calls yfinance / stock-scanner MCP tools.
        For the MVP, the outcome is populated by a scheduled task that
        queries market data APIs directly.
        """
        # This method is the interface. Actual data fetching happens in
        # the scheduled task (see collect_pending_outcomes below).
        outcome = ImpactOutcome(
            assessment_id=assessment.id,
            collection_window=window,
        )
        return outcome

    async def collect_pending(self, db, window: str) -> int:
        """Fetch market data for all assessments without outcomes for `window`.

        Returns count of outcomes created.
        """
        pending = db.get_assessments_without_outcomes(window, limit=20)
        count = 0
        for row in pending:
            # In production: call yfinance/stock-scanner here.
            # For MVP, write placeholder — actual data comes from
            # the scheduled task in main.py.
            pass
        return count

    def _normalize_score(self, *, spx_change: float, vix_change: float,
                          sector_count: int, bonds_moved: bool,
                          fx_moved: bool, commodities_moved: bool) -> float:
        """Compute normalized actual impact score (0-100)."""
        spx_val = min(abs(spx_change) / 3.0, 1.0) * 100
        vix_val = min(abs(vix_change) / 15.0, 1.0) * 100
        sector_val = (sector_count / 11.0) * 100
        cross_count = sum([bonds_moved, fx_moved, commodities_moved])
        cross_val = (cross_count / 3.0) * 100

        return round(
            spx_val * 0.40 + vix_val * 0.25 +
            sector_val * 0.20 + cross_val * 0.15, 1
        )
