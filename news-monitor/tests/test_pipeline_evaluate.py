"""Tests for EvaluateStage."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.evaluate import EvaluateStage
from pipeline.item import PipelineItem, DispatchDecision, AlertLevel


@pytest.fixture
def mock_impact():
    impact = MagicMock()
    impact.evaluate = AsyncMock()
    return impact


@pytest.fixture
def mock_dispatcher():
    disp = MagicMock()
    disp.classify = MagicMock(return_value=(AlertLevel.IMPORTANT, "test_reason"))
    return disp


@pytest.fixture
def stage(mock_impact, mock_dispatcher):
    return EvaluateStage(
        impact_evaluator=mock_impact,
        dispatcher=mock_dispatcher,
    )


class TestEvaluateStage:

    @pytest.mark.asyncio
    async def test_happy_path(self, stage, mock_impact, mock_dispatcher):
        """Normal item gets impact assessment + classification + decision."""
        from storage.models import ImpactAssessment
        items = [
            PipelineItem(
                id=1, title="FOMC raises rates", source="CNBC", url="http://x.com/1",
                priority_score=0.75, tickers_found="SPY", is_breaking=True,
            )
        ]
        mock_impact.evaluate.return_value = ImpactAssessment(
            impact_score=65, confidence=80, analyst_note="Key macro event",
            event_category="monetary_policy",
        )

        result = await stage.process(items)

        assert len(result) == 1
        assert result[0].decision.alert_level == AlertLevel.IMPORTANT
        assert result[0].decision.impact_score == 65
        assert result[0].decision.analyst_note == "Key macro event"
        assert mock_impact.evaluate.called

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self, stage, mock_impact, mock_dispatcher):
        """When LLM fails, fall back to legacy score-based classification."""
        items = [
            PipelineItem(
                id=1, title="Market update", source="WSJ", url="http://x.com/1",
                priority_score=0.60, tickers_found="", is_breaking=False,
            )
        ]
        mock_impact.evaluate = AsyncMock(side_effect=Exception("LLM timeout"))

        result = await stage.process(items)

        assert len(result) == 1
        assert mock_dispatcher.classify.called
        assert isinstance(result[0].decision, DispatchDecision)

    @pytest.mark.asyncio
    async def test_single_item_llm_failure(self, stage, mock_impact, mock_dispatcher):
        """One item failing LLM doesn't block others."""
        from storage.models import ImpactAssessment
        items = [
            PipelineItem(id=1, title="Good", source="s", url="http://a.com/1",
                         priority_score=0.75, tickers_found="AAPL"),
            PipelineItem(id=2, title="Bad LLM", source="s", url="http://a.com/2",
                         priority_score=0.60, tickers_found=""),
        ]
        call_count = 0

        async def fake_evaluate(item_dict, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("LLM timeout on second item")
            return ImpactAssessment(
                impact_score=70, confidence=85, analyst_note="Good item",
                event_category="earnings",
            )

        mock_impact.evaluate = fake_evaluate

        result = await stage.process(items)

        assert len(result) == 2
        assert result[0].decision.impact_score == 70
        assert isinstance(result[1].decision, DispatchDecision)

    @pytest.mark.asyncio
    async def test_empty_input(self, stage):
        result = await stage.process([])
        assert result == []
