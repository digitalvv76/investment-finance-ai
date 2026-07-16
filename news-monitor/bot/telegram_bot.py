"""Telegram Bot for news alerts and user interaction."""
import asyncio
import logging
import os
from typing import Optional
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.formatters import format_fast_alert, format_deep_analysis, build_feedback_keyboard
from bot.handlers import register_handlers
from bot.translator import get_translator
from storage.database import Database
from config.loader import ConfigLoader

logger = logging.getLogger(__name__)


class NewsBot:
    def __init__(self, token: str, db: Database, config: ConfigLoader, deep_lane=None, learner=None, curator=None, trainer=None):
        self.token = token
        self.db = db
        self.config = config
        self.deep_lane = deep_lane
        self.learner = learner
        self.curator = curator
        self.trainer = trainer
        self._app: Optional[Application] = None
        self._translator = get_translator()

    async def _auto_detect_chat_id(self):
        """Auto-detect and persist chat_id from recent Telegram conversations.

        Called once on startup when no chat_id is saved yet.  This ensures
        the bot can push messages even if the user hasn't explicitly sent
        /start — any prior conversation with the bot will be discovered.

        If multiple chat_ids are found in recent updates, the most recent one
        becomes the primary and older ones are logged for manual review.
        """
        existing = self._get_chat_ids()
        if existing:
            logger.info("Telegram chat_ids: %s (from database + env)", existing)
            return

        logger.info("No chat_id saved — auto-detecting from Telegram API ...")
        try:
            resp = await self._app.bot.get_updates(limit=10, timeout=5)
            seen: set[int] = set()
            for update in resp:
                chat = update.effective_chat
                if chat and chat.id not in seen:
                    seen.add(chat.id)
            if seen:
                # Use the most recently active chat as primary
                chat_id = max(seen)  # higher IDs = more recent
                self.set_chat_id(chat_id)
                logger.info("Auto-detected chat_id: %d (saved to database)", chat_id)
                if len(seen) > 1:
                    others = sorted(seen - {chat_id})
                    logger.info(
                        "Multiple chat_ids found: %s. To add additional Telegram, "
                        "set TELEGRAM_CHAT_ID_2 or TELEGRAM_CHAT_ID_3 in .env",
                        seen, others[0],
                    )
            else:
                logger.warning(
                    "No chat_id found — Telegram pushes will fail until "
                    "someone sends a message to the bot.  Open Telegram, "
                    "search for the bot, and send any message."
                )
        except Exception as e:
            logger.warning("chat_id auto-detection failed: %s", e)

    async def start(self):
        """Start the bot in polling mode."""
        self._app = Application.builder().token(self.token).build()

        # Register command and callback handlers
        register_handlers(self._app, self.db, self.deep_lane, self.learner, self.curator, self.trainer)

        # Initialize and auto-detect chat_id BEFORE starting polling
        await self._app.initialize()
        await self._auto_detect_chat_id()

        # Start polling
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram bot started (polling mode)")

    async def stop(self):
        """Stop the bot gracefully."""
        if self._app:
            try:
                await self._app.updater.stop()
            except RuntimeError:
                pass  # updater was never started (e.g. no token configured)
            try:
                await self._app.stop()
            except RuntimeError:
                pass
            try:
                await self._app.shutdown()
            except RuntimeError:
                pass
        logger.info("Telegram bot stopped")

    async def push_alert(self, item: dict, analyst_note: str = "",
                          event_category: str = "",
                          impact_score: int = 0, confidence: int = 0,
                          disable_notification: bool = False,
                          urgency: str = "",
                          sentiment: str = "",
                          greed_index: int = 50,
                          key_points: str = "",
                          risk_flags: str = ""):
        """Push a fast lane alert — Chinese only.

        Pushes to ALL registered chat_ids (primary + TELEGRAM_CHAT_ID_2/_3).
        """
        if not self._app:
            logger.warning("Bot not initialized, can't push")
            return

        chat_ids = self._get_chat_ids()
        if not chat_ids:
            return

        title = item.get('title', '')
        source = item.get('source', '')
        url = item.get('url', '')
        tickers = item.get('tickers_found', '')
        macro = item.get('macro_tags', '')

        keyboard = build_feedback_keyboard(item['id'], url)

        # --- Chinese title ---
        if self._is_chinese(title):
            cn_title = title
        else:
            cn_title = await self._translator.translate(title)

        if cn_title:
            cn_parts = [cn_title]

            # ── 💡 LLM 分析 ──
            note = analyst_note or item.get('analyst_note', '')
            if note:
                cn_parts.append(f"\n💡 {note}")

            # ── 💥 冲击 + 置信度 ──
            if impact_score > 0:
                imp_line = f"\n💥 冲击: {impact_score}分"
                if confidence > 0:
                    imp_line += f" | 置信度: {confidence}%"
                cn_parts.append(imp_line)

            # ── 🎯 相关标的 ──
            from bot.formatters import _build_ticker_etf_line
            etf_line = _build_ticker_etf_line(tickers, macro, event_category)
            if etf_line:
                cn_parts.append(f"\n🎯 {etf_line}")

            for chat_id in chat_ids:
                try:
                    await self._app.bot.send_message(
                        chat_id=chat_id,
                        text="\n".join(cn_parts),
                        reply_markup=keyboard,
                        disable_web_page_preview=False,
                        disable_notification=disable_notification,
                    )
                    logger.info(f"Alert pushed → chat {chat_id}: {title[:50]}...")
                except Exception as e:
                    logger.error(f"Push failed → chat {chat_id}: {e}")

    async def push_deep_analysis(self, item: dict):
        """Push deep analysis as a follow-up message to all registered chats."""
        if not self._app:
            return

        chat_ids = self._get_chat_ids()
        if not chat_ids:
            return

        text = format_deep_analysis(item)
        for chat_id in chat_ids:
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.error(f"Deep analysis push failed → chat {chat_id}: {e}")

    def _get_chat_ids(self) -> list[int]:
        """Get all authorized chat IDs.

        Priority:
        1. TELEGRAM_CHAT_ID env var — locked primary, never overwritten
        2. Auto-detected (DB) — fallback / additional user
        3. TELEGRAM_CHAT_ID_2 / _3 — explicit extras
        """
        ids: list[int] = []

        # Locked primary: set in .env, never rotates
        env_primary = os.environ.get("TELEGRAM_CHAT_ID", "")
        if env_primary:
            try:
                ids.append(int(env_primary))
            except ValueError:
                logger.warning("Invalid TELEGRAM_CHAT_ID: %s", env_primary)

        # Auto-detected: whoever messaged the bot most recently (DB)
        val = self.db.get_preference("telegram_chat_id")
        if val:
            db_id = int(val)
            if db_id not in ids:
                ids.append(db_id)

        # Secondary / tertiary: explicit extras
        for key in ("TELEGRAM_CHAT_ID_2", "TELEGRAM_CHAT_ID_3"):
            env_val = os.environ.get(key, "")
            if env_val:
                try:
                    eid = int(env_val)
                    if eid not in ids:
                        ids.append(eid)
                except ValueError:
                    logger.warning("Invalid %s: %s", key, env_val)
        return ids

    def set_chat_id(self, chat_id: int):
        """Set the primary chat ID (persisted to DB)."""
        self.db.set_preference("telegram_chat_id", str(chat_id))

    @staticmethod
    def _is_chinese(text: str) -> bool:
        """Return True if text is predominantly Chinese (CJK characters)."""
        if not text:
            return False
        cjk = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
        return cjk >= len(text) * 0.3  # 30%+ CJK → treat as Chinese
