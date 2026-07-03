"""LLM-driven market impact evaluator with data quality, explainability gates,
health monitoring, and prompt version management."""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI
from storage.models import NewsItem, ImpactAssessment, HealthEvent

logger = logging.getLogger(__name__)

# Configured at module load — single prompt file for v1
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "config" / "prompts"


# ---------------------------------------------------------------------------
# Prompt Version Manager
# ---------------------------------------------------------------------------

class PromptVersionManager:
    VERSIONS = {"v1": "impact_v1.txt"}
    ACTIVE = "v1"

    @classmethod
    def load(cls, version: str = None) -> str:
        version = version or cls.ACTIVE
        filename = cls.VERSIONS.get(version, cls.VERSIONS["v1"])
        path = _PROMPT_DIR / filename
        if path.is_file():
            return path.read_text(encoding="utf-8")
        logger.warning("Prompt file %s not found, using v1", path)
        fallback = _PROMPT_DIR / cls.VERSIONS["v1"]
        if fallback.is_file():
            return fallback.read_text(encoding="utf-8")
        return "You are a senior macro analyst..."  # absolute last resort

    @classmethod
    def compare_mae(cls, db) -> dict:
        """Compare MAE by prompt version. Uses db._get_conn() for proper WAL/PRAGMA."""
        result = {}
        with db._get_conn() as conn:
            for version in ["v1", "v2"]:
                row = conn.execute("""
                    SELECT AVG(ABS(a.impact_score - o.actual_score)) as mae,
                           COUNT(*) as n
                    FROM impact_assessments a
                    JOIN impact_outcomes o ON o.assessment_id = a.id
                    WHERE a.prompt_version = ?
                      AND o.actual_score >= 0
                """, (version,)).fetchone()
                if row and row["n"]:
                    result[version] = {"mae": round(row["mae"], 2), "samples": row["n"]}
        return result


# ---------------------------------------------------------------------------
# Data Quality Gate
# ---------------------------------------------------------------------------

def _validate_input(item: NewsItem) -> tuple[bool, str]:
    if not item.title or len(item.title.strip()) < 5:
        return False, "title_too_short"
    if not item.content_snippet or len(item.content_snippet) < 50:
        return False, "content_too_short"
    if "\x00" in item.title:
        return False, "null_byte_in_title"
    return True, "ok"


# ---------------------------------------------------------------------------
# Explainability Gate
# ---------------------------------------------------------------------------

def _validate_output(assessment: ImpactAssessment) -> tuple[bool, list[str]]:
    issues = []
    try:
        chain = json.loads(assessment.reasoning_chain)
    except (json.JSONDecodeError, TypeError):
        chain = []
        issues.append("reasoning_chain not valid JSON")

    if len(chain) != 5:
        issues.append(f"reasoning_chain has {len(chain)} steps, expected 5")
    if any(not step for step in chain):
        issues.append("empty reasoning step")

    if assessment.breadth == "cross_asset" and assessment.impact_score < 30:
        issues.append("cross_asset with low score")
    if assessment.event_category == "monetary" and assessment.impact_score < 20:
        issues.append("monetary event scored too low")

    if assessment.confidence < 40:
        assessment.low_confidence = True

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Health Monitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    ERROR_THRESHOLD = 5

    def __init__(self):
        self._consecutive_failures = 0
        self._last_error = ""
        self._total = 0
        self._success = 0
        self._latencies: list[float] = []

    def record_success(self, latency_ms: float):
        self._total += 1
        self._success += 1
        self._consecutive_failures = 0
        self._latencies.append(latency_ms)
        if len(self._latencies) > 100:
            self._latencies = self._latencies[-100:]

    def record_failure(self, reason: str):
        self._total += 1
        self._consecutive_failures += 1
        self._last_error = reason

    @property
    def health(self) -> dict:
        if self._total == 0:
            return {"status": "healthy", "success_rate_1h": 100,
                    "avg_latency_ms": 0, "consecutive_failures": 0,
                    "last_error": "", "total": 0}
        rate = round(self._success / max(self._total, 1) * 100, 1)
        avg_lat = round(sum(self._latencies) / max(len(self._latencies), 1), 1) if self._latencies else 0
        status = "healthy"
        if self._consecutive_failures >= self.ERROR_THRESHOLD:
            status = "degraded"
        if self._total >= 10 and self._success == 0:
            status = "down"
        return {
            "status": status,
            "success_rate_1h": rate,
            "avg_latency_ms": avg_lat,
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
            "total": self._total,
        }


