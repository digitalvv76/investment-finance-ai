"""Tests for Telegram bot handlers (Chinese UI)."""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Helpers — lightweight mocks that simulate telegram Update/Context
# ---------------------------------------------------------------------------

def _mock_update(text="", callback_data=""):
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.effective_chat.id = 12345
    if callback_data:
        update.callback_query = MagicMock()
        update.callback_query.data = callback_data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_reply_markup = AsyncMock()
        # callback_query.message is a nested mock
        update.callback_query.message = MagicMock()
        update.callback_query.message.reply_text = AsyncMock()
    else:
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        update.message.text = text
    return update


def _mock_context(args=None):
    """Create a mock Telegram Context object."""
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


def _mock_db():
    """Create a Database mock with defaults."""
    db = MagicMock()
    db.get_preference.return_value = None
    db.get_recent_news.return_value = []
    db.get_news_by_status.return_value = []
    return db


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------

@pytest.fixture
def handler_setup():
    """Set up handler registrations on a mock Application."""
    from unittest.mock import patch as mock_patch
    # We import inside the test so mocking works cleanly
    from bot import handlers as h
    app = MagicMock()
    db = _mock_db()
    deep_lane = MagicMock()
    learner = MagicMock()
    curator = MagicMock()
    trainer = MagicMock()

    h.register_handlers(
        app, db,
        deep_lane=deep_lane,
        learner=learner,
        curator=curator,
        trainer=trainer,
    )

    # Extract the registered async handler functions from add_handler calls
    handlers_map = {}
    for call_args in app.add_handler.call_args_list:
        handler_obj = call_args[0][0]
        htype = type(handler_obj).__name__
        if htype == "CommandHandler":
            # commands is a frozenset — extract the first element
            cmd = next(iter(handler_obj.commands))
            handlers_map[cmd] = handler_obj.callback
        elif htype == "CallbackQueryHandler":
            handlers_map["callback"] = handler_obj.callback

    return {
        "app": app,
        "db": db,
        "deep_lane": deep_lane,
        "learner": learner,
        "curator": curator,
        "trainer": trainer,
        "handlers": handlers_map,
    }


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_shows_welcome(handler_setup):
    h = handler_setup["handlers"]["start"]
    update = _mock_update()
    ctx = _mock_context()
    await h(update, ctx)
    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "金融新闻监控系统" in text
    assert "/status" in text


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_reports_zero(handler_setup):
    h = handler_setup["handlers"]["status"]
    db = handler_setup["db"]
    db.get_recent_news.return_value = []
    db.get_news_by_status.return_value = []

    update = _mock_update()
    ctx = _mock_context()
    await h(update, ctx)

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "系统运行中" in text
    assert "0 条" in text


@pytest.mark.asyncio
async def test_status_with_data(handler_setup):
    h = handler_setup["handlers"]["status"]
    db = handler_setup["db"]
    db.get_recent_news.return_value = [{"id": 1}] * 42
    db.get_news_by_status.side_effect = lambda s: [{"id": 1}] * (15 if s == "fast_pushed" else 8)

    update = _mock_update()
    ctx = _mock_context()
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "42 条" in text
    assert "15 条" in text  # fast_pushed
    assert "8 条" in text   # deep_pushed


# ---------------------------------------------------------------------------
# /filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_filter_no_args_shows_help(handler_setup):
    h = handler_setup["handlers"]["filter"]
    update = _mock_update()
    ctx = _mock_context(args=[])
    await h(update, ctx)
    text = update.message.reply_text.call_args[0][0]
    assert "filter add" in text
    assert "filter remove" in text


@pytest.mark.asyncio
async def test_filter_add_ticker(handler_setup):
    h = handler_setup["handlers"]["filter"]
    db = handler_setup["db"]
    db.get_preference.return_value = json.dumps([])

    update = _mock_update()
    ctx = _mock_context(args=["add", "NVDA"])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "已添加" in text
    assert "NVDA" in text


@pytest.mark.asyncio
async def test_filter_add_duplicate(handler_setup):
    h = handler_setup["handlers"]["filter"]
    db = handler_setup["db"]
    db.get_preference.return_value = json.dumps(["NVDA"])

    update = _mock_update()
    ctx = _mock_context(args=["add", "NVDA"])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "已在关注列表中" in text


@pytest.mark.asyncio
async def test_filter_remove_ticker(handler_setup):
    h = handler_setup["handlers"]["filter"]
    db = handler_setup["db"]
    db.get_preference.return_value = json.dumps(["NVDA", "TSLA"])

    update = _mock_update()
    ctx = _mock_context(args=["remove", "NVDA"])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "已从关注列表移除" in text
    assert "NVDA" in text


