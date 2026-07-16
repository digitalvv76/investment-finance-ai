"""Test same-topic phone dedup in DispatchStage.

Verifies that the CPI-repeat scenario (3 same-macro items in 3 hours →
only first reaches Pushover) is handled correctly, plus edge cases.
"""
import pytest
import time
from unittest.mock import AsyncMock, patch

from pipeline.item import PipelineItem, DispatchDecision, AlertLevel
from pipeline.dispatch import DispatchStage, _dedup_key, _DEDUP_WINDOW_SECONDS


# ── Helpers ────────────────────────────────────────────────────────────

def _item(title="", headline_signal="", ticker_hint=None, intensity=4,
          direction="up", alert_level=AlertLevel.IMPORTANT, id=1,
          impact_score=0, macro_tags=""):
    """Minimal PipelineItem with DispatchDecision for dispatch tests."""
    return PipelineItem(
        id=id,
        title=title,
        macro_tags=macro_tags,
        decision=DispatchDecision(
            alert_level=alert_level,
            intensity=intensity,
            direction=direction,
            headline_signal=headline_signal,
            ticker_hint=ticker_hint or [],
            impact_score=impact_score,
        ),
    )


# ── _dedup_key tests ───────────────────────────────────────────────────

def test_dedup_key_ticker_based():
    """Ticker-based items derive key from sorted tickers + direction."""
    item = _item(title="NVDA earnings beat", ticker_hint=["NVDA"], direction="up")
    assert _dedup_key(item) == "ticker:NVDA:up"

    # Multiple tickers → sorted
    item2 = _item(ticker_hint=["MSFT", "AAPL"], direction="down")
    assert _dedup_key(item2) == "ticker:AAPL,MSFT:down"


def test_dedup_key_macro_cpi():
    """Macro CPI items derive key from headline_signal pattern match."""
    item = _item(
        title="CPI低于预期推动股市上涨",
        headline_signal="CPI超预期回落至3.5%，降息预期升温",
        direction="up",
    )
    key = _dedup_key(item)
    # CPI/通胀/inflation all normalize to canonical "inflation"
    assert key == "macro:inflation:up"


@pytest.mark.parametrize("headline,expected_topic", [
    ("美联储维持利率不变，鲍威尔偏鸽", "fed_rate"),
    ("6月非农就业远超预期，失业率降至3.5%", "employment"),
    ("GDP增速放缓至2.1%，衰退担忧升温", "gdp"),
    ("ISM制造业PMI意外跌至46.0，连续第八个月收缩", "pmi"),
    ("PCE物价指数同比上涨2.6%，核心PCE持平", "pce_ppi"),
    ("特朗普宣布对中国加征60%关税", "trade"),
    ("摩根大通、花旗财报超预期，银行股集体走高", "bank_earnings"),
])
def test_dedup_key_macro_patterns(headline, expected_topic):
    """All macro topic patterns match and produce canonical keys."""
    item = _item(title=headline, headline_signal=headline, direction="up")
    key = _dedup_key(item)
    assert key is not None, f"Should match: {headline}"
    assert key == f"macro:{expected_topic}:up"


def test_dedup_key_none_for_non_macro():
    """Non-macro, non-ticker items return None (no dedup)."""
    item = _item(
        title="某CEO接受采访谈行业前景",
        headline_signal="CEO对AI长期前景持乐观态度",
    )
    assert _dedup_key(item) is None


# ── _phone_should_skip tests ───────────────────────────────────────────

def test_phone_skip_first_occurrence_allows():
    """First occurrence of a topic is always allowed through."""
    stage = DispatchStage([])
    item = _item(
        title="CPI低于预期",
        headline_signal="CPI超预期回落至3.5%",
        intensity=4,
    )
    skip, reason = stage._phone_should_skip(item)
    assert skip is False
    assert reason == ""
    # Should be recorded
    assert len(stage._phone_push_log) == 1


def test_phone_skip_same_topic_blocks_second():
    """Second same-topic item within window is blocked."""
    stage = DispatchStage([])
    item1 = _item(
        id=1, title="CPI低于预期 #1",
        headline_signal="CPI超预期回落至3.5%，利好美股",
        intensity=4,
    )
    item2 = _item(
        id=2, title="CPI低于预期 #2",
        headline_signal="CPI通胀放缓至3.5%，投资者关注",
        intensity=4,
    )
    # First passes
    skip1, _ = stage._phone_should_skip(item1)
    assert skip1 is False
    # Second blocked — same topic, same intensity
    skip2, reason2 = stage._phone_should_skip(item2)
    assert skip2 is True
    assert "same_topic_dedup" in reason2
    assert "prev_id=1" in reason2


def test_phone_skip_intensity_upgrade_allows():
    """Higher intensity on same topic overrides dedup (upgrade)."""
    stage = DispatchStage([])
    item1 = _item(
        id=1, title="CPI低于预期 #1",
        headline_signal="CPI回落至3.5%",
        intensity=4,
    )
    item2 = _item(
        id=2, title="CPI暴跌！美联储紧急降息",
        headline_signal="CPI意外暴跌，美联储召开紧急会议",
        intensity=5,
        alert_level=AlertLevel.CRITICAL,
    )
    # First passes
    stage._phone_should_skip(item1)
    # Second passes — intensity 5 > 4
    skip2, reason2 = stage._phone_should_skip(item2)
    assert skip2 is False
    assert "intensity_upgrade" in reason2


