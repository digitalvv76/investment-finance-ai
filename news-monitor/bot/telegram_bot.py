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
        """
        existing = self._get_chat_id()
        if existing:
            logger.info("Telegram chat_id: %d (from database)", existing)
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
                # Use the most recently active chat
                chat_id = max(seen)  # higher IDs = more recent
                self.set_chat_id(chat_id)
                logger.info("Auto-detected chat_id: %d (saved to database)", chat_id)
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
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("Telegram bot stopped")

    async def push_alert(self, item: dict, analyst_note: str = "",
                          event_category: str = "",
                          impact_score: int = 0, confidence: int = 0):
        """Push a fast lane alert — English original + Chinese translation.

        The English message includes analyst note, ticker CN names, and
        sector ETFs.  The Chinese message is a translation of the title
        followed by the same analyst note and ETF line.
        """
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

        # --- English alert (includes analyst note + impact + ETFs) ---
        en_text = format_fast_alert(item, analyst_note=analyst_note,
                                    event_category=event_category,
                                    impact_score=impact_score,
                                    confidence=confidence)
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

            # Impact score + confidence
            if impact_score > 0:
                imp_line = f"\n💥 冲击: {impact_score}分"
                if confidence > 0:
                    imp_line += f" | 置信度: {confidence}%"
                cn_parts.append(imp_line)

            # Analyst note (same as EN version — already in Chinese)
            note = analyst_note or item.get('analyst_note', '')
            if note:
                cn_parts.append(f"\n{note}")

            # Related tickers + sector ETFs
            from bot.formatters import _build_ticker_etf_line
            etf_line = _build_ticker_etf_line(tickers, macro, event_category)
            if etf_line:
                cn_parts.append(f"\n{etf_line}")

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
