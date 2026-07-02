"""Tests for sentiment analyzer."""
import pytest
from engine.sentiment import SentimentAnalyzer, Sentiment


@pytest.fixture
def analyzer():
    return SentimentAnalyzer()


class TestSentimentAnalyzer:
    """Sentiment analysis tests."""

    def test_bullish_text(self, analyzer):
        """Clearly positive financial text should return bullish."""
        sentiment, score = analyzer.analyze(
            "NVDA stock surges to all-time high on record earnings beat, "
            "analysts upgrade rating to strong buy"
        )
        assert sentiment == Sentiment.BULLISH
        assert score > 0.15

    def test_bearish_text(self, analyzer):
        """Clearly negative financial text should return bearish."""
        sentiment, score = analyzer.analyze(
            "Market crashes as recession fears mount, stocks plunge "
            "on bankruptcy warnings and mass layoffs"
        )
        assert sentiment == Sentiment.BEARISH
        assert score < -0.15

    def test_neutral_text(self, analyzer):
        """Neutral text should stay in neutral range."""
        sentiment, score = analyzer.analyze(
            "The board meeting is scheduled for Wednesday afternoon "
            "according to the company spokesperson"
        )
        assert sentiment == Sentiment.NEUTRAL
        assert -0.15 <= score <= 0.15

    def test_cautiously_bullish(self, analyzer):
        """Slightly positive text."""
        sentiment, score = analyzer.analyze(
            "Markets edge higher on modest gains in financial sector"
        )
        assert sentiment in (Sentiment.CAUTIOUSLY_BULLISH, Sentiment.BULLISH)

    def test_cautiously_bearish(self, analyzer):
        """Slightly negative text."""
        sentiment, score = analyzer.analyze(
            "Stocks slipped marginally as concerns over slowing growth "
            "weighed on investor sentiment, though losses were limited"
        )
        assert sentiment in (Sentiment.CAUTIOUSLY_BEARISH, Sentiment.BEARISH)

    def test_financial_lexicon_overrides(self, analyzer):
        """Financial terms should be scored correctly by lexicon overrides."""
        # "beat" in "beat earnings" should be bullish
        s1, _ = analyzer.analyze("Company beats earnings expectations by wide margin")
        assert s1 in (Sentiment.BULLISH, Sentiment.CAUTIOUSLY_BULLISH)

        # "downgrade" should be bearish
        s2, _ = analyzer.analyze("Analyst downgrades stock to underperform")
        assert s2 in (Sentiment.BEARISH, Sentiment.CAUTIOUSLY_BEARISH)

    def test_empty_text(self, analyzer):
        """Empty or whitespace text should return neutral."""
        sentiment, score = analyzer.analyze("")
        assert sentiment == Sentiment.NEUTRAL
        assert score == 0.0

        sentiment2, score2 = analyzer.analyze("   ")
        assert sentiment2 == Sentiment.NEUTRAL
        assert score2 == 0.0

    def test_analyze_with_detail(self, analyzer):
        """Detail method should return full score breakdown."""
        result = analyzer.analyze_with_detail(
            "Strong earnings and positive guidance from major tech companies"
        )
        assert 'sentiment' in result
        assert 'compound' in result
        assert 'positive' in result
        assert 'negative' in result
        assert 'neutral' in result
        assert result['positive'] > 0

    def test_mixed_sentiment(self, analyzer):
        """Mixed signals should produce moderate scores."""
        sentiment, score = analyzer.analyze(
            "Tech stocks surge on AI optimism but rising rates spark valuation concerns, "
            "analysts warn of overbought conditions"
        )
        # Should not be extreme in either direction
        assert -0.5 < score < 0.5
