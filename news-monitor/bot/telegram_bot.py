"""Telegram Bot for news alerts and user interaction."""
import asyncio
import logging
import os
from typing import Optional
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.formatters import format_fast_alert, format_deep_analysis, build_feedback_keyboard
from bot.handlers import register_handlers
from storage.database import Database
from config.loader import ConfigLoader

logger = logging.getLogger(__name__)

TRANSLATE_PROMPT = """Translate this financial news headline to Chinese. Keep it concise and accurate. Preserve ticker symbols (like NVDA, AAPL) as-is. Only output the Chinese translation, nothing else.

English: {text}
Chinese:"""


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
        self._translate_client = None

    def _get_translate_client(self):
        """Lazy-init DeepSeek client for translation."""
        if self._translate_client is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if api_key:
                try:
                    from openai import OpenAI
                    self._translate_client = OpenAI(
                        api_key=api_key,
                        base_url="https://api.deepseek.com",
                    )
                except ImportError:
                    pass
        return self._translate_client

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
        cn_title = await self._translate(title)
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

    async def _translate(self, text: str) -> str:
        """Translate English text to Chinese via DeepSeek."""
        if not text:
            return ""
        client = self._get_translate_client()
        if not client:
            return ""
        try:
            prompt = TRANSLATE_PROMPT.format(text=text[:500])
            response = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=200,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content.strip()
        except Exception as e:
            logger.debug(f"Translation failed: {e}")
        return ""

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
