"""Self-learning calibration engine for Impact Evaluator."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

CATEGORIES = ["monetary", "geopolitical", "macro_data", "corporate", "regulatory"]


class ImpactLearner:
    MIN_SAMPLES = 5
    MAX_ADJUST = 5.0
    BIAS_THRESHOLD = 2.0  # ignore bias below this

    def analyze_deviation(self, category: str, db) -> float:
        """Return mean bias for a category (positive = over-estimate)."""
        samples = db.get_outcomes_for_category(category, limit=20)
        if len(samples) < self.MIN_SAMPLES:
            return 0.0
        biases = [
            s["predicted_score"] - s["actual_score"]
            for s in samples
            if (s.get("actual_score") is not None
                and s.get("actual_score", 0) >= 0)  # skip sentinel -1.0 (not yet collected)
        ]
        if not biases:
            return 0.0
        bias = sum(biases) / len(biases)
        return max(-self.MAX_ADJUST, min(self.MAX_ADJUST, bias))

    def generate_calibration_hint(self, db) -> str:
        """Build calibration text for injection into LLM prompt."""
        hints = {}
        for cat in CATEGORIES:
            hints[cat] = self.analyze_deviation(cat, db)
        return self._build_hint(hints)

    def _build_hint(self, hints: dict[str, float]) -> str:
        filtered = {
            cat: bias for cat, bias in hints.items()
            if abs(bias) >= self.BIAS_THRESHOLD
        }
        if not filtered:
            return "No calibration data yet"
        parts = []
        for cat, bias in filtered.items():
            direction = "over-estimate" if bias > 0 else "under-estimate"
            parts.append(
                f"Tend to {direction} {cat} events by ~{abs(bias):.0f} points"
            )
        return "; ".join(parts) if parts else "No calibration data yet"

    def update_calibration(self, db):
        """Persist calibration state for all categories."""
        for cat in CATEGORIES:
            bias = self.analyze_deviation(cat, db)
            samples = db.get_outcomes_for_category(cat, limit=20)
            db.upsert_calibration(cat, bias, len(samples))