def test_phone_skip_equal_intensity_no_upgrade():
    """Equal intensity is NOT an upgrade — still blocked."""
    stage = DispatchStage([])
    item1 = _item(id=1, headline_signal="CPI回落至3.5%", intensity=4)
    item2 = _item(id=2, headline_signal="CPI通胀放缓", intensity=4)
    stage._phone_should_skip(item1)
    skip2, _ = stage._phone_should_skip(item2)
    assert skip2 is True


def test_phone_skip_different_direction_different_key():
    """Same macro but different direction → different key, both pass."""
    stage = DispatchStage([])
    item_up = _item(
        id=1, headline_signal="CPI回落利好美股", direction="up", intensity=4,
    )
    item_down = _item(
        id=2, headline_signal="CPI反弹引发抛售", direction="down", intensity=4,
    )
    skip1, _ = stage._phone_should_skip(item_up)
    skip2, _ = stage._phone_should_skip(item_down)
    assert skip1 is False
    assert skip2 is False  # Different direction → different key


def test_phone_skip_window_expiry_allows():
    """After the dedup window expires, same topic is allowed again."""
    stage = DispatchStage([])
    item = _item(id=1, headline_signal="CPI回落至3.5%", intensity=4)
    stage._phone_should_skip(item)

    # Simulate window expiry by manipulating the stored timestamp
    key = _dedup_key(item)
    old_intensity, _, old_id = stage._phone_push_log[key]
    stage._phone_push_log[key] = (old_intensity, time.time() - _DEDUP_WINDOW_SECONDS - 1, old_id)

    item2 = _item(id=2, headline_signal="CPI通胀放缓", intensity=4)
    skip, _ = stage._phone_should_skip(item2)
    assert skip is False


def test_phone_skip_ticker_dedup():
    """Ticker-based dedup: same stock, same direction → blocked."""
    stage = DispatchStage([])
    item1 = _item(id=1, title="NVDA earnings beat", ticker_hint=["NVDA"],
                  direction="up", intensity=4)
    item2 = _item(id=2, title="NVDA raised guidance", ticker_hint=["NVDA"],
                  direction="up", intensity=4)
    stage._phone_should_skip(item1)
    skip, reason = stage._phone_should_skip(item2)
    assert skip is True


def test_phone_skip_ticker_different_direction_allows():
    """Same ticker, opposite direction → different key, both pass."""
    stage = DispatchStage([])
    item1 = _item(id=1, ticker_hint=["NVDA"], direction="up", intensity=4)
    item2 = _item(id=2, ticker_hint=["NVDA"], direction="down", intensity=4)
    stage._phone_should_skip(item1)
    skip, _ = stage._phone_should_skip(item2)
    assert skip is False


# ── Integration: dispatch stage with mock channels ─────────────────────

class SpyChannel:
    """Records every send() call for assertions."""
    def __init__(self, name):
        self.name = name
        self.calls: list[dict] = []

    async def send(self, item, decision, disable_notification=False):
        # Mirror real PushoverChannel: only CRITICAL/IMPORTANT reach phone
        if self.name == "pushover" and decision.alert_level not in (
            AlertLevel.CRITICAL, AlertLevel.IMPORTANT,
        ):
            return False
        self.calls.append({
            "id": item.id,
            "title": item.title,
            "level": decision.alert_level.value,
            "silent": disable_notification,
            "intensity": decision.intensity,
        })
        return True


@pytest.mark.asyncio
async def test_dispatch_cpi_trio_only_first_to_pushover():
    """CPI 3-article scenario: first → Pushover, 2nd+3rd → TG only."""
    pushover = SpyChannel("pushover")
    telegram = SpyChannel("telegram")

    stage = DispatchStage([pushover, telegram])

    items = [
        _item(id=1, title="CPI暴跌至3.5%，降息预期飙升",
              headline_signal="CPI大幅回落至3.5%远超预期，市场押注9月降息50bp",
              intensity=5, direction="up", impact_score=100, macro_tags="CPI"),  # ≥85 → phone
        _item(id=2, title="CPI Headline Inflation Drops To 3.5%",
              headline_signal="CPI超预期回落至3.5%，助力股市走高",
              intensity=4, direction="up", impact_score=80, macro_tags="CPI"),  # <85 → TG only
        _item(id=3, title="6月通胀放缓至3.5%，但能持续多久？",
              headline_signal="6月通胀放缓至3.5%，但投资者需知后续风险",
              intensity=4, direction="up", impact_score=80, macro_tags="CPI"),
    ]

    await stage.process(items)

    # Pushover: only first
    assert len(pushover.calls) == 1, f"Expected 1 Pushover push, got {len(pushover.calls)}"
    assert pushover.calls[0]["id"] == 1

    # Telegram: all 3 (NOTABLE is silent, but these are IMPORTANT → not silent)
    assert len(telegram.calls) == 3, f"Expected 3 Telegram pushes, got {len(telegram.calls)}"