@pytest.mark.asyncio
async def test_filter_remove_not_found(handler_setup):
    h = handler_setup["handlers"]["filter"]
    db = handler_setup["db"]
    db.get_preference.return_value = json.dumps(["AAPL"])

    update = _mock_update()
    ctx = _mock_context(args=["remove", "NVDA"])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "不在关注列表中" in text


@pytest.mark.asyncio
async def test_filter_list(handler_setup):
    h = handler_setup["handlers"]["filter"]
    db = handler_setup["db"]
    db.get_preference.return_value = json.dumps(["AAPL", "NVDA", "TSLA"])

    update = _mock_update()
    ctx = _mock_context(args=["list"])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "AAPL" in text
    assert "NVDA" in text


# ---------------------------------------------------------------------------
# /mute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mute_ticker(handler_setup):
    h = handler_setup["handlers"]["mute"]
    db = handler_setup["db"]
    db.get_preference.return_value = json.dumps({})

    update = _mock_update()
    ctx = _mock_context(args=["TSLA", "24"])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "已静音" in text
    assert "TSLA" in text
    assert "24" in text


@pytest.mark.asyncio
async def test_mute_no_args_shows_active(handler_setup):
    h = handler_setup["handlers"]["mute"]
    db = handler_setup["db"]
    future = (datetime.now() + timedelta(hours=3)).isoformat()
    db.get_preference.return_value = json.dumps({"TSLA": future})

    update = _mock_update()
    ctx = _mock_context(args=[])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "已静音" in text
    assert "TSLA" in text


# ---------------------------------------------------------------------------
# /prefs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prefs_shows_settings(handler_setup):
    h = handler_setup["handlers"]["prefs"]
    db = handler_setup["db"]

    def get_pref_side_effect(key):
        prefs = {
            "filter_tickers": json.dumps(["NVDA", "AAPL"]),
            "muted_tickers": json.dumps({}),
            "learner_threshold": "0.25",
            "learner_personal_dict": json.dumps(["AI", "semiconductor"]),
        }
        return prefs.get(key)

    db.get_preference.side_effect = get_pref_side_effect

    update = _mock_update()
    ctx = _mock_context()
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "偏好设置" in text
    assert "NVDA" in text
    assert "0.25" in text


# ---------------------------------------------------------------------------
# /daily
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_generates_briefing(handler_setup):
    h = handler_setup["handlers"]["daily"]
    db = handler_setup["db"]

    update = _mock_update()
    ctx = _mock_context()
    await h(update, ctx)

    # Two calls: "generating..." then the actual digest
    assert update.message.reply_text.call_count == 2
    assert "正在生成" in update.message.reply_text.call_args_list[0][0][0]


# ---------------------------------------------------------------------------
# /profile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_profile_no_args_shows_current(handler_setup):
    h = handler_setup["handlers"]["profile"]
    curator = handler_setup["curator"]
    curator.get_profile.return_value = {
        "description": "科技股投资者",
        "examples": ["NVDA暴涨"],
        "anti_examples": ["meme币拉升"],
        "focus_tickers": ["NVDA", "AAPL"],
        "focus_sectors": ["AI", "半导体"],
    }

    update = _mock_update()
    ctx = _mock_context(args=[])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "科技股投资者" in text
    assert "NVDA" in text


@pytest.mark.asyncio
async def test_profile_set_description(handler_setup):
    h = handler_setup["handlers"]["profile"]
    curator = handler_setup["curator"]

    update = _mock_update()
    ctx = _mock_context(args=["set", "我是量化交易员，关注波动率套利"])
    await h(update, ctx)

    curator.set_description.assert_called_once_with("我是量化交易员，关注波动率套利")


# ---------------------------------------------------------------------------
# /train
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_train_no_args_shows_docs(handler_setup):
    h = handler_setup["handlers"]["train"]
    trainer = handler_setup["trainer"]
    trainer.list_docs.return_value = [{"id": 1, "type": "url", "title": "Test"}]

    update = _mock_update()
    ctx = _mock_context(args=[])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "训练资料库" in text


# ---------------------------------------------------------------------------
# Callback: thumbs_up / thumbs_down
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_thumbs_up(handler_setup):
    h = handler_setup["handlers"]["callback"]
    db = handler_setup["db"]
    learner = handler_setup["learner"]

    # Simulate first feedback — should trigger adaptation cycle
    def get_pref(key):
        return None
    db.get_preference.side_effect = get_pref

    update = _mock_update(callback_data="thumbs_up:42")
    update.callback_query.data = "thumbs_up:42"

    await h(update, MagicMock())

    db.insert_feedback.assert_called_once()
    learner.run_adaptation_cycle.assert_called_once()


