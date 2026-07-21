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

    def test_business_impact_price_english(self, scorer):
        """Price increase language should boost score."""
        score = scorer.score(
            NewsItem(
                title="Exclusive: TSMC to raise chipmaking prices by up to 10% from 2027",
                url="x", source="Nikkei Asia",
            ),
        )
        # business_impact: regex match → intensity 0.9 → 0.9*0.15=0.135
        assert score >= 0.10

    def test_business_impact_price_chinese(self, scorer):
        """Chinese 涨价 should boost score."""
        score = scorer.score(
            NewsItem(
                title="台积电计划从2027年起将芯片制造价格提高至多10%",
                url="x", source="新浪财经·7x24综合快讯",
            ),
        )
        assert score >= 0.02

    def test_business_impact_price_explicit(self, scorer):
        """Explicit 全面涨价 keyword should give strong boost."""
        score = scorer.score(
            NewsItem(
                title="台积电宣布3nm制程全面涨价20%",
                url="x", source="新浪财经·7x24综合快讯",
            ),
        )
        assert score >= 0.15

    def test_business_impact_no_signal(self, scorer):
        """Headlines without business impact should not get boost."""
        score = scorer.score(
            NewsItem(
                title="TSMC reports strong quarterly earnings, beats expectations",
                url="x", source="Reuters",
            ),
        )
        assert score >= 0.05  # source authority alone

    def test_business_impact_max_not_sum(self, scorer):
        """Multiple keywords should take max, not sum."""
        score1 = scorer.score(
            NewsItem(title="price hike price increase", url="x", source="Test"),
        )
        score2 = scorer.score(
            NewsItem(title="price hike", url="x", source="Test"),
        )
        assert score1 == score2

    def test_business_impact_guidance_raise(self, scorer):
        """Guidance raise should get business_impact boost."""
        score = scorer.score(
            NewsItem(
                title="NVDA raises guidance on strong AI chip demand",
                url="x", source="CNBC",
            ),
        )
        # "raises guidance" → 0.8 × 0.15 = 0.12
        assert score >= 0.15

    def test_business_impact_record_revenue(self, scorer):
        """Record revenue should get strong boost."""
        score = scorer.score(
            NewsItem(
                title="Apple reports record revenue of $98 billion in Q3",
                url="x", source="Reuters",
            ),
        )
        # "record revenue" → 0.9 × 0.15 = 0.135
        assert score >= 0.15

    def test_business_impact_major_deal(self, scorer):
        """Billion dollar deal should get strong boost."""
        score = scorer.score(
            NewsItem(
                title="Rocket Lab wins billion dollar contract from Space Force",
                url="x", source="Bloomberg",
            ),
        )
        # "billion dollar contract" → 0.9 × 0.15 = 0.135
        assert score >= 0.20

    def test_score_batch(self, scorer):
        """Batch scoring should tag items correctly."""
        items = [
            NewsItem(title="BREAKING: NVDA crash", url="x1", source="Bloomberg", is_breaking=True),
            NewsItem(title="Local news", url="x2", source="Local Paper"),
        ]
        pushed = scorer.score_batch(
            items,
            tickers_map={0: {"NVDA"}},  # key=index (items have no DB id yet)
        )
        assert len(pushed) == 1
        assert pushed[0].priority_score >= FAST_LANE_THRESHOLD
        assert pushed[0].status == 'fast_pushed'
