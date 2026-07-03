"""Telegram bot command and handler callbacks (Chinese UI).

Each command handler is a module-level async function with signature:
    async def handler(update, context, db, **extras)

Dependencies are bound via _bind() in register_handlers().
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from functools import partial
from typing import Callable, Awaitable, Optional

from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from storage.database import Database
from storage.models import FeedbackRecord, NewsItem

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_filters(db: Database) -> list:
    raw = db.get_preference("filter_tickers")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return []


def _save_filters(db: Database, filters: list):
    db.set_preference("filter_tickers", json.dumps(filters))


def _get_muted(db: Database) -> dict:
    raw = db.get_preference("muted_tickers")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {}


def _save_muted(db: Database, muted: dict):
    db.set_preference("muted_tickers", json.dumps(muted))


def _ensure_chat_id(update, db: Database):
    """Persist the chat ID so the bot can push to this user."""
    chat_id = update.effective_chat.id
    db.set_preference("telegram_chat_id", str(chat_id))
    return chat_id


def _newsitem_from_dict(news_dict: dict) -> NewsItem:
    """Construct a NewsItem from a database row dict.

    Centralised here so main.py and handlers don't duplicate the mapping.
    """
    return NewsItem(
        id=news_dict['id'],
        title=news_dict['title'],
        url=news_dict['url'],
        source=news_dict['source'],
        content_snippet=news_dict.get('content_snippet', ''),
        tickers_found=news_dict.get('tickers_found', ''),
        macro_tags=news_dict.get('macro_tags', ''),
        is_breaking=bool(news_dict.get('is_breaking', False)),
        priority_score=news_dict.get('priority_score', 0.0),
        sentiment=news_dict.get('sentiment'),
        sentiment_score=news_dict.get('sentiment_score', 0.0),
        status=news_dict.get('status', 'pending'),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

async def cmd_start(update, context, db: Database):
    await update.message.reply_text(
        "\U0001f4ca 金融新闻监控系统\n\n"
        "可用命令：\n"
        "/status  — 系统运行状态\n"
        "/filter  — 管理关注列表 (add/remove/list)\n"
        "/mute    — 临时静音某标的\n"
        "/profile — AI 个性化配置（设置你的兴趣偏好）\n"
        "/analyze — 自定义分析框架（设置 AI 回复逻辑）\n"
        "/alert   — 紧急打断关键词（匹配后强制推送）\n"
        "/strategic — 战略警报规则（政府入股/英伟达投资检测）\n"
        "/train   — 训练 AI（上传文档/链接让 AI 学习）\n"
        "/reason  — 查看最近推送的打分权重拆解\n"
        "/prefs   — 查看偏好设置\n"
        "/daily   — 生成每日简报\n"
        "/help    — 显示此消息"
    )


async def cmd_status(update, context, db: Database):
    _ensure_chat_id(update, db)

    all_recent = db.get_recent_news(hours=24)
    total_news = len(all_recent)
    total_pushed = len(db.get_news_by_status("fast_pushed"))
    total_deep = len(db.get_news_by_status("deep_pushed"))

    threshold = db.get_preference("learner_threshold") or "0.30"
    personal_kw = db.get_preference("learner_personal_dict") or "[]"
    try:
        kw_count = len(json.loads(personal_kw))
    except json.JSONDecodeError:
        kw_count = 0

    msg = (
        "\U0001f4ca 系统运行中\n\n"
        f"24小时新闻: {total_news} 条\n"
        f"快速推送: {total_pushed} 条\n"
        f"深度分析: {total_deep} 条\n"
        f"推送阈值: {threshold}\n"
        f"个人关键词: {kw_count} 个"
    )
    await update.message.reply_text(msg)


async def cmd_filter(update, context, db: Database):
    args = context.args or []
    _ensure_chat_id(update, db)

    if not args:
        await update.message.reply_text(
            "用法：\n"
            "/filter add <代码>  — 添加关注标的\n"
            "/filter remove <代码>  — 移除关注标的\n"
            "/filter list  — 查看当前列表"
        )
        return

    action = args[0].lower()
    filters = _get_filters(db)

    if action == "list":
        if filters:
            await update.message.reply_text(
                f"关注列表: {', '.join(sorted(filters))}"
            )
        else:
            await update.message.reply_text("关注列表为空。")
    elif action == "add" and len(args) >= 2:
        ticker = args[1].upper()
        if ticker in filters:
            await update.message.reply_text(f"{ticker} 已在关注列表中。")
        else:
            filters.append(ticker)
            _save_filters(db, filters)
            await update.message.reply_text(f"已添加 {ticker} 到关注列表。")
    elif action == "remove" and len(args) >= 2:
        ticker = args[1].upper()
        if ticker in filters:
            filters.remove(ticker)
            _save_filters(db, filters)
            await update.message.reply_text(f"已从关注列表移除 {ticker}。")
        else:
            await update.message.reply_text(f"{ticker} 不在关注列表中。")
    else:
        await update.message.reply_text("无效命令。用法: add / remove / list")


async def cmd_mute(update, context, db: Database):
    args = context.args or []
    _ensure_chat_id(update, db)

    if len(args) == 0:
        muted = _get_muted(db)
        now = datetime.now()
        active = {t: u for t, u in muted.items() if datetime.fromisoformat(u) > now}
        if active:
            lines = ["已静音的标的："]
            for t, until in active.items():
                lines.append(f"  ${t} — 到 {until[:16]}")
            await update.message.reply_text("\n".join(lines))
        else:
            await update.message.reply_text("当前没有静音的标的。\n用法: /mute <代码> <小时数>")
        return

    if len(args) >= 2:
        ticker = args[0].upper()
        try:
            hours = int(args[1])
        except ValueError:
            await update.message.reply_text("用法: /mute <代码> <小时数>，如 /mute TSLA 24")
            return

        muted = _get_muted(db)
        until = (datetime.now() + timedelta(hours=hours)).isoformat()
        muted[ticker] = until
        _save_muted(db, muted)
        await update.message.reply_text(
            f"已静音 ${ticker} {hours} 小时（到 {until[:16]}）"
        )
    else:
        await update.message.reply_text("用法: /mute <代码> <小时数>")


async def cmd_prefs(update, context, db: Database):
    _ensure_chat_id(update, db)

    filters = _get_filters(db)
    muted = _get_muted(db)
    threshold = db.get_preference("learner_threshold") or "0.30"
    personal_kw = db.get_preference("learner_personal_dict") or "[]"
    chat_id_val = db.get_preference("telegram_chat_id") or "未设置"

    try:
        kw_list = json.loads(personal_kw)
    except json.JSONDecodeError:
        kw_list = []

    lines = [
        "偏好设置",
        "",
        f"Chat ID: {chat_id_val}",
        f"推送阈值: {threshold}",
        f"关注列表: {', '.join(sorted(filters)) if filters else '无'}",
        f"个人关键词: {', '.join(kw_list) if kw_list else '无'}",
    ]

    if muted:
        now = datetime.now()
        active_mutes = {
            t: until for t, until in muted.items()
            if datetime.fromisoformat(until) > now
        }
        if active_mutes:
            lines.append("已静音:")
            for t, until in active_mutes.items():
                lines.append(f"  ${t} 到 {until[:16]}")
        else:
            lines.append("已静音: 无（全部已过期）")

    await update.message.reply_text("\n".join(lines))


async def cmd_profile(update, context, db: Database, curator=None, **kwargs):
    args = context.args or []
    _ensure_chat_id(update, db)

    if not curator:
        await update.message.reply_text("AI 策展引擎未就绪。")
        return

    if not args:
        p = curator.get_profile()
        desc = p.get("description", "未设置")[:300]
        examples = p.get("examples", [])
        anti = p.get("anti_examples", [])
        tickers = p.get("focus_tickers", [])
        sectors = p.get("focus_sectors", [])

        msg = "*你的兴趣档案*\n\n"
        msg += f"描述: {desc}\n\n"
        if tickers:
            msg += f"关注标的: {', '.join(tickers)}\n"
        if sectors:
            msg += f"关注领域: {', '.join(sectors)}\n"
        if examples:
            msg += f"\n正面案例 ({len(examples)}条):\n"
            for e in examples[-3:]:
                msg += f"  + {e[:60]}\n"
        if anti:
            msg += f"\n负面案例 ({len(anti)}条):\n"
            for e in anti[-3:]:
                msg += f"  - {e[:60]}\n"
        msg += "\n命令:\n"
        msg += "/profile set <描述> — 设置兴趣描述\n"
        msg += "/profile add <标题> — 添加正面案例\n"
        msg += "/profile anti <标题> — 添加负面案例\n"
        msg += "/profile clear — 重置为默认"
        await update.message.reply_text(msg)
        return

    action = args[0].lower()

    if action == "set":
        desc = " ".join(args[1:])
        if not desc:
            await update.message.reply_text("用法: /profile set <描述你的兴趣>")
            return
        curator.set_description(desc)
        await update.message.reply_text("兴趣描述已更新。系统将根据此描述筛选新闻。")

    elif action == "add" and len(args) >= 2:
        headline = " ".join(args[1:])
        curator.add_example(headline)
        await update.message.reply_text(f"已添加正面案例: {headline[:80]}")

    elif action == "anti" and len(args) >= 2:
        headline = " ".join(args[1:])
        curator.add_anti_example(headline)
        await update.message.reply_text(f"已添加负面案例: {headline[:80]}")

    elif action == "clear":
        curator.reset_profile()
        await update.message.reply_text("已重置为默认兴趣档案。")

    else:
        await update.message.reply_text(
            "用法:\n"
            "/profile — 查看当前档案\n"
            "/profile set <描述> — 设置兴趣\n"
            "/profile add <标题> — 添加正面案例\n"
            "/profile anti <标题> — 添加负面案例\n"
            "/profile clear — 重置"
        )


async def cmd_train(update, context, db: Database, trainer=None, **kwargs):
    args = context.args or []
    _ensure_chat_id(update, db)

    if not trainer:
        await update.message.reply_text("训练引擎未就绪。")
        return

    if not args:
        docs = trainer.list_docs()
        if docs:
            lines = [f"*训练资料库* ({len(docs)} 条)\n"]
            for d in docs[:10]:
                tp = "URL" if d['type'] == 'url' else "文本"
                title = (d.get('title') or d.get('source', ''))[:60]
                lines.append(f"  #{d['id']} [{tp}] {title}")
            lines.append("\n命令:")
        else:
            lines = ["训练资料库为空。\n"]

        lines.append("/train url <链接> — 添加网页进行分析学习")
        lines.append("/train text <内容> — 添加文本资料")
        lines.append("/train delete <id> — 删除某条资料")
        lines.append("/train list — 查看所有资料")
        await update.message.reply_text("\n".join(lines))
        return

    action = args[0].lower()

    if action == "url" and len(args) >= 2:
        url = args[1]
        await update.message.reply_text(f"正在获取并分析: {url[:80]}...")
        try:
            doc_id = await trainer.ingest_url(url)
            if doc_id:
                await update.message.reply_text(
                    f"已添加到训练资料库 (ID: {doc_id})。\nAI 将学习此内容用于新闻筛选。"
                )
            else:
                await update.message.reply_text("获取失败。请检查链接是否可访问。")
        except Exception as e:
            await update.message.reply_text(f"处理失败: {e}")

    elif action == "text" and len(args) >= 2:
        text = " ".join(args[1:])
        doc_id = trainer.ingest_text(text)
        await update.message.reply_text(
            f"已添加文本资料 (ID: {doc_id})。\nAI 将学习此内容用于新闻筛选。"
        )

    elif action == "delete" and len(args) >= 2:
        try:
            doc_id = int(args[1])
            trainer.delete_doc(doc_id)
            await update.message.reply_text(f"已删除资料 #{doc_id}。")
        except ValueError:
            await update.message.reply_text("用法: /train delete <id>")

    elif action == "list":
        docs = trainer.list_docs()
        if docs:
            lines = [f"*训练资料库* ({len(docs)} 条)\n"]
            for d in docs[:15]:
                tp = "URL" if d['type'] == 'url' else "文本"
                title = (d.get('title') or d.get('source', ''))[:50]
                summary = (d.get('summary', ''))[:60]
                lines.append(f"#{d['id']} [{tp}] {title}")
                if summary:
                    lines.append(f"    {summary}")
            await update.message.reply_text("\n".join(lines))
        else:
            await update.message.reply_text("训练资料库为空。")

    else:
        await update.message.reply_text(
            "用法:\n"
            "/train url <链接> — 添加网页\n"
            "/train text <内容> — 添加文本\n"
            "/train list — 查看资料\n"
            "/train delete <id> — 删除资料"
        )


async def cmd_analyze(update, context, db: Database, deep_lane=None, **kwargs):
    args = context.args or []
    _ensure_chat_id(update, db)

    if not deep_lane:
        await update.message.reply_text("深度分析引擎未就绪。")
        return

    if not args:
        # Show current framework preview
        framework = deep_lane.get_framework()
        preview = framework[:500] + ("..." if len(framework) > 500 else "")
        msg = (
            "*当前分析框架*\n\n"
            f"```\n{preview}\n```\n\n"
            "命令:\n"
            "/analyze set <4步框架> — 设置自定义分析框架\n"
            "/analyze reset — 恢复默认框架\n"
            "/analyze show — 查看完整框架"
        )
        await update.message.reply_text(msg)
        return

    action = args[0].lower()

    if action == "set":
        framework = " ".join(args[1:])
        if not framework:
            await update.message.reply_text(
                "用法: /analyze set <你的分析框架>\n\n"
                "框架中可以使用变量: {title}, {source}, {tickers}, "
                "{macro_tags}, {sentiment}, {sentiment_score}, {extra_context}\n\n"
                "建议包含4步: 事件定性 → 传导路径 → 组合映射 → 置信度"
            )
            return
        deep_lane.set_framework(framework)
        await update.message.reply_text(
            f"分析框架已更新 ({len(framework)} 字符)。\n"
            "后续所有深度分析将使用此框架。"
        )

    elif action == "reset":
        deep_lane.reset_framework()
        await update.message.reply_text("已恢复默认分析框架。")

    elif action == "show":
        framework = deep_lane.get_framework()
        if len(framework) <= 3800:
            await update.message.reply_text(f"```\n{framework}\n```")
        else:
            for i in range(0, len(framework), 3800):
                chunk = framework[i:i+3800]
                await update.message.reply_text(f"```\n{chunk}\n```")

    else:
        await update.message.reply_text(
            "用法: /analyze [set|reset|show]"
        )


async def cmd_alert(update, context, db: Database):
    args = context.args or []
    _ensure_chat_id(update, db)

    if not args:
        keywords_raw = db.get_preference("urgent_keywords") or ""
        keywords = [k for k in keywords_raw.split(",") if k] if keywords_raw else []
        if keywords:
            msg = f"*紧急打断关键词* ({len(keywords)} 个):\n" + "\n".join(f"  🔴 {k}" for k in keywords)
        else:
            msg = "未设置紧急关键词。\n用法: /alert urgent <关键词1> <关键词2> ..."
        msg += "\n\n匹配到这些关键词的新闻将*绕过评分阈值强制推送*。"
        await update.message.reply_text(msg)
        return

    action = args[0].lower()

    if action == "urgent":
        keywords = args[1:]
        if not keywords:
            await update.message.reply_text("用法: /alert urgent <关键词1> <关键词2> ...")
            return
        db.set_preference("urgent_keywords", ",".join(keywords))
        await update.message.reply_text(
            f"已设置 {len(keywords)} 个紧急关键词:\n" +
            "\n".join(f"  🔴 {k}" for k in keywords) +
            "\n\n匹配到这些词的新闻将强制推送。"
        )

    elif action == "clear":
        db.set_preference("urgent_keywords", "")
        await update.message.reply_text("已清除所有紧急关键词。")

    else:
        await update.message.reply_text("用法: /alert urgent <关键词> 或 /alert clear")


async def cmd_strategic(update, context, db: Database):
    args = context.args or []
    _ensure_chat_id(update, db)

    if not args:
        gov_entities = db.get_preference("strategic_gov_entities") or ""
        nvda_entities = db.get_preference("strategic_nvda_entities") or ""
        extra_actions = db.get_preference("strategic_actions") or ""

        lines = [
            "🎯 *战略警报规则*",
            "",
            "*检测模式*:",
            "1. 政府/监管机构 + 入股/资助/扶持 → 某公司",
            "2. 英伟达/黄仁勋 + 入股/投资/收购 → 某公司",
            "",
        ]
        if gov_entities:
            lines.append(f"自定义政府实体: {gov_entities}")
        if nvda_entities:
            lines.append(f"自定义NV实体: {nvda_entities}")
        if extra_actions:
            lines.append(f"自定义动作词: {extra_actions}")

        lines.append("")
        lines.append("命令:")
        lines.append("/strategic gov add <实体> — 添加政府实体")
        lines.append("/strategic nvda add <实体> — 添加NVIDIA相关实体")
        lines.append("/strategic action add <动词> — 添加触发动作")
        lines.append("/strategic test <文本> — 测试一条新闻是否触发")
        await update.message.reply_text("\n".join(lines))
        return

    action = args[0].lower()

    if action == "test":
        test_text = " ".join(args[1:])
        if not test_text:
            await update.message.reply_text("用法: /strategic test <新闻标题或内容>")
            return
        from engine.strategic_detector import StrategicDetector
        sd = StrategicDetector()
        matches = sd.detect(test_text)
        if matches:
            lines = [f"✅ 触发! {len(matches)} 条匹配:"]
            for m in matches:
                lines.append(f"  🎯 {m.category} (置信度: {m.confidence:.0%})")
                lines.append(f"     {m.matched_text[:100]}")
        else:
            lines = ["❌ 未触发任何战略警报规则。"]
        await update.message.reply_text("\n".join(lines))
        return

    if len(args) < 3:
        await update.message.reply_text(
            "用法:\n"
            "/strategic gov add <实体>\n"
            "/strategic nvda add <实体>\n"
            "/strategic action add <动词>\n"
            "/strategic test <文本>"
        )
        return

    sub_action = args[1].lower()
    value = " ".join(args[2:])

    if action == "gov" and sub_action == "add":
        existing = db.get_preference("strategic_gov_entities") or ""
        current = set(existing.split(",")) if existing else set()
        current.add(value)
        db.set_preference("strategic_gov_entities", ",".join(current))
        await update.message.reply_text(f"已添加政府实体: {value}")

    elif action == "nvda" and sub_action == "add":
        existing = db.get_preference("strategic_nvda_entities") or ""
        current = set(existing.split(",")) if existing else set()
        current.add(value)
        db.set_preference("strategic_nvda_entities", ",".join(current))
        await update.message.reply_text(f"已添加NVIDIA实体: {value}")

    elif action == "action" and sub_action == "add":
        existing = db.get_preference("strategic_actions") or ""
        current = set(existing.split(",")) if existing else set()
        current.add(value)
        db.set_preference("strategic_actions", ",".join(current))
        await update.message.reply_text(f"已添加动作词: {value}")

    else:
        await update.message.reply_text("无效命令。用法: gov add / nvda add / action add / test")


async def cmd_reason(update, context, db: Database):
    _ensure_chat_id(update, db)

    recent = db.get_recent_news(hours=24, limit=1)
    if not recent:
        await update.message.reply_text("最近24小时没有推送记录。")
        return

    item = recent[0]
    tickers = item.get('tickers_found', '') or '无'
    macros = item.get('macro_tags', '') or '无'
    priority = item.get('priority_score', 0)
    sentiment = item.get('sentiment', 'neutral')
    sentiment_score = item.get('sentiment_score', 0)
    is_breaking = bool(item.get('is_breaking', False))
    source = item.get('source', '未知')
    status = item.get('status', 'pending')

    breaking_score = 0.40 if is_breaking else 0.0
    ticker_list = [t for t in tickers.split(",") if t and t != '无']
    macro_list = [m for m in macros.split(",") if m and m != '无']
    ticker_score = min(len(ticker_list) * 0.06, 0.30)
    macro_score = min(len(macro_list) * 0.08, 0.32)
    base_score = min(breaking_score + ticker_score + macro_score, 1.0)

    lines = [
        "🔍 *打分权重拆解*",
        "",
        f"*新闻*: {item.get('title', '')[:80]}",
        f"*来源*: {source}",
        f"*最终得分*: {priority:.3f}",
        f"*状态*: {status}",
        f"*情感*: {sentiment} ({sentiment_score:+.2f})",
        "",
        "*得分分解*:",
        f"  🔴 突发标记: {breaking_score:.2f} {'(是)' if is_breaking else '(否)'}",
        f"  📊 标的 ({len(ticker_list)}个): {ticker_score:.2f} — {tickers}",
        f"  🌐 宏观 ({len(macro_list)}个): {macro_score:.2f} — {macros}",
        f"  ─────────────────",
        f"  基础分: {base_score:.2f}",
        f"  剩余: {priority - base_score:+.3f} (来源权威 + 共振 + 其他)",
    ]

    total = db.get_preference("prediction_total") or "0"
    correct = db.get_preference("prediction_correct") or "0"
    if total != "0":
        acc = int(correct) / int(total) * 100 if int(total) > 0 else 0
        lines.append("")
        lines.append(f"*预测记录*: {correct}/{total} 准确 ({acc:.0f}%)")

    urgent = db.get_preference("urgent_keywords") or ""
    if urgent:
        lines.append(f"*紧急关键词*: {urgent}")

    await update.message.reply_text("\n".join(lines))


async def cmd_daily(update, context, db: Database):
    _ensure_chat_id(update, db)

    await update.message.reply_text("正在生成每日简报...")

    try:
        from bot.digest import DigestGenerator
        digest_gen = DigestGenerator(db)
        text = digest_gen.generate(hours=24)
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"简报生成失败: {e}")
        await update.message.reply_text("简报生成失败，请稍后重试。")


async def cmd_help(update, context, db: Database):
    await cmd_start(update, context, db)


# ═══════════════════════════════════════════════════════════════════════════
# Callback query handler
# ═══════════════════════════════════════════════════════════════════════════

async def handle_callback(update, context, db: Database,
                          deep_lane=None, learner=None, **kwargs):
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split(':', 1)
    action = parts[0]
    news_id = int(parts[1]) if len(parts) > 1 else 0

    # Backward-compatible thumbs_up/down (deprecated, map to content_good)
    if action in ('thumbs_up', 'thumbs_down'):
        action = 'content_good'

    if action == 'content_good':
        fb = FeedbackRecord(news_id=news_id, reaction='content_good')
        db.insert_feedback(fb)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("📰 已记录：内容质量反馈。系统将优化此类内容的推送权重。")

        if learner:
            try:
                learner.run_adaptation_cycle()
                db.set_preference("feedback_pending_count", "0")
                db.set_preference("last_adaptation_time", datetime.now().isoformat())
            except Exception as e:
                logger.debug(f"学习引擎跳过: {e}")

    elif action in ('prediction_right', 'prediction_wrong'):
        label = "准确" if action == 'prediction_right' else "错误"
        fb = FeedbackRecord(news_id=news_id, reaction=action)
        db.insert_feedback(fb)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"📈 已记录：预测{label}。系统正在学习分析准确性...\n"
            "（此反馈不影响内容推送权重，仅用于评估分析框架）"
        )

        try:
            total = int(db.get_preference("prediction_total") or "0") + 1
            correct = int(db.get_preference("prediction_correct") or "0")
            if action == 'prediction_right':
                correct += 1
            db.set_preference("prediction_total", str(total))
            db.set_preference("prediction_correct", str(correct))
        except Exception:
            pass

    elif action == 'analyze':
        await query.message.reply_text("正在深度分析...")
        if deep_lane and news_id:
            news_dict = db.get_news_by_id(news_id)
            if news_dict:
                item = _newsitem_from_dict(news_dict)
                try:
                    result = await deep_lane.process_on_demand(item)
                    if result.llm_analysis:
                        await query.message.reply_text(
                            f"深度分析:\n\n{result.llm_analysis}"
                        )
                    else:
                        await query.message.reply_text(
                            "分析完成，但未获取到详细洞察。"
                        )
                except Exception as e:
                    logger.error(f"按需分析失败: {e}")
                    await query.message.reply_text("分析失败，请稍后重试。")
        else:
            await query.message.reply_text("深度分析引擎未就绪。")

    elif action == 'ignore':
        await query.edit_message_reply_markup(reply_markup=None)


# ═══════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════

def register_handlers(app: Application, db: Database,
                      deep_lane=None, learner=None, curator=None,
                      trainer=None) -> None:
    """Register all command and callback handlers on the application."""

    # Bind db (+ optional dependencies) to each handler.
    # Each handler receives (update, context, db, **extras).
    extras = dict(
        deep_lane=deep_lane, learner=learner,
        curator=curator, trainer=trainer,
    )
    extras_cb = dict(deep_lane=deep_lane, learner=learner)

    H = lambda fn, **kw: _make_handler(fn, db, **(kw or {}))

    app.add_handler(CommandHandler("start",     H(cmd_start)))
    app.add_handler(CommandHandler("status",    H(cmd_status)))
    app.add_handler(CommandHandler("filter",    H(cmd_filter)))
    app.add_handler(CommandHandler("mute",      H(cmd_mute)))
    app.add_handler(CommandHandler("prefs",     H(cmd_prefs)))
    app.add_handler(CommandHandler("profile",   H(cmd_profile, **extras)))
    app.add_handler(CommandHandler("train",     H(cmd_train, **extras)))
    app.add_handler(CommandHandler("daily",     H(cmd_daily)))
    app.add_handler(CommandHandler("analyze",   H(cmd_analyze, **extras)))
    app.add_handler(CommandHandler("alert",     H(cmd_alert)))
    app.add_handler(CommandHandler("strategic", H(cmd_strategic)))
    app.add_handler(CommandHandler("reason",    H(cmd_reason)))
    app.add_handler(CommandHandler("help",      H(cmd_help)))
    app.add_handler(CallbackQueryHandler(
        H(handle_callback, **extras_cb)
    ))

    logger.info("Bot handlers registered (Chinese UI)")


def _make_handler(fn, db: Database, **extras):
    """Return an async callback that invokes *fn* with bound dependencies.

    Usage:
        handler = _make_handler(cmd_status, db)
        app.add_handler(CommandHandler("status", handler))
    """
    async def wrapper(update, context):
        return await fn(update, context, db, **extras)
    return wrapper