@pytest.mark.asyncio
async def test_callback_thumbs_down(handler_setup):
    h = handler_setup["handlers"]["callback"]
    db = handler_setup["db"]
    learner = handler_setup["learner"]

    def get_pref(key):
        return None
    db.get_preference.side_effect = get_pref

    update = _mock_update(callback_data="thumbs_down:7")
    update.callback_query.data = "thumbs_down:7"

    await h(update, MagicMock())

    db.insert_feedback.assert_called_once()
    learner.run_adaptation_cycle.assert_called_once()


@pytest.mark.asyncio
async def test_callback_feedback_semantics(handler_setup):
    """content_good triggers adaptation. prediction_right/wrong do NOT."""
    h = handler_setup["handlers"]["callback"]
    db = handler_setup["db"]
    learner = handler_setup["learner"]

    db.get_preference.return_value = None

    # content_good: should trigger adaptation (affects topic weights)
    update = _mock_update(callback_data="content_good:1")
    await h(update, MagicMock())
    assert learner.run_adaptation_cycle.call_count == 1

    # prediction_right: should NOT trigger adaptation (only accuracy tracking)
    update2 = _mock_update(callback_data="prediction_right:2")
    await h(update2, MagicMock())
    assert learner.run_adaptation_cycle.call_count == 1

    # prediction_wrong: should NOT trigger adaptation
    update3 = _mock_update(callback_data="prediction_wrong:3")
    await h(update3, MagicMock())
    assert learner.run_adaptation_cycle.call_count == 1


#ssert learner.run_adaptation_cycle.call_count == 1


# ---------------------------------------------------------------------------
# Callback: analyze
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_analyze(handler_setup):
    h = handler_setup["handlers"]["callback"]
    db = handler_setup["db"]
    deep_lane = handler_setup["deep_lane"]

    db.get_news_by_id.return_value = {
        "id": 42, "title": "NVDA earnings", "url": "https://x.com/1",
        "source": "Bloomberg", "content_snippet": "...",
        "tickers_found": "NVDA", "macro_tags": "", "is_breaking": 0,
        "priority_score": 0.5, "sentiment": "bullish",
        "sentiment_score": 0.6, "status": "fast_pushed",
    }

    result = MagicMock()
    result.llm_analysis = "深度分析结果：NVDA 看涨"
    deep_lane.process_on_demand = AsyncMock(return_value=result)

    update = _mock_update(callback_data="analyze:42")
    await h(update, MagicMock())

    deep_lane.process_on_demand.assert_called_once()
    # Check that analysis result was sent via callback_query.message
    assert update.callback_query.message.reply_text.call_count >= 2


# ---------------------------------------------------------------------------
# Callback: ignore
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_ignore(handler_setup):
    h = handler_setup["handlers"]["callback"]

    update = _mock_update(callback_data="ignore:42")
    await h(update, MagicMock())

    update.callback_query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_profile_without_curator(handler_setup):
    """Profile should handle missing curator gracefully."""
    # Re-register without curator
    from bot import handlers as h_mod
    app = MagicMock()
    db = _mock_db()
    h_mod.register_handlers(app, db, curator=None, trainer=MagicMock())

    # Find the profile handler
    for call_args in app.add_handler.call_args_list:
        handler_obj = call_args[0][0]
        if hasattr(handler_obj, 'commands') and 'profile' in handler_obj.commands:
            update = _mock_update()
            ctx = _mock_context(args=[])
            await handler_obj.callback(update, ctx)
            text = update.message.reply_text.call_args[0][0]
            assert "未就绪" in text
            return

    pytest.fail("profile handler not found")


@pytest.mark.asyncio
async def test_train_without_trainer(handler_setup):
    """Train should handle missing trainer gracefully."""
    from bot import handlers as h_mod
    app = MagicMock()
    db = _mock_db()
    h_mod.register_handlers(app, db, curator=MagicMock(), trainer=None)

    for call_args in app.add_handler.call_args_list:
        handler_obj = call_args[0][0]
        if hasattr(handler_obj, 'commands') and 'train' in handler_obj.commands:
            update = _mock_update()
            ctx = _mock_context(args=[])
            await handler_obj.callback(update, ctx)
            text = update.message.reply_text.call_args[0][0]
            assert "未就绪" in text
            return

    pytest.fail("train handler not found")


@pytest.mark.asyncio
async def test_filter_invalid_action(handler_setup):
    h = handler_setup["handlers"]["filter"]
    db = handler_setup["db"]
    db.get_preference.return_value = json.dumps([])

    update = _mock_update()
    ctx = _mock_context(args=["x", "y"])
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "无效" in text


@pytest.mark.asyncio
async def test_mute_invalid_hours(handler_setup):
    h = handler_setup["handlers"]["mute"]
    db = handler_setup["db"]
    db.get_preference.return_value = json.dumps({})

    update = _mock_update()
    ctx = _mock_context(args=["TSLA", "abc"])  # Non-numeric hours
    await h(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "用法" in text
