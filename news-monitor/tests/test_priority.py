"""Tests for priority scorer."""
import pytest
from engine.priority import PriorityScorer, URGENT_THRESHOLD, IMPORTANT_THRESHOLD, FAST_LANE_THRESHOLD
from storage.models import NewsItem


@pytest.fixture
def scorer():
    return PriorityScorer()


class TestPriorityScorer:
    """Priority scoring tests."""

    def test_breaking_only(self, scorer):
        """Breaking news without other signals should get breaking weight."""
        item = NewsItem(
            title="BREAKING: Market update",
            url="https://example.com/1",
            source="Bloomberg",
            is_breaking=True,
        )
        score = scorer.score(item, tickers=set(), macro_tags=set())
        assert score >= 0.40  # breaking (0.40) + source authority
        assert scorer.classify(score) == "important"

    def test_ticker_hits_increase_score(self, scorer):
        """More tickers = higher score."""
        score1 = scorer.score(
            NewsItem(title="NVDA up", url="x", source="Test"),
            tickers={"NVDA"},
        )
        score2 = scorer.score(
            NewsItem(title="NVDA AAPL MSFT rally", url="x2", source="Test"),
            tickers={"NVDA", "AAPL", "MSFT"},
        )
        assert score2 > score1

    def test_macro_tags_increase_score(self, scorer):
        """Macro tags should boost score."""
        score_no_macro = scorer.score(
            NewsItem(title="Market update", url="x", source="Test"),
        )
        score_macro = scorer.score(
            NewsItem(title="CPI data released", url="x2", source="Test"),
            macro_tags={"CPI", "inflation", "Federal Reserve"},
        )
        assert score_macro > score_no_macro

    def test_key_people_bonus(self, scorer):
        """Key people mentions add score."""
        score_without = scorer.score(
            NewsItem(title="Fed policy update", url="x", source="Test"),
        )
        score_with = scorer.score(
            NewsItem(title="Fed policy update", url="x2", source="Test"),
            has_people=True,
        )
        assert score_with > score_without

    def test_source_authority(self, scorer):
        """Bloomberg should score higher than a blog."""
        score_bloomberg = scorer.score(
            NewsItem(title="Market update", url="x1", source="Bloomberg Markets"),
        )
        score_unknown = scorer.score(
            NewsItem(title="Market update", url="x2", source="Random Blog"),
        )
        assert score_bloomberg > score_unknown

    def test_resonance_bonus(self, scorer):
        """Multiple similar articles should boost score."""
        score_single = scorer.score(
            NewsItem(title="Event", url="x", source="Test"),
        )
        score_resonance = scorer.score(
            NewsItem(title="Event", url="x2", source="Test"),
            similar_count=3,
        )
        assert score_resonance > score_single

    def test_urgent_classification(self, scorer):
        """All signals combined should reach urgent."""
        score = scorer.score(
            NewsItem(
                title="BREAKING: Fed emergency meeting",
                url="x",
                source="Bloomberg Markets",
                is_breaking=True,
            ),
            tickers={"NVDA", "AAPL", "MSFT"},
            macro_tags={"FOMC", "Federal Reserve", "rate hike", "inflation"},
            has_people=True,
            similar_count=4,
        )
        assert score >= URGENT_THRESHOLD
        assert scorer.classify(score) == "urgent"

    def test_no_signals_low_score(self, scorer):
        """Article with no signals should score near zero."""
        score = scorer.score(
            NewsItem(title="General market commentary", url="x", source="Unknown Blog"),
        )
        assert score < IMPORTANT_THRESHOLD

    def test_score_batch(self, scorer):
        """Batch scoring should tag items correctly."""
        items = [
            NewsItem(title="BREAKING: NVDA crash", url="x1", source="Bloomberg", is_breaking=True),
            NewsItem(title="Local news", url="x2", source="Local Paper"),
        ]
        pushed = scorer.score_batch(
            items,
            tickers_map={id(items[0]): {"NVDA"}},
        )
        assert len(pushed) == 1
        assert pushed[0].priority_score >= FAST_LANE_THRESHOLD
        assert pushed[0].status == 'fast_pushed'
