"""Shared DeepSeek translation utility — used by both Telegram bot and AlertDispatcher."""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

TRANSLATE_PROMPT = """Translate this financial news headline to Chinese. Keep it concise and accurate. Preserve ticker symbols (like NVDA, AAPL) as-is. Only output the Chinese translation, nothing else.

English: {text}
Chinese:"""


class TitleTranslator:
    """Translate English financial news titles to Chinese via DeepSeek."""

    def __init__(self) -> None:
        self._client: Optional[object] = None

    def _get_client(self):
        if self._client is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if api_key:
                try:
                    from openai import OpenAI
                    self._client = OpenAI(
                        api_key=api_key,
                        base_url="https://api.deepseek.com",
                    )
                except ImportError:
                    logger.warning("openai package not installed, translation disabled")
        return self._client

    async def translate(self, text: str) -> str:
        """Translate English text to Chinese. Returns empty string on failure."""
        if not text:
            return ""
        client = self._get_client()
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
            logger.debug("Translation failed: %s", e)
        return ""


# Module-level singleton
_translator: Optional[TitleTranslator] = None


def get_translator() -> TitleTranslator:
    global _translator
    if _translator is None:
        _translator = TitleTranslator()
    return _translator
