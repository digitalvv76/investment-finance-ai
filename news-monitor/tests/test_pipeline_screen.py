"""Tests for ScreenStage."""
import pytest
from unittest.mock import MagicMock, patch
from pipeline.screen import ScreenStage
from pipeline.item import PipelineItem, DispatchDecision


@pytest.fixture
def mock_fast_lane():
    fl = MagicMock()
    fl.process = MagicMock(return_value=[])
    return fl


@pytest.fixture
def stage(mock_fast_lane):
    return ScreenStage(fast_lane=mock_fast_lane)


class TestScreenStage:

    @pytest.mark.asyncio
    async def test_happy_path(self, stage, mock_fast_lane):
        """Items with priority >= 0.3 pass through."""
        from datetime import datetime
        from storage.models import NewsItem

        items = [
            PipelineItem(id=1, title="Big news", source="CNBC", url="http://x.com/1"),
        ]
        enriched = [
            NewsItem(
                id=1, title="Big news", source="CNBC", url="http://x.com/1",
                priority_score=0.75, tickers_found="AAPL,MSFT",
                macro_tags="fed", is_breaking=True,
            )
        ]
        mock_fast_lane.process.return_value = enriched

        result = await stage.process(items)

        assert len(result) == 1
        assert result[0].priority_score == 0.75
        assert result[0].tickers_found == "AAPL,MSFT"
        assert result[0].is_breaking is True

    @pytest.mark.asyncio
    async def test_below_threshold_filtered(self, stage, mock_fast_lane):
        """Items with priority < 0.3 are dropped."""
        from datetime import datetime
        from storage.models import NewsItem

        items = [PipelineItem(id=1, title="Meh", source="blog", url="http://x.com/1")]
        enriched = [
            NewsItem(
                id=1, title="Meh", source="blog", url="http://x.com/1",
                priority_score=0.15, tickers_found="",
            )
        ]
        mock_fast_lane.process.return_value = enriched

        result = await stage.process(items)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_empty_input(self, stage):
        result = await stage.process([])
        assert result == []

    @pytest.mark.asyncio
    async def test_fastlane_batch_failure(self, stage, mock_fast_lane):
        """When FastLane throws, return empty list."""
        mock_fast_lane.process.side_effect = Exception("FastLane crash")
        items = [PipelineItem(id=1, title="News", source="s", url="http://x.com/1")]
        result = await stage.process(items)
        assert result == []
