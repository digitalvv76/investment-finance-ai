"""LLM-based actionability review for borderline push decisions.

Runs as a fast second-opinion check (10s timeout) on cases where the
rule-based signal_score lands in the grey zone (composite 0.30-0.70).

Only ~5-10 calls/day — far cheaper than running ImpactEvaluator on every item.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from openai import OpenAI
from storage.models import NewsItem

logger = logging.getLogger(__name__)

REVIEW_TIMEOUT = 10.0     # fast: 10s vs 45s for ImpactEvaluator
SDK_TIMEOUT = 8.0         # OpenAI SDK timeout

_BORDERLINE_MIN = 0.30
_BORDERLINE_MAX = 0.70

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an investment analyst reviewing whether a news alert should
be pushed to a trader's phone. Your ONLY job is to catch false positives
that the automated system missed.

Reply with EXACTLY ONE WORD: ACTIONABLE or NOT_ACTIONABLE.

The news is ACTIONABLE if ALL of:
- It describes a NEW event (not a recap/summary of something that already happened)
- It describes a concrete ACTION (not a threat/proposal/consideration)
- An investor could TRADE on this right now (specific ticker, sector, or macro instrument)
- If a personnel change, it comes with specific policy implications

The news is NOT_ACTIONABLE if ANY of:
- It's a recap, review, or summary of past events ("monthly review", "year-to-date")
- It's a threat, proposal, or hypothetical ("considering tariffs", "may impose")
- It's purely a personnel appointment without policy action
- It describes a historical event from a different era (2008, 2020, etc.)
- It's about a foreign country's local politics with no global market implication"""

_USER_PROMPT_TEMPLATE = """News: {title}
Source: {source}
Content: {snippet}

Signal scores: composite={composite:.2f}, timeliness={timeliness:.2f}, novelty={novelty:.2f}, relevance={relevance:.2f} ({direction})
Event category: {category}

Is this ACTIONABLE?"""


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------

class ActionabilityReviewer:
    """LLM second opinion for grey-zone push decisions."""

    def __init__(self):
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> Optional[OpenAI]:
        if self._client is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if api_key:
                self._client = OpenAI(
                    api_key=api_key,
                    base_url="https://api.deepseek.com",
                    timeout=SDK_TIMEOUT,
                )
        return self._client

    def should_review(self, composite: float) -> bool:
        """Only review borderline cases — clear signals don't need LLM help."""
        return _BORDERLINE_MIN <= composite <= _BORDERLINE_MAX

    async def review(
        self,
        item: NewsItem,
        signal: dict,
        impact_assessment=None,
    ) -> str:
        """Run LLM actionability check.

        Args:
            item: The news item to review.
            signal: signal_score() output dict (composite, timeliness, novelty, relevance, direction).
            impact_assessment: Optional ImpactAssessment from ImpactEvaluator.

        Returns:
            'ACTIONABLE' | 'NOT_ACTIONABLE' | 'UNSURE' (on timeout/error)
        """
        client = self._get_client()
        if not client:
            logger.debug("ActionabilityReview: no LLM client — skipping")
            return "UNSURE"

        category = ""
        if impact_assessment:
            category = getattr(impact_assessment, 'event_category', '')

        user_prompt = _USER_PROMPT_TEMPLATE.format(
            title=(item.title or "")[:200],
            source=(item.source or "unknown"),
            snippet=(item.content_snippet or "")[:300],
            composite=signal.get("composite", 0),
            timeliness=signal.get("timeliness", 0),
            novelty=signal.get("novelty", 0),
            relevance=signal.get("relevance", 0),
            direction=signal.get("relevance_direction", "none"),
            category=category or "unknown",
        )

        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat.completions.create,
                    model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=10,
                ),
                timeout=REVIEW_TIMEOUT,
            )

            raw = resp.choices[0].message.content.strip().upper()
            if "NOT_ACTIONABLE" in raw:
                return "NOT_ACTIONABLE"
            elif "ACTIONABLE" in raw:
                return "ACTIONABLE"
            else:
                logger.warning("ActionabilityReview: unexpected response: %s", raw[:50])
                return "UNSURE"

        except asyncio.TimeoutError:
            logger.debug("ActionabilityReview: timeout — keeping original decision")
            return "UNSURE"
        except Exception as e:
            logger.debug("ActionabilityReview: error — %s", e)
            return "UNSURE"
