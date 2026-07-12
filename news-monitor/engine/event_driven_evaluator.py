"""Event-driven news evaluator — structured catalyst detection + intensity scoring.

Replaces the old free-form LLM impact scoring with a strict three-step pipeline:
  1. Relevance gate — filter out non-US-equity noise
  2. Catalyst classification — 5 wealth-effect catalyst types
  3. Intensity scoring (1-5 stars) + sector tagging + Chinese trading signal

The output is a structured JSON that directly drives the push/no-push decision:
  is_event=True + intensity>=3 → push; everything else → skip.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openai import OpenAI

if TYPE_CHECKING:
    from storage.models import NewsItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class EventAssessment:
    """Structured output of the event-driven evaluator.

    Maps directly to the LLM JSON response fields.
    """
    is_event: bool = False
    event_types: list[int] = field(default_factory=list)    # catalyst codes 1-5
    intensity: int = 0                                       # 1-5 stars
    sector_tags: list[str] = field(default_factory=list)
    headline_signal: str = ""                                # Chinese trading logic
    ticker_hint: list[str] = field(default_factory=list)
    risk_snapshot: str = ""                                  # Chinese risk point
    notable: bool = False                                    # non-event but substantive action (safety-net)
    direction: str = "up"                                    # up/down/neutral — decoupled from intensity (SPEC-intensity-scale-bear-bias)
    confirmed: bool = False                                  # True only when LLM affirms official/happened; fail-safe: omitted → not confirmed → no siren
    timeliness: str = "immediate"                            # immediate|recent|retrospective_new|retrospective — audit trail for temporal assessment
    filter_reason: str = ""                                  # why filtered (non-event)
    raw_json: str = ""                                       # raw LLM response for audit

    @property
    def should_push(self) -> bool:
        """Only events with intensity >= 3 trigger push (intensity 3 = silent TG)."""
        return self.is_event and self.intensity >= 3

    @property
    def alert_level(self) -> str:
        """Base direction-aware channel level (no escalation — that needs tracked).

        See event_channel_level(). The bearish→critical escalation (tracked
        losers + confirmed) is applied in the pipeline where tracked tickers
        are available.
        """
        if not self.should_push:
            return "normal"
        return event_channel_level(self.intensity, self.direction, confirmed=self.confirmed)

    @classmethod
    def from_json(cls, raw: str) -> EventAssessment:
        """Parse LLM JSON response into EventAssessment. Resilient to malformed JSON."""
        result = cls(raw_json=raw)
        try:
            # Strip any markdown code block wrappers
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
            data = json.loads(cleaned)

            result.is_event = bool(data.get("is_event", False))
            result.event_types = _parse_int_list(data.get("event_types", []))
            result.intensity = int(data.get("intensity", 0))
            result.sector_tags = _parse_str_list(data.get("sector_tags", []))
            result.headline_signal = str(data.get("headline_signal", "")).strip()
            result.ticker_hint = _parse_str_list(data.get("ticker_hint", []))
            result.risk_snapshot = str(data.get("risk_snapshot", "")).strip()
            result.notable = bool(data.get("notable", False))
            result.direction = (str(data.get("direction", "up")).strip().lower() or "up")
            # confirmed defaults False (fail-safe): a phone siren for bearish must
            # be affirmatively justified; omitted field → treated as unconfirmed.
            result.confirmed = bool(data.get("confirmed", False))
            result.timeliness = str(data.get("timeliness", "immediate")).strip().lower()
            # Normalize: only accept known values, default to "immediate"
            if result.timeliness not in ("immediate", "recent", "retrospective_new", "retrospective"):
                result.timeliness = "immediate"
            result.filter_reason = str(data.get("filter_reason", data.get("reason", ""))).strip()
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("EventDrivenEval: JSON parse failed — %s", e)
            result.is_event = False
            result.filter_reason = f"JSON parse error: {e}"
        return result


def event_channel_level(
    intensity: int,
    direction: str,
    *,
    confirmed: bool = False,
    losers: set[str] | None = None,
    tracked: set[str] | None = None,
) -> str:
    """Direction-aware channel mapping (SPEC-intensity-scale-bear-bias §4/§4b).

    FAIL-SAFE toward silence: this is an anti-false-alarm fix, so whenever the
    LLM output is ambiguous/missing a field the mapping errs toward LESS
    alerting (notable/important), never toward a phone siren.

    Intensity measures volatility magnitude (direction-neutral). Channel:
      ★≤2              → normal (no push)
      ★3               → notable (silent TG, NEVER phone) — any direction
      ★4/★5 up         → important / critical (phone) — the bullish siren path
      ★4/★5 down, unconfirmed → notable (silent TG, never phone) — reportedly
                         rumors don't reach the phone even if multi-source bumps
                         intensity (cal-01 anchor).
      ★4/★5 down, confirmed   → important (channel B, no siren), escalating to
                         critical only when it hits tracked money (holdings ∪
                         watchlist).
      neutral / unknown direction → capped at important (no siren).

    ``confirmed`` defaults False: a phone SIREN for a bearish event must be
    affirmatively justified by the LLM, not assumed when the field is omitted.
    """
    direction = (direction or "").strip().lower()
    if intensity < 3:
        return "normal"
    if intensity == 3:
        return "notable"  # silent TG, no phone (phone threshold raised to ≥4)
    # intensity >= 4
    if direction == "down":
        if not confirmed:
            return "notable"  # reportedly/unverified bearish → never phone (cal-01)
        if (losers or set()) & (tracked or set()):
            return "critical"  # confirmed bearish hitting tracked money → siren
        return "important"  # confirmed bearish → phone high-pri (channel B, no siren)
    if direction == "up":
        return "critical" if intensity >= 5 else "important"
    # neutral / empty / unknown → cap at important (no siren) — fail-safe.
    return "important"


def watchlist_safety_net(event_assessment, tracked_tickers: set[str]) -> bool:
    """Non-event news carrying a NOTABLE action on a tracked ticker → rescue.

    Pure function, no side effects (see SPEC-safety-net-pipeline.md §6). Returns
    True iff the sentinel said NOT a hard event, BUT flagged a substantive action
    (notable) on a name the user tracks (watchlist ∪ portfolio). Such items get a
    SILENT Telegram — never the phone.
    """
    ea = event_assessment
    if ea is None or ea.is_event or not getattr(ea, "notable", False):
        return False
    hint = {t.strip().upper() for t in (ea.ticker_hint or []) if t and t.strip()}
    return bool(hint & tracked_tickers)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------



class EventDrivenEvaluator:
    """Call LLM with the event-driven prompt and return structured EventAssessment.

    Uses the same dual-provider pattern as ImpactEvaluator:
      primary: DeepSeek (cheap, fast) → fallback: Anthropic (reliable)
    Temperature=0 for deterministic output.
    """

    HARD_TIMEOUT = 30.0       # shorter than old ImpactEvaluator (45s) — prompt is smaller
    SDK_TIMEOUT = 20.0

    _PROVIDERS = [
        ("DEEPSEEK_API_KEY",   "deepseek",  True,  "https://api.deepseek.com"),
        ("ANTHROPIC_API_KEY",  "anthropic", False, None),
    ]

    _PROMPT_PATH = Path(__file__).resolve().parent.parent / "config" / "prompts" / "event_driven_v1.txt"

    def __init__(self) -> None:
        self._prompt_template: str | None = None
        self._clients: dict[str, object] = {}
        self._last_provider: str = ""

    @property
    def last_provider(self) -> str:
        return self._last_provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(self, item: NewsItem) -> EventAssessment | None:
        """Run event-driven evaluation on a single news item.

        Returns None only when no LLM provider is available.
        Otherwise always returns an EventAssessment (even on LLM failure —
        is_event=False with filter_reason set).
        """
        # Load prompt template lazily
        prompt = self._load_prompt()

        # Fill template
        user_prompt = prompt.replace("{{title}}", item.title or "")
        user_prompt = user_prompt.replace("{{summary}}", (item.content_snippet or "")[:1200])

        providers = self._available_providers()
        if not providers:
            logger.warning("EventDrivenEval: no LLM provider configured")
            return None

        raw = None
        primary = providers[0]
        fallback = providers[1] if len(providers) > 1 else None

        for provider_name in ([primary] + ([fallback] if fallback else [])):
            client = self._get_client(provider_name)
            if not client:
                continue

            for attempt in range(2):
                try:
                    raw = await self._call_llm(client, provider_name, user_prompt)
                    self._last_provider = provider_name
                    break
                except asyncio.TimeoutError:
                    logger.error("EventDrivenEval %s attempt %d: timeout", provider_name, attempt + 1)
                    if attempt == 0:
                        continue
                except Exception as e:
                    logger.error("EventDrivenEval %s attempt %d: %s", provider_name, attempt + 1, e)
                    if attempt == 0:
                        continue
            if raw is not None:
                break

        if raw is None:
            return EventAssessment(
                is_event=False,
                filter_reason="LLM call failed after all retries",
            )

        return EventAssessment.from_json(raw)

    # ------------------------------------------------------------------
    # Internal: prompt
    # ------------------------------------------------------------------

    def _load_prompt(self) -> str:
        if self._prompt_template is not None:
            return self._prompt_template
        try:
            self._prompt_template = self._PROMPT_PATH.read_text(encoding="utf-8")
            logger.info("EventDrivenEval: loaded prompt v1 (%d chars)", len(self._prompt_template))
        except Exception:
            logger.error("EventDrivenEval: cannot load prompt from %s", self._PROMPT_PATH)
            self._prompt_template = "Title: {{title}}\nSummary: {{summary}}\n\nClassify the news."
        return self._prompt_template

    # ------------------------------------------------------------------
    # Internal: LLM
    # ------------------------------------------------------------------

    def _available_providers(self) -> list[str]:
        available = []
        for env_key, name, _, _ in self._PROVIDERS:
            if os.environ.get(env_key, ""):
                available.append(name)
        return available

    def _get_client(self, provider_name: str):
        if provider_name in self._clients:
            return self._clients[provider_name]

        for env_key, name, is_openai, base_url in self._PROVIDERS:
            if name != provider_name:
                continue
            api_key = os.environ.get(env_key, "")
            if not api_key:
                return None
            if is_openai:
                client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=self.SDK_TIMEOUT,
                )
            else:
                import anthropic
                client = anthropic.Anthropic(
                    api_key=api_key,
                    timeout=self.SDK_TIMEOUT,
                )
            self._clients[provider_name] = client
            return client
        return None

    async def _call_llm(self, client, provider_name: str, user_prompt: str) -> str:
        loop = asyncio.get_event_loop()

        if provider_name == "deepseek":
            model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
            return await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    max_tokens=600,
                    timeout=self.SDK_TIMEOUT,
                ).choices[0].message.content,
            )
        else:  # anthropic
            import anthropic
            model = os.environ.get("ANTHROPIC_MODEL", "claude-fable-5")
            resp = await loop.run_in_executor(
                None,
                lambda: client.messages.create(
                    model=model,
                    max_tokens=600,
                    temperature=0,
                    system="You are an event-driven equity analyst. Output ONLY valid JSON, no markdown, no commentary.",
                    messages=[{"role": "user", "content": user_prompt}],
                    timeout=self.SDK_TIMEOUT,
                ),
            )
            return resp.content[0].text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_int_list(val) -> list[int]:
    if not isinstance(val, list):
        return []
    result = []
    for v in val:
        try:
            result.append(int(v))
        except (TypeError, ValueError):
            pass
    return result


def _parse_str_list(val) -> list[str]:
    if not isinstance(val, list):
        return []
    return [str(v).strip() for v in val if str(v).strip()]