@pytest.mark.asyncio
async def test_dispatch_intensity_upgrade_repushes():
    """Intensity upgrade (4→5) on same topic pushes again to phone."""
    pushover = SpyChannel("pushover")
    telegram = SpyChannel("telegram")
    stage = DispatchStage([pushover, telegram])

    items = [
        _item(id=1, title="CPI低于预期", headline_signal="CPI通胀放缓至3.5%",
              intensity=4, direction="up", impact_score=100, macro_tags="CPI"),
        _item(id=2, title="CPI暴跌！紧急降息", headline_signal="CPI意外暴跌，美联储紧急降息50bp",
              intensity=5, direction="up", alert_level=AlertLevel.CRITICAL),
    ]

    await stage.process(items)

    assert len(pushover.calls) == 2, f"Both should push (upgrade): got {len(pushover.calls)}"
    assert len(telegram.calls) == 2


@pytest.mark.asyncio
async def test_dispatch_mixed_tickers_all_pass():
    """Different tickers → all pass through to phone."""
    pushover = SpyChannel("pushover")
    telegram = SpyChannel("telegram")
    stage = DispatchStage([pushover, telegram])

    items = [
        _item(id=1, title="NVDA earnings", ticker_hint=["NVDA"],
              intensity=4, direction="up"),
        _item(id=2, title="RKLB launch success", ticker_hint=["RKLB"],
              intensity=4, direction="up"),
        _item(id=3, title="TSLA delivery beat", ticker_hint=["TSLA"],
              intensity=4, direction="up"),
    ]

    await stage.process(items)

    assert len(pushover.calls) == 3
    assert len(telegram.calls) == 3


@pytest.mark.asyncio
async def test_dispatch_normal_skipped_entirely():
    """NORMAL items never reach any channel (including dedup check)."""
    pushover = SpyChannel("pushover")
    telegram = SpyChannel("telegram")
    stage = DispatchStage([pushover, telegram])

    items = [_item(id=1, alert_level=AlertLevel.NORMAL)]

    await stage.process(items)

    assert len(pushover.calls) == 0
    assert len(telegram.calls) == 0


@pytest.mark.asyncio
async def test_dispatch_notable_telegram_only():
    """NOTABLE items go to Telegram (silent), never to phone."""
    pushover = SpyChannel("pushover")
    telegram = SpyChannel("telegram")
    stage = DispatchStage([pushover, telegram])

    items = [_item(id=1, alert_level=AlertLevel.NOTABLE, intensity=3,
                   headline_signal="关注股异动", ticker_hint=["SMR"])]

    await stage.process(items)

    # Pushover: PushoverChannel.send() only fires for CRITICAL/IMPORTANT
    assert len(pushover.calls) == 0
    # Telegram: gets NOTABLE with disable_notification=True
    assert len(telegram.calls) == 1
    assert telegram.calls[0]["silent"] is True


@pytest.mark.asyncio
async def test_headline_similarity_cross_ticker_dedup():
    """台积电(TSM) and TSM produce different ticker keys, but similar
    headline_signal should still dedup on phone.

    Scenario: Chinese source reports "台积电3nm涨价", LLM ticker_hint=[];
    English source reports "TSMC price hike", LLM ticker_hint=["TSM"].
    Without cross-key fallback, both push to phone. With it, second is skipped.
    """
    pushover = SpyChannel("pushover")
    telegram = SpyChannel("telegram")
    stage = DispatchStage([pushover, telegram])

    # Item 1: Chinese source — article covers TSMC+NVIDIA, LLM picks NVDA
    # NVDA is in watchlist → phone threshold passes
    item1 = _item(id=1, title="台积电3nm制程涨价20%，英伟达成本承压",
                  headline_signal="台积电宣布3nm制程涨价20%，英伟达GPU成本将上升，利好半导体代工板块",
                  ticker_hint=["NVDA"], intensity=4, direction="up")

    # Item 2: English source — same event, LLM picks TSM (different ticker!)
    # TSM is in watchlist → phone threshold passes
    item2 = _item(id=2, title="TSMC Raises 3nm Prices By 20%",
                  headline_signal="台积电3nm晶圆代工价格上调20%，反映AI芯片强劲需求，利好台积电毛利率",
                  ticker_hint=["TSM"], intensity=4, direction="up")

    await stage.process([item1])
    assert len(pushover.calls) == 1  # first item pushes to phone

    await stage.process([item2])
    # Second item should be deduped on phone because headline_signal is similar
    assert len(pushover.calls) == 1, (
        f"Cross-key headline dedup failed: expected 1 Pushover, got {len(pushover.calls)}. "
        f"Calls: {[(c['id'], c.get('reason','')) for c in pushover.calls]}"
    )
    # TG still gets both (by design — TG doesn't participate in phone dedup)
    assert len(telegram.calls) == 2