# ---------------------------------------------------------------------------
# Impact Evaluator
# ---------------------------------------------------------------------------

class ImpactEvaluator:
    THRESHOLD = 0.50
    SDK_TIMEOUT = 30.0
    HARD_TIMEOUT = 45.0

    def __init__(self):
        self.health = HealthMonitor()
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if api_key:
                self._client = OpenAI(
                    api_key=api_key,
                    base_url="https://api.deepseek.com",
                    timeout=self.SDK_TIMEOUT,
                )
        return self._client

    async def evaluate(self, item: NewsItem, market_context: str = "",
                       calibration_hint: str = "",
                       historical_examples: str = "",
                       prompt_version: str = "v1") -> Optional[ImpactAssessment]:
        # 1. Data Quality Gate
        ok, reason = _validate_input(item)
        if not ok:
            logger.info("ImpactEval: quality gate rejected news#%s: %s", item.id, reason)
            return None  # Health event logged by caller

        # 2. Build prompt
        system_prompt = PromptVersionManager.load(prompt_version)
        system_prompt = system_prompt.replace("{market_context}", market_context or "No additional context provided.")
        system_prompt = system_prompt.replace("{calibration_hint}", calibration_hint or "No calibration data yet.")
        system_prompt = system_prompt.replace("{historical_examples}", historical_examples or "No historical examples available.")

        user_prompt = (
            f"Title: {item.title}\n"
            f"Source: {item.source}\n"
            f"Tickers: {item.tickers_found}\n"
            f"Macro tags: {item.macro_tags}\n"
            f"Content: {item.content_snippet[:800]}\n"
        )

        # 3. LLM call with retry (API failures + hard timeout)
        raw = None
        t0 = time.monotonic()
        for attempt in range(2):
            try:
                client = self._get_client()
                if not client:
                    logger.warning("ImpactEval: no LLM client available")
                    self.health.record_failure("no_client")
                    return None

                # Run synchronous OpenAI SDK in a thread to avoid blocking event loop.
                # HARD_TIMEOUT guards against hangs (network dropout, server overload).
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.chat.completions.create,
                        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.3,
                        max_tokens=1200,
                    ),
                    timeout=self.HARD_TIMEOUT,
                )
                raw = resp.choices[0].message.content
                break  # API call succeeded, exit retry loop

            except asyncio.TimeoutError:
                logger.error(
                    "ImpactEval attempt %d: LLM call timed out after %.0fs",
                    attempt + 1, self.HARD_TIMEOUT,
                )
                if attempt == 0:
                    continue  # retry once
                self.health.record_failure("hard_timeout")
                return None

            except Exception as e:
                logger.error("ImpactEval API attempt %d failed: %s", attempt + 1, e)
                if attempt == 0:
                    continue  # retry once
                self.health.record_failure(str(e)[:200])
                return None

        if raw is None:
            return None

        latency = (time.monotonic() - t0) * 1000

        # Parse response (outside retry loop — parse failures are NOT retried)
        try:
            assessment = self._parse_response(raw, prompt_version, int(latency))
            if assessment:
                assessment.news_id = item.id  # assign early for logging
                self.health.record_success(latency)
                return assessment
            else:
                self.health.record_failure("parse_returned_none")
                return None
        except Exception as e:
            logger.error("ImpactEval parse failed: %s", e)
            self.health.record_failure(f"parse_error: {str(e)[:200]}")
            return None

    def _parse_response(self, raw: str, prompt_version: str,
                        latency_ms: int) -> Optional[ImpactAssessment]:
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("ImpactEval: JSON parse failed: %s", e)
            return None

        assessment = ImpactAssessment(
            impact_score=float(data.get("impact_score", 0)),
            confidence=float(data.get("confidence", 0)),
            event_category=str(data.get("event_category", "")),
            surprise_level=str(data.get("surprise_level", "")),
            breadth=str(data.get("breadth", "")),
            reasoning_chain=json.dumps(data.get("reasoning_chain", [])),
            similar_events=json.dumps(data.get("similar_historical_events", [])),
            expected_moves=json.dumps(data.get("expected_asset_moves", {})),
            calibration_note=str(data.get("calibration_note", "")),
            prompt_version=prompt_version,
            latency_ms=latency_ms,
        )

        # Explainability Gate
        ok, issues = _validate_output(assessment)
        if not ok:
            logger.info("ImpactEval: explainability issues for news#%s: %s",
                        assessment.news_id, issues)

        return assessment
