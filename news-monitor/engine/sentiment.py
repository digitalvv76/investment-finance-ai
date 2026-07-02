"""Sentiment analysis using VADER + financial lexicon overrides."""
import logging
from enum import Enum
from typing import Tuple

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)


class Sentiment(Enum):
    BULLISH = "bullish"
    CAUTIOUSLY_BULLISH = "cautiously_bullish"
    NEUTRAL = "neutral"
    CAUTIOUSLY_BEARISH = "cautiously_bearish"
    BEARISH = "bearish"


# ---------------------------------------------------------------------------
# Financial lexicon — overrides VADER defaults for domain-specific terms.
# Positive values = bullish, negative = bearish.
# ---------------------------------------------------------------------------
FINANCIAL_LEXICON: dict[str, float] = {
    # Bullish terms
    "surge": 2.5,
    "surged": 2.5,
    "surges": 2.5,
    "soar": 2.5,
    "soared": 2.5,
    "soars": 2.5,
    "rally": 2.0,
    "rallied": 2.0,
    "rallies": 2.0,
    "bullish": 2.5,
    "outperform": 1.5,
    "outperformed": 1.5,
    "beat": 1.5,
    "beats": 1.5,
    "upgrade": 1.5,
    "upgraded": 1.5,
    "upgrades": 1.5,
    "breakout": 2.0,
    "breakthrough": 2.0,
    "oversold": 1.5,
    "dip": -1.0,
    "dips": -1.0,
    "dipped": -1.0,
    # Bearish terms
    "plunge": -2.5,
    "plunged": -2.5,
    "plunges": -2.5,
    "crash": -3.0,
    "crashed": -3.0,
    "crashes": -3.0,
    "tumble": -2.0,
    "tumbled": -2.0,
    "tumbles": -2.0,
    "slump": -2.0,
    "slumped": -2.0,
    "slumps": -2.0,
    "bearish": -2.5,
    "downgrade": -1.5,
    "downgraded": -1.5,
    "downgrades": -1.5,
    "underperform": -1.5,
    "sell-off": -2.5,
    "selloff": -2.5,
    "sell off": -2.5,
    "overbought": -1.5,
    "recession": -2.0,
    "layoff": -1.5,
    "layoffs": -1.5,
    "default": -2.5,
    "defaults": -2.5,
    "bankruptcy": -3.0,
    "delist": -2.5,
    "delisted": -2.5,
    "warning": -1.0,
    "warns": -1.0,
    "warned": -1.0,
    "miss": -1.0,
    "missed": -1.0,
    "misses": -1.0,
    "cut": -1.0,
    "cuts": -1.0,
    "suspend": -1.5,
    "suspended": -1.5,
    "probe": -1.0,
    "investigation": -1.0,
    "fine": -1.0,
    "fined": -1.0,
    "lawsuit": -1.5,
    "sanction": -1.5,
    "sanctions": -1.5,
    "tariff": -1.0,
    "tariffs": -1.0,
    # Mixed/context-dependent — neutral override
    "volatile": -0.5,
    "volatility": -0.5,
    "swing": 0.0,
    "swings": 0.0,
}

# Score thresholds for sentiment classification
BULLISH_THRESHOLD = 0.15
CAUTIOUSLY_BULLISH_THRESHOLD = 0.05
CAUTIOUSLY_BEARISH_THRESHOLD = -0.05
BEARISH_THRESHOLD = -0.15


class SentimentAnalyzer:
    """Analyze sentiment of financial text.

    Uses VADER as the base sentiment engine, then applies a domain-specific
    financial lexicon to adjust scores for terms that VADER misinterprets
    in financial contexts (e.g., "beat" is neutral to VADER but bullish
    in earnings context).
    """

    def __init__(self):
        self._vader = SentimentIntensityAnalyzer()
        # Patch the VADER lexicon with our financial overrides
        self._vader.lexicon.update(FINANCIAL_LEXICON)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, text: str) -> Tuple[Sentiment, float]:
        """Analyze sentiment of text.

        Args:
            text: The news title + snippet to analyze.

        Returns:
            Tuple of (Sentiment enum, compound score in [-1.0, 1.0]).
        """
        if not text or not text.strip():
            return Sentiment.NEUTRAL, 0.0

        scores = self._vader.polarity_scores(text)
        compound = scores["compound"]

        sentiment = self._score_to_sentiment(compound)
        logger.debug(
            "Sentiment: %s (compound=%.3f, pos=%.3f, neg=%.3f, neu=%.3f)",
            sentiment.value, compound,
            scores["pos"], scores["neg"], scores["neu"],
        )
        return sentiment, compound

    def analyze_with_detail(self, text: str) -> dict:
        """Analyze and return full detail including component scores.

        Returns:
            {
                "sentiment": "bullish",
                "compound": 0.45,
                "positive": 0.30,
                "negative": 0.05,
                "neutral": 0.65,
            }
        """
        sentiment, compound = self.analyze(text)
        scores = self._vader.polarity_scores(text)
        return {
            "sentiment": sentiment.value,
            "compound": compound,
            "positive": scores["pos"],
            "negative": scores["neg"],
            "neutral": scores["neu"],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _score_to_sentiment(compound: float) -> Sentiment:
        """Map compound score to Sentiment enum."""
        if compound >= BULLISH_THRESHOLD:
            return Sentiment.BULLISH
        elif compound >= CAUTIOUSLY_BULLISH_THRESHOLD:
            return Sentiment.CAUTIOUSLY_BULLISH
        elif compound > BEARISH_THRESHOLD:
            return Sentiment.NEUTRAL
        elif compound >= CAUTIOUSLY_BEARISH_THRESHOLD:
            return Sentiment.CAUTIOUSLY_BEARISH
        else:
            return Sentiment.BEARISH
