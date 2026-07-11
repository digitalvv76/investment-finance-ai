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


class TestAssessmentPersistence:
    """#1: EvaluateStage must persist the detailed impact assessment."""

    @pytest.mark.asyncio
    async def test_persists_assessment_when_db_provided(self, mock_impact, mock_dispatcher):
        from storage.models import ImpactAssessment
        db = MagicMock()
        db.insert_assessment = MagicMock(return_value=42)
        stage = EvaluateStage(
            impact_evaluator=mock_impact, dispatcher=mock_dispatcher, db=db,
        )
        items = [
            PipelineItem(id=7, title="FOMC", source="CNBC", url="http://x/1",
                         priority_score=0.75, tickers_found="SPY", is_breaking=True)
        ]
        mock_impact.evaluate.return_value = ImpactAssessment(
            impact_score=65, confidence=80, analyst_note="x", event_category="earnings",
        )

        await stage.process(items)

        assert db.insert_assessment.called
        saved = db.insert_assessment.call_args[0][0]
        assert saved.news_id == 7  # FK bound to the persisted news row

    @pytest.mark.asyncio
    async def test_no_persist_when_id_zero(self, mock_impact, mock_dispatcher):
        """Guard: don't write a dangling FK for unpersisted items (id=0)."""
        from storage.models import ImpactAssessment
        db = MagicMock()
        db.insert_assessment = MagicMock(return_value=0)
        stage = EvaluateStage(
            impact_evaluator=mock_impact, dispatcher=mock_dispatcher, db=db,
        )
        items = [
            PipelineItem(id=0, title="x", source="s", url="http://x/0",
                         priority_score=0.75, tickers_found="SPY")
        ]
        mock_impact.evaluate.return_value = ImpactAssessment(
            impact_score=65, confidence=80, event_category="earnings",
        )

        await stage.process(items)

        assert not db.insert_assessment.called

    @pytest.mark.asyncio
    async def test_no_db_is_backward_compatible(self, stage, mock_impact):
        """No db handle → no crash (legacy construction path)."""
        from storage.models import ImpactAssessment
        items = [
            PipelineItem(id=1, title="x", source="s", url="http://x/1",
                         priority_score=0.75, tickers_found="SPY")
        ]
        mock_impact.evaluate.return_value = ImpactAssessment(
            impact_score=65, confidence=80, event_category="earnings",
        )
        result = await stage.process(items)
        assert len(result) == 1


class TestEventDirectionChannel:
    """SPEC-intensity-scale-bear-bias — _apply_event_assessment direction-aware
    channel + bearish escalation, end-to-end through the pipeline stage."""

    def _apply(self, ea, tracked):
        from engine.event_driven_evaluator import EventAssessment  # noqa: F401
        stage = EvaluateStage(impact_evaluator=MagicMock(), dispatcher=MagicMock())
        item = PipelineItem(id=1, title="t", source="s", url="http://x/1")
        with patch("engine.relevance.get_tracked_tickers", return_value=set(tracked)):
            stage._apply_event_assessment(item, ea)
        return item.decision

    def _ea(self, **kw):
        from engine.event_driven_evaluator import EventAssessment
        base = dict(is_event=True, intensity=5, direction="up", confirmed=True,
                    ticker_hint=[], headline_signal="h", risk_snapshot="r")
        base.update(kw)
        return EventAssessment(**base)

    def test_cal01_reportedly_bearish_3_is_notable_not_phone(self):
        """cal-01 acceptance anchor: reportedly bearish ★3 hitting tracked GOOGL
        → NOTABLE (silent TG), NOT critical, NOT phone."""
        ea = self._ea(intensity=3, direction="down", confirmed=False,
                      ticker_hint=["GOOGL", "MSFT"])
        d = self._apply(ea, tracked=["GOOGL"])
        assert d.alert_level == AlertLevel.NOTABLE

    def test_bullish_5_critical(self):
        d = self._apply(self._ea(intensity=5, direction="up"), tracked=[])
        assert d.alert_level == AlertLevel.CRITICAL

    def test_bearish_5_caps_important(self):
        ea = self._ea(intensity=5, direction="down", confirmed=True, ticker_hint=["XYZ"])
        d = self._apply(ea, tracked=["GOOGL"])
        assert d.alert_level == AlertLevel.IMPORTANT

    def test_bearish_5_escalates_when_tracked_and_confirmed(self):
        ea = self._ea(intensity=5, direction="down", confirmed=True, ticker_hint=["GOOGL"])
        d = self._apply(ea, tracked=["GOOGL", "AAPL"])
        assert d.alert_level == AlertLevel.CRITICAL

    def test_bearish_5_rumor_off_phone_notable(self):
        """Fail-safe: unconfirmed (reportedly) bearish → NOTABLE (silent TG),
        never phone — holds even at ★5 hitting a tracked name."""
        ea = self._ea(intensity=5, direction="down", confirmed=False, ticker_hint=["GOOGL"])
        d = self._apply(ea, tracked=["GOOGL"])
        assert d.alert_level == AlertLevel.NOTABLE

    def test_intensity_3_up_notable(self):
        d = self._apply(self._ea(intensity=3, direction="up"), tracked=[])
        assert d.alert_level == AlertLevel.NOTABLE
        assert d.direction == "up"
