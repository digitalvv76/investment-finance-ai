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
    level, reason = dispatcher.classify(0.50)
    assert level == AlertLevel.IMPORTANT
    assert "0.50" in reason


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
    """Low-confidence nvda_endorsement → NOT critical (falls to score).

    With default rel_mult=1.0 (simulating watchlist stock), 0.38 >= 0.35
    new watchlist threshold → IMPORTANT.  Previously this was NORMAL at 0.45.
    """
    matches = [StrategicMatch("nvda_endorsement", "Jensen Huang says nice thing", 0.65)]
    level, reason = dispatcher.classify(0.38, matches)
    assert level == AlertLevel.IMPORTANT  # score 0.38 >= watchlist threshold 0.35

def test_classify_non_watchlist_below_threshold(dispatcher):
    """Non-watchlist stock with moderate score → NORMAL."""
    matches = [StrategicMatch("nvda_endorsement", "Jensen Huang says nice thing", 0.65)]
    level, reason = dispatcher.classify(0.38, matches, rel_mult=0.3, has_tickers=True, is_macro=False)
    assert level == AlertLevel.NORMAL  # rel_mult=0.3 = not in watchlist, 0.38 < 0.45


def test_classify_gov_trumps_score(dispatcher):
    """gov_intervention takes priority over everything."""
    matches = [StrategicMatch("gov_intervention", "White House signs order", 0.65)]
    level, reason = dispatcher.classify(0.95, matches)
    assert level == AlertLevel.CRITICAL


def test_classify_empty_matches(dispatcher):
    """0.38 with default rel_mult=1.0 → treated as watchlist → IMPORTANT (≥0.35)."""
    level, reason = dispatcher.classify(0.38, [])
    assert level == AlertLevel.IMPORTANT

def test_classify_empty_matches_non_watchlist(dispatcher):
    """0.38 with rel_mult=0.3 → non-watchlist → NORMAL (<0.45)."""
    level, reason = dispatcher.classify(0.38, [], rel_mult=0.3, has_tickers=True, is_macro=False)
    assert level == AlertLevel.NORMAL


def test_classify_none_matches(dispatcher):
    level, reason = dispatcher.classify(0.50, None)
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
    dispatcher._pushover_users = []

    push_calls = []

    async def mock_push(item, disable_notification=True):
        push_calls.append(disable_notification)

    result = await dispatcher.dispatch(
        sample_item, priority_score=0.50,
        telegram_push_fn=mock_push,
    )
    assert result.level == AlertLevel.IMPORTANT
    assert push_calls == [False]  # disable_notification=False for IMPORTANT


@pytest.mark.asyncio
async def test_dispatch_critical_triple_push(dispatcher, sample_item):
    """CRITICAL items get triple push (3 Telegram messages)."""
    dispatcher._pushover_token = ""
    dispatcher._pushover_users = []

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
    dispatcher._pushover_users = ["test_user"]

    item = {
        "id": 1,
        "title": "Market crash: Fed emergency meeting",
        "source": "Bloomberg",
        "url": "https://example.com",
        "tickers_found": "SPY,QQQ",
        "macro_tags": "monetary_policy",
        "_impact_score": 95,
        "_confidence": 88,
    }

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_post.return_value.__aenter__.return_value = mock_resp

        # Mock the translator to return a known Chinese string (avoids real API call)
        with patch("bot.translator.TitleTranslator.translate", new_callable=AsyncMock) as mock_translate:
            mock_translate.return_value = "市场崩盘：美联储紧急会议"

            result = await dispatcher._pushover_emergency(item)
            assert result is True

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["priority"] == 2
        assert payload["sound"] == "spacealarm"
        assert payload["retry"] == 30
        assert payload["expire"] == 3600
        # Title: source + Chinese headline (tickers in body ETF line)
        assert "市场崩盘" in payload["title"]
        # Body: starts with impact score, includes ETF line with tickers
        assert "冲击: 95分" in payload["message"]
        assert "置信度: 88%" in payload["message"]
        assert "SPY" in payload["message"]


@pytest.mark.asyncio
async def test_pushover_high_payload():
    """Verify Pushover high priority message structure."""
    dispatcher = AlertDispatcher()
    dispatcher._pushover_token = "test_token"
    dispatcher._pushover_users = ["test_user"]

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
    dispatcher._pushover_users = ["test"]

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
    dispatcher._pushover_users = ["xyz"]
    assert dispatcher.pushover_available is True


def test_pushover_not_available(dispatcher):
    dispatcher._pushover_token = ""
    dispatcher._pushover_users = []
    assert dispatcher.pushover_available is False


def test_pushover_partial_not_available(dispatcher):
    dispatcher._pushover_token = "abc"
    dispatcher._pushover_users = []
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

    # Apple earnings — Apple in FALLBACK_TICKERS, default rel=1.0 → watchlist stock
    # 0.38 >= 0.35 watchlist threshold → IMPORTANT
    text2 = "Apple reports quarterly earnings, stock up 3%"
    matches2 = strategic.detect(text2)
    level2, reason2 = dispatcher.classify(0.38, matches2)
    assert level2 == AlertLevel.IMPORTANT


# ---------------------------------------------------------------------------
# send_system_alert — watchdog/operational alerts (direct Pushover, no news item)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, captured):
        self._captured = captured
        self.status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def text(self):
        return "ok"


class _FakeSession:
    """Stubs aiohttp.ClientSession so send_system_alert never hits the network."""
    def __init__(self, captured):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, url, json=None, timeout=None):
        self._captured.append(json)
        return _FakeResp(self._captured)


def _wire_fake_pushover(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "engine.alert_dispatcher.aiohttp.ClientSession",
        lambda *a, **k: _FakeSession(captured),
    )
    d = AlertDispatcher()
    d._pushover_token = "tok"
    d._pushover_users = ["u1"]
    return d, captured


@pytest.mark.asyncio
async def test_send_system_alert_emergency_is_siren(monkeypatch):
    d, captured = _wire_fake_pushover(monkeypatch)
    ok = await d.send_system_alert("停摆", "零采集", emergency=True)
    assert ok is True
    assert captured[0]["priority"] == 2
    assert captured[0]["sound"] == "siren"
    assert captured[0]["retry"] == 30 and captured[0]["expire"] == 3600


@pytest.mark.asyncio
async def test_send_system_alert_quiet_is_silent(monkeypatch):
    d, captured = _wire_fake_pushover(monkeypatch)
    ok = await d.send_system_alert("日报", "系统正常", quiet=True)
    assert ok is True
    assert captured[0]["priority"] == -1
    assert captured[0]["sound"] == "none"


@pytest.mark.asyncio
async def test_send_system_alert_default_is_high(monkeypatch):
    d, captured = _wire_fake_pushover(monkeypatch)
    ok = await d.send_system_alert("降级", "成功率下降")
    assert ok is True
    assert captured[0]["priority"] == 1
    assert captured[0]["sound"] == "persistent"


@pytest.mark.asyncio
async def test_send_system_alert_unavailable_returns_false():
    d = AlertDispatcher()
    d._pushover_token = ""
    d._pushover_users = []
    ok = await d.send_system_alert("x", "y", emergency=True)
    assert ok is False
