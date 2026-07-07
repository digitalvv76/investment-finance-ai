"""Tests for DeepStage."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from pipeline.deep import DeepStage
from pipeline.item import PipelineItem, DispatchDecision, AlertLevel


class TestDeepStage:

    @pytest.mark.asyncio
    async def test_needs_deep_spawns_task(self):
        """Items with needs_deep=True spawn background tasks and return immediately."""
        mock_dl = MagicMock()
        mock_dl.process = AsyncMock()
        stage = DeepStage(deep_lane=mock_dl)

        items = [
            PipelineItem(
                id=1, title="Big event", source="CNBC", url="http://x.com/1",
                decision=DispatchDecision(needs_deep=True),
            )
        ]
        result = await stage.process(items)

        assert len(result) == 1  # Returns immediately
        # Give background task time to run
        import asyncio
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_no_deep_passes_through(self):
        """Items without needs_deep pass through unchanged, no LLM call."""
        mock_dl = MagicMock()
        stage = DeepStage(deep_lane=mock_dl)

        items = [
            PipelineItem(
                id=1, title="Routine", source="blog", url="http://x.com/1",
                decision=DispatchDecision(needs_deep=False),
            )
        ]
        result = await stage.process(items)

        assert len(result) == 1
        assert not mock_dl.process.called

    @pytest.mark.asyncio
    async def test_empty_input(self):
        stage = DeepStage(deep_lane=MagicMock())
        result = await stage.process([])
        assert result == []
