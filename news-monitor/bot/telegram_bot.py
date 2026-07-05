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

    async def start(self):
        """Start the bot in polling mode."""
        self._app = Application.builder().token(self.token).build()

        # Register command and callback handlers
        register_handlers(self._app, self.db, self.deep_lane, self.learner, self.curator, self.trainer)

        # Start polling
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram bot started (polling mode)")

    async def stop(self):
        """Stop the bot gracefully."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("Telegram bot stopped")

    async def push_alert(self, item: dict):
        """Push a fast lane alert — English + Chinese translation."""
        if not self._app:
            logger.warning("Bot not initialized, can't push")
            return

        chat_id = self._get_chat_id()
        if not chat_id:
            return

        title = item.get('title', '')
        source = item.get('source', '')
        url = item.get('url', '')
        tickers = item.get('tickers_found', '')
        macro = item.get('macro_tags', '')

        # --- English alert ---
        en_text = format_fast_alert(item)
        keyboard = build_feedback_keyboard(item['id'])

        try:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=en_text,
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )
            logger.info(f"Alert pushed (EN): {title[:50]}...")
        except Exception as e:
            logger.error(f"Push failed (EN): {e}")
            return  # Don't send CN if EN failed

        # --- Chinese translation ---
        cn_title = await self._translator.translate(title)
        if cn_title:
            cn_parts = [f"\U0001f1e8\U0001f1f3 {cn_title}"]
            cn_parts.append(f"来源: {source}")
            if tickers:
                cn_parts.append(f"标的: {tickers}")
            if macro:
                cn_parts.append(f"主题: {macro}")
            if url:
                cn_parts.append(f"\U0001f517 {url}")

            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text="\n".join(cn_parts),
                    disable_web_page_preview=False,
                )
            except Exception as e:
                logger.error(f"Push failed (CN): {e}")

    async def push_deep_analysis(self, item: dict):
        """Push deep analysis as a follow-up message."""
        if not self._app:
            return

        chat_id = self._get_chat_id()
        if not chat_id:
            return

        text = format_deep_analysis(item)
        try:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=text,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error(f"Deep analysis push failed: {e}")

    def _get_chat_id(self) -> Optional[int]:
        """Get the authorized chat ID from preferences."""
        val = self.db.get_preference("telegram_chat_id")
        return int(val) if val else None

    def set_chat_id(self, chat_id: int):
        self.db.set_preference("telegram_chat_id", str(chat_id))
