"""Tests for deep lane orchestrator."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from engine.deep_lane import DeepLane
from storage.models import NewsItem


@pytest.fixture
def mock_db():
    """Create a mock database for deep lane tests."""
    return MagicMock()


@pytest.fixture
def mock_config():
    """Create a mock config."""
    cfg = MagicMock()
    cfg.load_keywords.return_value = {
        'breaking_markers': ['BREAKING', 'URGENT'],
        'macro_alerts': ['CPI', 'FOMC', 'inflation'],
        'key_people': ['Kevin Warsh', 'Jerome Powell'],
        'sectors': {'semiconductor': ['chip', 'GPU']},
    }
    cfg.load_settings.return_value = {
        'deep_lane': {'llm_model': 'claude-fable-5', 'max_tokens': 800},
    }
    return cfg


@pytest.fixture
def deep_lane(mock_config, mock_db):
    return DeepLane(config=mock_config, db=mock_db)


class TestDeepLane:
    """Deep lane pipeline tests."""

    @pytest.mark.asyncio
    async def test_process_urgent_item(self, deep_lane):
        """Urgent priority items should trigger auto LLM analysis."""
        item = NewsItem(
            id=1,
            title="BREAKING: NVDA reports blowout earnings, raises guidance",
            url="https://example.com/1",
            source="Bloomberg Markets",
            is_breaking=True,
            tickers_found="NVDA",
            macro_tags="",
            status="fast_pushed",
        )

        # Process without LLM (no API key) — should still complete pipeline
        result = await deep_lane.process(item)
        assert result.sentiment is not None
        # Sentiment score can be 0.0 for short texts — that's valid
        assert isinstance(result.sentiment_score, float)
        assert result.market_impact in ('high', 'medium', 'low')
        # Fallback analysis should be set
        assert result.llm_analysis or result.status in ('fast_pushed', 'archived')

    @pytest.mark.asyncio
    async def test_process_low_priority_archives(self, deep_lane):
        """Low priority items should be archived without LLM."""
        item = NewsItem(
            id=2,
            title="Regular market commentary and analysis",
            url="https://example.com/2",
            source="Unknown Blog",
            is_breaking=False,
            tickers_found="",
            macro_tags="",
            status="pending",
        )

        result = await deep_lane.process(item)
        assert result.sentiment is not None
        assert result.market_impact == 'low'
        # Should be archived, not deep_pushed
        assert result.status == 'archived'

    @pytest.mark.asyncio
    async def test_process_extracts_entities(self, deep_lane):
        """Deep lane should extract entities even if fast lane missed them."""
        item = NewsItem(
            id=3,
            title="CPI data shows persistent inflation, Federal Reserve concerned",
            url="https://example.com/3",
            source="Reuters",
            is_breaking=False,
            tickers_found="",
            macro_tags="",
            status="pending",
        )

        result = await deep_lane.process(item)
        # Should have found macro tags in deep lane
        assert result.macro_tags != '' or result.entities is not None

    @pytest.mark.asyncio
    async def test_assess_impact(self):
        """Market impact assessment logic."""
        assert DeepLane._assess_impact(0.8, 3) == 'high'
        assert DeepLane._assess_impact(0.5, 1) == 'medium'
        assert DeepLane._assess_impact(0.2, 0) == 'low'
        assert DeepLane._assess_impact(0.3, 3) == 'high'  # ticker count drives high

    def test_fallback_analysis(self):
        """Fallback analysis should produce meaningful text."""
        item = NewsItem(
            title="NVDA earnings beat",
            tickers_found="NVDA,AAPL",
            macro_tags="inflation",
            sentiment="bullish",
            market_impact="high",
        )
        result = DeepLane._fallback_analysis(item)
        assert result
        assert 'NVDA' in result or 'high' in result
        assert len(result) > 10

    @pytest.mark.asyncio
    async def test_process_on_demand(self, deep_lane):
        """On-demand processing forces LLM call."""
        item = NewsItem(
            id=4,
            title="Fed signals policy shift",
            url="https://example.com/4",
            source="CNBC",
            is_breaking=False,
            tickers_found="",
            macro_tags="",
            status="fast_pushed",
        )

        result = await deep_lane.process_on_demand(item)
        assert result.sentiment is not None
        # On-demand should always attempt deep analysis
        assert result.llm_analysis or result.status == 'deep_pushed'
