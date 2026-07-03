"""Tests for multi-channel alert dispatcher."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from engine.alert_dispatcher import (
    AlertDispatcher, AlertLevel, DispatchResult,
    CRITICAL_PRIORITY, IMPORTANT_PRIORITY,
)
from engine.strategic_detector import StrategicDetector, StrategicMatch


@pytest.fixture
def dispatcher():
    return AlertDispatcher()


@pytest.fixture
def strategic():
    return StrategicDetector()


@pytest.fixture
def sample_item():
    return {
        "id": 1,
        "title": "Fed raises rates by 50bp",
        "source": "CNBC",
        "url": "https://example.com/fed",
        "tickers_found": "",
        "macro_tags": "monetary_policy",
    }


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------


def test_classify_critical_by_score(dispatcher):
    level, reason = dispatcher.classify(0.95)
    assert level == AlertLevel.CRITICAL
    assert "0.95" in reason


def test_classify_important_by_score(dispatcher):
    level, reason = dispatcher.classify(0.60)
    assert level == AlertLevel.IMPORTANT
    assert "0.60" in reason


def test_classify_normal_by_score(dispatcher):
    level, reason = dispatcher.classify(0.3)
    assert level == AlertLevel.NORMAL


def test_classify_critical_by_gov_intervention(dispatcher):
    """gov_intervention match → auto CRITICAL regardless of score."""
    matches = [StrategicMatch("gov_intervention", "CHIPS Act funds Intel", 0.85)]
    level, reason = dispatcher.classify(0.3, matches)
    assert level == AlertLevel.CRITICAL
    assert "gov_intervention" in reason


def test_classify_critical_by_nvda_investment(dispatcher):
    """High-confidence nvda_investment → CRITICAL."""
    matches = [StrategicMatch("nvda_investment", "NVIDIA invests in AI startup", 0.90)]
    level, reason = dispatcher.classify(0.5, matches)
    assert level == AlertLevel.CRITICAL


def test_classify_nvda_endorsement_below_threshold(dispatcher):
    """Low-confidence nvda_endorsement → NOT critical (falls to score)."""
    matches = [StrategicMatch("nvda_endorsement", "Jensen Huang says nice thing", 0.65)]
    level, reason = dispatcher.classify(0.49, matches)
    assert level == AlertLevel.NORMAL  # score 0.49 < 0.50, nvda conf 0.65 < 0.70


def test_classify_gov_trumps_score(dispatcher):
    """gov_intervention takes priority over everything."""
    matches = [StrategicMatch("gov_intervention", "White House signs order", 0.65)]
    level, reason = dispatcher.classify(0.95, matches)
    assert level == AlertLevel.CRITICAL


def test_classify_empty_matches(dispatcher):
    level, reason = dispatcher.classify(0.49, [])
    assert level == AlertLevel.NORMAL


def test_classify_none_matches(dispatcher):
    level, reason = dispatcher.classify(0.60, None)
    assert level == AlertLevel.IMPORTANT


# ---------------------------------------------------------------------------
# Dispatch tests (with mock telegram push)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_normal_calls_telegram_silent(dispatcher, sample_item):
    """NORMAL items only get Telegram silent push."""
    push_calls = []

    async def mock_push(item, disable_notification=True):
        push_calls.append(disable_notification)

    result = await dispatcher.dispatch(
        sample_item, priority_score=0.3,
        telegram_push_fn=mock_push,
    )
    assert result.level == AlertLevel.NORMAL
    assert "telegram_silent" in result.channels_used
    assert push_calls == [True]  # disable_notification=True


@pytest.mark.asyncio
async def test_dispatch_important_no_pushover(dispatcher, sample_item):
    """IMPORTANT without Pushover config → Telegram alert only."""
    # Ensure Pushover is disabled
    dispatcher._pushover_token = ""
    dispatcher._pushover_user = ""

    push_calls = []

    async def mock_push(item, disable_notification=True):
        push_calls.append(disable_notification)

    result = await dispatcher.dispatch(
        sample_item, priority_score=0.60,
        telegram_push_fn=mock_push,
    )
    assert result.level == AlertLevel.IMPORTANT
    assert push_calls == [False]  # disable_notification=False for IMPORTANT


@pytest.mark.asyncio
async def test_dispatch_critical_triple_push(dispatcher, sample_item):
    """CRITICAL items get triple push (3 Telegram messages)."""
    dispatcher._pushover_token = ""
    dispatcher._pushover_user = ""

    push_calls = []

    async def mock_push(item, disable_notification=True):
        push_calls.append(disable_notification)

    result = await dispatcher.dispatch(
        sample_item, priority_score=0.95,
        telegram_push_fn=mock_push,
    )
    assert result.level == AlertLevel.CRITICAL
    assert "telegram_triple" in result.channels_used
    assert len(push_calls) == 3
    assert all(not dn for dn in push_calls)  # all 3 → disable_notification=False


# ---------------------------------------------------------------------------
# Pushover message construction (mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pushover_emergency_payload():
    """Verify Pushover emergency message has correct priority/sound fields."""
    dispatcher = AlertDispatcher()
    dispatcher._pushover_token = "test_token"
    dispatcher._pushover_user = "test_user"

    item = {
        "id": 1,
        "title": "Market crash: Fed emergency meeting",
        "source": "Bloomberg",
        "url": "https://example.com",
        "tickers_found": "SPY,QQQ",
        "macro_tags": "monetary_policy",
    }

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_post.return_value.__aenter__.return_value = mock_resp

        result = await dispatcher._pushover_emergency(item)
        assert result is True

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["priority"] == 2
        assert payload["sound"] == "siren"
        assert payload["retry"] == 60
        assert payload["expire"] == 3600
        assert "Market crash" in payload["title"]


@pytest.mark.asyncio
async def test_pushover_high_payload():
    """Verify Pushover high priority message structure."""
    dispatcher = AlertDispatcher()
    dispatcher._pushover_token = "test_token"
    dispatcher._pushover_user = "test_user"

    item = {"title": "Earnings beat", "source": "Reuters", "url": ""}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_post.return_value.__aenter__.return_value = mock_resp

        result = await dispatcher._pushover_high(item)
        assert result is True

        payload = mock_post.call_args[1]["json"]
        assert payload["priority"] == 1
        assert payload["sound"] == "persistent"


@pytest.mark.asyncio
async def test_pushover_http_error_handled():
    """HTTP error should not raise, just log and return False."""
    dispatcher = AlertDispatcher()
    dispatcher._pushover_token = "test"
    dispatcher._pushover_user = "test"

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value="Bad request")
        mock_post.return_value.__aenter__.return_value = mock_resp

        result = await dispatcher._pushover_emergency({"title": "test"})
        assert result is False


# ---------------------------------------------------------------------------
# Pushover availability
# ---------------------------------------------------------------------------


def test_pushover_available(dispatcher):
    dispatcher._pushover_token = "abc"
    dispatcher._pushover_user = "xyz"
    assert dispatcher.pushover_available is True


def test_pushover_not_available(dispatcher):
    dispatcher._pushover_token = ""
    dispatcher._pushover_user = ""
    assert dispatcher.pushover_available is False


def test_pushover_partial_not_available(dispatcher):
    dispatcher._pushover_token = "abc"
    dispatcher._pushover_user = ""
    assert dispatcher.pushover_available is False


# ---------------------------------------------------------------------------
# DispatchResult
# ---------------------------------------------------------------------------


def test_dispatch_result_repr():
    result = DispatchResult(
        level=AlertLevel.CRITICAL,
        channels_used=["pushover_emergency", "telegram_triple"],
        reason="gov_intervention match",
    )
    assert result.level == AlertLevel.CRITICAL
    assert len(result.channels_used) == 2


# ---------------------------------------------------------------------------
# Alert level values
# ---------------------------------------------------------------------------


def test_alert_level_values():
    assert AlertLevel.CRITICAL.value == "critical"
    assert AlertLevel.IMPORTANT.value == "important"
    assert AlertLevel.NORMAL.value == "normal"


# ---------------------------------------------------------------------------
# Integration: real StrategicDetector + AlertDispatcher.classify
# ---------------------------------------------------------------------------


def test_end_to_end_classification_with_real_detector(strategic):
    """Full integration: StrategicDetector → AlertDispatcher.classify."""
    dispatcher = AlertDispatcher()

    # gov_intervention text → should be CRITICAL
    text = "美国政府通过CHIPS Act向英特尔注资85亿美元"
    matches = strategic.detect(text)
    level, reason = dispatcher.classify(0.5, matches)
    assert level == AlertLevel.CRITICAL
    assert "gov_intervention" in reason

    # Normal text → NORMAL
    text2 = "Apple reports quarterly earnings, stock up 3%"
    matches2 = strategic.detect(text2)
    level2, reason2 = dispatcher.classify(0.49, matches2)
    assert level2 == AlertLevel.NORMAL
