"""MacroAgent — independent macro news evaluator (V2.1).

Detects and evaluates macro-economic indicator releases separately from
the stock-catalyst pipeline.  Macro news (CPI, FOMC, NFP, etc.) uses a
Tier × Deviation matrix instead of the EventDrivenEvaluator's individual-
stock framework.

Design: docs/superpowers/specs/2026-07-15-macro-agent-design.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class MacroAssessment:
    """Output of MacroAgent.evaluate()."""
    is_macro: bool = False
    indicator: str = ""          # "CPI", "FOMC", "PPI", ...
    tier: str = ""               # "A" / "B" / "C"
    actual: str = ""             # release value as string
    expected: str = ""           # consensus as string
    deviation: str = ""          # "slight" / "significant" / "extreme"
    alert_level: str = ""        # "normal" / "notable" / "important"
    headline_signal: str = ""    # Chinese push text with numbers
    risk_snapshot: str = ""      # one-line risk warning


# ---------------------------------------------------------------------------
# MacroAgent
# ---------------------------------------------------------------------------


class MacroAgent:
    """Detect macro-economic news and evaluate via LLM + Tier×Deviation matrix.

    Detection is rule-based (whitelist) for cost efficiency.
    Evaluation is LLM-based for qualitative judgment.

    All failures default to "pass through" — macro news that the agent
    cannot process is forwarded to the standard pipeline.
    """

    def __init__(self):
        self._whitelist: dict[str, tuple[str, re.Pattern]] = {}  # kw → (tier, pattern)
        self._preview_patterns: list[re.Pattern] = []
        self._llm_client = None
        self._llm_model = "deepseek-chat"
        self._prompt = ""
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_loaded(self):
        """Idempotently load config + prompt. Called on first use."""
        if self._loaded:
            return
        self._load_whitelist()
        self._load_prompt()
        self._loaded = True

    def detect(self, title: str, content: str = "") -> Optional[str]:
        """Return the indicator ID if title matches a macro indicator, else None.

        Also returns None for preview/forecast titles (is_macro=false).
        """
        self.ensure_loaded()
        if not title:
            return None

        title_lower = title.lower()

        # Preview check first — forecast articles are NOT macro releases
        for pat in self._preview_patterns:
            if pat.search(title_lower):
                return None

        # Whitelist match
        for kw, (tier, pattern) in self._whitelist.items():
            if pattern.search(title):
                logger.debug("MacroAgent: detected %s (tier=%s) in title: %s",
                             kw, tier, title[:80])
                return kw
        return None

    async def evaluate(self, title: str, content: str = "") -> Optional[MacroAssessment]:
        """Evaluate a macro news item via LLM.

        Returns MacroAssessment on success, None on failure (pass-through).
        """
        self.ensure_loaded()
        if not self._prompt:
            return None

        user_prompt = f"标题：{title}\n\n内容摘要：{content[:1200]}"

        try:
            raw = await self._call_llm(user_prompt)
            return self._parse_response(raw)
        except Exception:
            logger.warning("MacroAgent: evaluation failed, passing through", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_whitelist(self):
        """Load macro indicator keywords from config/macro_indicators.yaml."""
        try:
            config_dir = Path(__file__).resolve().parent.parent / "config"
            path = config_dir / "macro_indicators.yaml"
            if not path.exists():
                logger.info("MacroAgent: macro_indicators.yaml not found")
                return

            import yaml
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            for entry in data.get("indicators", []):
                tier = entry["tier"]
                for kw in entry.get("keywords", []):
                    self._whitelist[kw] = (tier, re.compile(re.escape(kw), re.IGNORECASE))

            for kw in data.get("preview_keywords", []):
                self._preview_patterns.append(re.compile(re.escape(kw), re.IGNORECASE))

            logger.info("MacroAgent: loaded %d indicators + %d preview keywords",
                         len(self._whitelist), len(self._preview_patterns))
        except Exception:
            logger.warning("MacroAgent: failed to load whitelist", exc_info=True)

    def _load_prompt(self):
        """Load macro_eval.txt prompt template."""
        try:
            prompt_dir = Path(__file__).resolve().parent.parent / "config" / "prompts"
            path = prompt_dir / "macro_eval.txt"
            if path.exists():
                self._prompt = path.read_text(encoding="utf-8")
        except Exception:
            logger.warning("MacroAgent: failed to load prompt", exc_info=True)

    async def _call_llm(self, user_prompt: str) -> str:
        """Call DeepSeek LLM. Returns raw response text."""
        if self._llm_client is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if not api_key:
                raise RuntimeError("DEEPSEEK_API_KEY not set")
            from openai import OpenAI
            self._llm_client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com",
            )
            self._llm_model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

        resp = await asyncio.wait_for(
            asyncio.to_thread(
                self._llm_client.chat.completions.create,
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": self._prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=600,
            ),
            timeout=45,
        )
        return resp.choices[0].message.content.strip()

    @staticmethod
    def _parse_response(raw: str) -> Optional[MacroAssessment]:
        """Parse LLM JSON response into MacroAssessment."""
        # Strip markdown code fences
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("MacroAgent: JSON parse failed: %s", raw[:120])
            return None

        if not data.get("is_macro"):
            return MacroAssessment(is_macro=False)

        return MacroAssessment(
            is_macro=True,
            indicator=data.get("indicator", ""),
            tier=data.get("tier", ""),
            actual=data.get("actual", ""),
            expected=data.get("expected", ""),
            deviation=data.get("deviation", ""),
            alert_level=data.get("alert_level", "normal"),
            headline_signal=data.get("headline_signal", ""),
            risk_snapshot=data.get("risk_snapshot", ""),
        )
