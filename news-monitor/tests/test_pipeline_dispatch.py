"""Tests for DispatchStage."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from pipeline.dispatch import DispatchStage
from pipeline.item import PipelineItem, DispatchDecision, AlertLevel


class MockChannel:
    def __init__(self, name, should_fail=False):
        self.name = name
        self.should_fail = should_fail
        self.sent = []

    async def send(self, item, decision, disable_notification=False):
        if self.should_fail:
            raise Exception(f"{self.name} error")
        self.sent.append((item.id, decision.alert_level))
        return True


class TestDispatchStage:

    @pytest.mark.asyncio
    async def test_happy_path_all_channels(self):
        """Items are sent to all channels."""
        ch1 = MockChannel("pushover")
        ch2 = MockChannel("telegram")
        stage = DispatchStage(channels=[ch1, ch2])

        items = [
            PipelineItem(
                id=1, title="FOMC emergency", source="CNBC", url="http://x.com/1",
                decision=DispatchDecision(alert_level=AlertLevel.CRITICAL, alert_reason="test"),
            )
        ]
        result = await stage.process(items)

        assert len(result) == 1
        assert len(ch1.sent) == 1
        assert len(ch2.sent) == 1

    @pytest.mark.asyncio
    async def test_single_channel_failure(self):
        """One channel failing doesn't block others."""
        ch_good = MockChannel("telegram")
        ch_bad = MockChannel("pushover", should_fail=True)
        stage = DispatchStage(channels=[ch_good, ch_bad])

        items = [
            PipelineItem(
                id=1, title="Test", source="s", url="http://x.com/1",
                decision=DispatchDecision(alert_level=AlertLevel.IMPORTANT),
            )
        ]
        result = await stage.process(items)

        assert len(result) == 1
        assert len(ch_good.sent) == 1  # Good channel still received it

    @pytest.mark.asyncio
    async def test_empty_input(self):
        stage = DispatchStage(channels=[])
        result = await stage.process([])
        assert result == []
