"""Graham Review — Benjamin Graham-style value investing gate.

A pre-dispatch safety net that asks: "Does this news really deserve to
interrupt the investor's attention?"  Graham can only DOWNGRADE — never
upgrade.  He is the brake, not the accelerator.

Inserted between Evaluate and Dispatch: every non-NORMAL item passes
through Graham before reaching the push channels.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "prompts", "graham_review.txt",
)


def _load_prompt() -> str:
    try:
        p = os.path.normpath(_PROMPT_PATH)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read()
    except Exception:
        logger.exception("Graham: failed to load prompt from disk")
    return ""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class GrahamVerdict:
    verdict: str          # "PUSH" | "SILENT" | "DROP"
    failures: list[int]   # e.g. [2, 5]
    note: str             # one-line reason


# ---------------------------------------------------------------------------
# Graham Reviewer
# ---------------------------------------------------------------------------


class GrahamReviewer:
    """Pre-dispatch safety net — value-investor perspective.

    Only downgrades, never upgrades.  Fails open (timeout / API error →
    let the item pass through unchanged).
    """

    def __init__(self) -> None:
        self._client = None
        self._model = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def review(
        self,
        title: str,
        snippet: str = "",
        source: str = "",
        tickers: str = "",
        macro_tags: str = "",
    ) -> GrahamVerdict | None:
        """Review a news item through Graham's 5-question checklist.

        Returns None on error (fail-open: let the item pass).
        """
        if not title:
            return None

        prompt = _load_prompt()
        if not prompt:
            logger.warning("Graham: prompt not available, skipping review")
            return None

        user_text = self._build_user_text(title, snippet, source, tickers, macro_tags)
        full_prompt = f"{prompt}\n\n---\n\n{user_text}"

        try:
            raw = await asyncio.wait_for(
                self._call_llm(full_prompt), timeout=5.0,
            )
            parsed = self._parse(raw)
            if parsed is None:
                logger.warning("Graham: failed to parse LLM output, skipping")
                return None
            return parsed
        except asyncio.TimeoutError:
            logger.warning("Graham: LLM call timed out, skipping review")
            return None
        except Exception:
            logger.exception("Graham: LLM call failed, skipping review")
            return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_user_text(
        self, title: str, snippet: str, source: str,
        tickers: str, macro_tags: str,
    ) -> str:
        parts = [f"标题：{title}"]
        if snippet:
            snip = snippet[:300]
            parts.append(f"摘要：{snip}")
        if source:
            parts.append(f"来源：{source}")
        if tickers:
            parts.append(f"涉及标的：{tickers}")
        if macro_tags:
            parts.append(f"宏观标签：{macro_tags}")
        return "\n".join(parts)

    async def _call_llm(self, prompt: str) -> str:
        if self._client is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if not api_key:
                raise RuntimeError("DEEPSEEK_API_KEY not set")
            from openai import OpenAI
            self._client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com",
            )
            self._model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

        resp = await asyncio.to_thread(
            self._client.chat.completions.create,
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=256,
        )
        return resp.choices[0].message.content.strip()

    @staticmethod
    def _parse(raw: str) -> GrahamVerdict | None:
        # Strip markdown code fences
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find a JSON object in the text
            m = re.search(r'\{[^{}]*"verdict"[^{}]*\}', text, re.DOTALL)
            if m is None:
                return None
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                return None

        verdict = str(data.get("verdict", "")).upper().strip()
        if verdict not in ("PUSH", "SILENT", "DROP"):
            return None

        failures_raw = data.get("failures", [])
        if not isinstance(failures_raw, list):
            return None
        failures = [int(f) for f in failures_raw if isinstance(f, (int, float)) and 1 <= f <= 5]

        note = str(data.get("note", ""))[:200]

        return GrahamVerdict(verdict=verdict, failures=failures, note=note)
