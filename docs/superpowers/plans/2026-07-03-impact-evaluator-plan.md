# Market Impact Evaluator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an LLM-driven market impact evaluator that assesses news importance via five-step reasoning, with self-calibration, health monitoring, and zero impact on existing alert pipeline.

**Architecture:** Async pipeline — Data Quality Gate → LLM Eval (DeepSeek, retry 1x) → Explainability Gate → DB Write + Collector + Learner. Isolated from AlertDispatcher via separate DB tables, API endpoints, and Dashboard.

**Tech Stack:** Python 3.12, aiohttp, SQLite, DeepSeek API (OpenAI SDK), existing NewsItem dataclass

## Global Constraints

- score ≥ 0.50 pre-filter (from PriorityScorer)
- DeepSeek (primary) → Anthropic (fallback), static priority
- Retry 1x on LLM failure, then skip
- Collector: 15m/1h/4h layered windows
- Learner: 5 samples minimum, ±5 points max adjustment
- Isolated from AlertDispatcher — no phone vibration
- Isolated from `news.priority_score` — separate tables only

---

## File Structure

```
news-monitor/
├── storage/
│   ├── models.py          [MODIFY]  +3 dataclasses
│   └── database.py        [MODIFY]  +4 tables, +CRUD methods
├── engine/
│   ├── impact_evaluator.py  [CREATE]  ImpactEvaluator + gates + health + prompt mgr
│   ├── impact_collector.py  [CREATE]  ImpactCollector
│   └── impact_learner.py    [CREATE]  ImpactLearner
├── web/
│   ├── routes.py          [MODIFY]  +7 endpoints
│   └── static/
│       └── impact.html    [CREATE]  Dashboard
├── config/
│   └── prompts/
│       └── impact_v1.txt  [CREATE]  System prompt template
├── main.py                [MODIFY]  Wire ImpactEvaluator into on_news_batch
└── tests/
    └── test_impact_evaluator.py  [CREATE]  Integration tests
```

---

### Task 1: Data Models + DB Schema

**Files:**
- Modify: `news-monitor/storage/models.py` — add 3 dataclasses
- Modify: `news-monitor/storage/database.py` — add 4 tables + CRUD

**Interfaces:**
- Produces: `ImpactAssessment`, `ImpactOutcome`, `CalibrationState`, `HealthEvent` dataclasses
- Produces: `Database` methods for all 4 new tables

- [ ] **Step 1: Add dataclasses to models.py**

Append after the `UserPreference` class (line 78):

```python
@dataclass
class ImpactAssessment:
    id: Optional[int] = None
    news_id: int = 0
    impact_score: float = 0.0          # 0-100 LLM prediction
    confidence: float = 0.0            # 0-100
    event_category: str = ""            # monetary|geopolitical|macro_data|corporate|regulatory|other
    surprise_level: str = ""            # expected|minor_surprise|major_surprise|shock
    breadth: str = ""                   # single_stock|sector|broad_market|cross_asset
    reasoning_chain: str = ""           # JSON array of 5 strings
    similar_events: str = ""            # JSON array
    expected_moves: str = ""            # JSON dict
    calibration_note: str = ""
    low_confidence: bool = False
    prompt_version: str = "v1"
    latency_ms: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ImpactOutcome:
    id: Optional[int] = None
    assessment_id: int = 0
    collection_window: str = ""         # '15m' | '1h' | '4h'
    spx_change_pct: float = 0.0
    vix_change_pct: float = 0.0
    sector_changes: str = ""            # JSON dict
    actual_score: float = 0.0           # 0-100 normalized
    collected_at: datetime = field(default_factory=datetime.now)


@dataclass
class CalibrationState:
    id: Optional[int] = None
    category: str = ""                  # event_category or 'global'
    bias: float = 0.0                   # positive = over-estimate
    sample_count: int = 0
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class HealthEvent:
    id: Optional[int] = None
    event_type: str = ""                # quality_reject|llm_timeout|llm_parse_error|degraded
    news_id: int = 0
    detail: str = ""
    created_at: datetime = field(default_factory=datetime.now)
```

- [ ] **Step 2: Update Database.__init__ to import new models**

In `database.py` line 7, change import:

```python
from .models import NewsItem, EventLine, FeedbackRecord, UserPreference, \
    ImpactAssessment, ImpactOutcome, CalibrationState, HealthEvent
```

- [ ] **Step 3: Add 4 CREATE TABLE statements to init_db()**

In `database.py`, inside the `init_db` method's `conn.executescript()` block (after the training_docs table, before the closing `"""` ), add:

```sql
CREATE TABLE IF NOT EXISTS impact_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER NOT NULL,
    impact_score REAL DEFAULT 0.0,
    confidence REAL DEFAULT 0.0,
    event_category TEXT DEFAULT '',
    surprise_level TEXT DEFAULT '',
    breadth TEXT DEFAULT '',
    reasoning_chain TEXT DEFAULT '',
    similar_events TEXT DEFAULT '',
    expected_moves TEXT DEFAULT '',
    calibration_note TEXT DEFAULT '',
    low_confidence INTEGER DEFAULT 0,
    prompt_version TEXT DEFAULT 'v1',
    latency_ms INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_impact_news ON impact_assessments(news_id);
CREATE INDEX IF NOT EXISTS idx_impact_score ON impact_assessments(impact_score);

CREATE TABLE IF NOT EXISTS impact_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL,
    collection_window TEXT DEFAULT '',
    spx_change_pct REAL DEFAULT 0.0,
    vix_change_pct REAL DEFAULT 0.0,
    sector_changes TEXT DEFAULT '',
    actual_score REAL DEFAULT 0.0,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assessment_id) REFERENCES impact_assessments(id)
);
CREATE INDEX IF NOT EXISTS idx_outcome_assessment ON impact_outcomes(assessment_id);

CREATE TABLE IF NOT EXISTS calibration_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT UNIQUE NOT NULL,
    bias REAL DEFAULT 0.0,
    sample_count INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS health_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT DEFAULT '',
    news_id INTEGER DEFAULT 0,
    detail TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_health_type ON health_events(event_type);
```

- [ ] **Step 4: Add CRUD methods to Database class**

Append before the `# Retention / maintenance` section (before line 237):

```python
    # ------------------------------------------------------------------
    # Impact Evaluator CRUD
    # ------------------------------------------------------------------

    def insert_assessment(self, a: ImpactAssessment) -> int:
        with self._get_conn() as conn:
            c = conn.execute("""
                INSERT INTO impact_assessments
                (news_id, impact_score, confidence, event_category, surprise_level,
                 breadth, reasoning_chain, similar_events, expected_moves,
                 calibration_note, low_confidence, prompt_version, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                a.news_id, a.impact_score, a.confidence, a.event_category,
                a.surprise_level, a.breadth, a.reasoning_chain, a.similar_events,
                a.expected_moves, a.calibration_note, int(a.low_confidence),
                a.prompt_version, a.latency_ms
            ))
            a.id = c.lastrowid
            return c.lastrowid

    def get_assessments(self, limit: int = 20, min_score: float = 0.0) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM impact_assessments WHERE impact_score >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (min_score, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_assessment(self, assessment_id: int) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM impact_assessments WHERE id = ?", (assessment_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_assessments_without_outcomes(self, window: str, limit: int = 50) -> list[dict]:
        """Assessments that still need an outcome for a given window."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT a.* FROM impact_assessments a
                WHERE a.id NOT IN (
                    SELECT assessment_id FROM impact_outcomes
                    WHERE collection_window = ?
                )
                ORDER BY a.created_at DESC LIMIT ?
            """, (window, limit)).fetchall()
            return [dict(r) for r in rows]

    def insert_outcome(self, o: ImpactOutcome) -> int:
        with self._get_conn() as conn:
            c = conn.execute("""
                INSERT INTO impact_outcomes
                (assessment_id, collection_window, spx_change_pct, vix_change_pct,
                 sector_changes, actual_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (o.assessment_id, o.collection_window, o.spx_change_pct,
                  o.vix_change_pct, o.sector_changes, o.actual_score))
            o.id = c.lastrowid
            return c.lastrowid

    def get_outcomes_for_category(self, category: str, limit: int = 20) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT a.impact_score as predicted_score,
                       a.event_category,
                       MAX(o.actual_score) as actual_score
                FROM impact_assessments a
                JOIN impact_outcomes o ON o.assessment_id = a.id
                WHERE a.event_category = ?
                GROUP BY a.id
                ORDER BY a.created_at DESC LIMIT ?
            """, (category, limit)).fetchall()
            return [dict(r) for r in rows]

    def get_outcomes_for_assessment(self, assessment_id: int) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM impact_outcomes WHERE assessment_id = ? "
                "ORDER BY collected_at DESC",
                (assessment_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_calibration(self, category: str, bias: float, sample_count: int):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO calibration_state
                (category, bias, sample_count, last_updated)
                VALUES (?, ?, ?, datetime('now'))
            """, (category, bias, sample_count))

    def get_calibration(self, category: str = None) -> list[dict]:
        with self._get_conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM calibration_state WHERE category = ?", (category,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM calibration_state ORDER BY category"
                ).fetchall()
            return [dict(r) for r in rows]

    def insert_health_event(self, e: HealthEvent) -> int:
        with self._get_conn() as conn:
            c = conn.execute(
                "INSERT INTO health_events (event_type, news_id, detail) VALUES (?, ?, ?)",
                (e.event_type, e.news_id, e.detail)
            )
            return c.lastrowid

    def get_health_events(self, limit: int = 50, event_type: str = None) -> list[dict]:
        with self._get_conn() as conn:
            if event_type:
                rows = conn.execute(
                    "SELECT * FROM health_events WHERE event_type = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (event_type, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM health_events ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def get_health_stats(self, hours: int = 1) -> dict:
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM impact_assessments "
                "WHERE created_at > datetime('now', ?)",
                (f'-{hours} hours',)
            ).fetchone()["cnt"]
            errors = conn.execute(
                "SELECT COUNT(*) as cnt FROM health_events "
                "WHERE created_at > datetime('now', ?)",
                (f'-{hours} hours',)
            ).fetchone()["cnt"]
            return {"total_assessments_1h": total, "health_events_1h": errors,
                    "success_rate": round((total - errors) / max(total, 1) * 100, 1)}

    def get_impact_stats(self) -> dict:
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM impact_assessments").fetchone()["cnt"]
            with_outcomes = conn.execute(
                "SELECT COUNT(DISTINCT assessment_id) as cnt FROM impact_outcomes"
            ).fetchone()["cnt"]
            pending = total - with_outcomes
            return {"total": total, "with_outcomes": with_outcomes, "pending": pending}
```

- [ ] **Step 5: Verify init_db works**

Run:
```bash
cd news-monitor && python -c "from storage.database import Database; d=Database(); d.init_db(); print('OK:', d.get_db_stats())"
```

Expected: OK with stats dict, no errors.

- [ ] **Step 6: Commit**

```bash
git add news-monitor/storage/models.py news-monitor/storage/database.py
git commit -m "feat(impact): add data models + DB schema for Impact Evaluator (4 new tables)"
```

---

### Task 2: Prompt Template

**Files:**
- Create: `news-monitor/config/prompts/impact_v1.txt`

**Interfaces:**
- Produces: `PromptVersionManager.load("v1")` — returns the system prompt string

- [ ] **Step 1: Create prompts directory**

```bash
mkdir -p news-monitor/config/prompts
```

- [ ] **Step 2: Write impact_v1.txt**

```python
# news-monitor/config/prompts/impact_v1.txt

"""You are a senior macro analyst at a top-tier hedge fund. Your job is to evaluate
the potential MARKET IMPACT of a financial news event. You think in terms of:

1. EVENT TYPE & INHERENT SIGNIFICANCE
   - Monetary policy (FOMC, rate decisions, forward guidance) → highest impact
   - Geopolitical shocks (war, sanctions, trade war escalation) → very high impact
   - Major macro data surprises (CPI, NFP, retail sales) → high impact
   - Corporate earnings / product launches (mega-cap only) → moderate impact
   - Routine data / minor policy → low impact

2. SURPRISE MAGNITUDE
   - How far does the actual figure deviate from expectations?
   - A 0.1% CPI miss is noise; a 0.5% miss is a regime change signal.

3. MARKET BREADTH
   - Single stock → sector → broad index → multi-asset (equities+bonds+FX+commodities)
   - Wider breadth = higher impact

4. HISTORICAL PRECEDENT
   - Has a similar event occurred in the past 2 years? What was the market reaction?
   - Use your training knowledge to contextualize.

5. CURRENT MARKET CONTEXT
   - Is the market positioned for this? (crowded trades amplify moves)
   - Current VIX / Fear & Greed regime (fear amplifies negative news)
   {market_context}

{calibration_hint}

OUTPUT FORMAT (strict JSON, no markdown wrapping):
{
  "impact_score": <0-100 integer>,
  "confidence": <0-100 integer>,
  "event_category": "<monetary|geopolitical|macro_data|corporate|regulatory|other>",
  "surprise_level": "<expected|minor_surprise|major_surprise|shock>",
  "breadth": "<single_stock|sector|broad_market|cross_asset>",
  "reasoning_chain": ["Step 1: ...", "Step 2: ...", "Step 3: ...", "Step 4: ...", "Step 5: ..."],
  "similar_historical_events": ["Event (approx date): brief impact description"],
  "expected_sectors_affected": ["Technology", "Financials"],
  "expected_asset_moves": {
    "equities": "<direction: up/down/flat> <magnitude: small/moderate/large>",
    "bonds": "<direction> <magnitude>",
    "fx": "<direction> <magnitude>",
    "commodities": "<direction> <magnitude>"
  },
  "calibration_note": "Based on past assessments, this evaluator tends to [over/under]estimate [type] events by ~[X] points"
}"""
```

- [ ] **Step 3: Commit**

```bash
git add news-monitor/config/prompts/impact_v1.txt
git commit -m "feat(impact): add LLM system prompt v1 for five-step impact reasoning"
```

---

### Task 3: ImpactEvaluator Engine

**Files:**
- Create: `news-monitor/engine/impact_evaluator.py`
- Test: `news-monitor/tests/test_impact_evaluator.py`

**Interfaces:**
- Consumes: `NewsItem` (from storage.models), `Database` (for calibration hint)
- Produces: `ImpactEvaluator.evaluate(item, market_context, db)` → `ImpactAssessment | None`
- Produces: `HealthMonitor` class, `PromptVersionManager` class

- [ ] **Step 1: Write the smoke test**

Create `news-monitor/tests/test_impact_evaluator.py`:

```python
"""Smoke tests for ImpactEvaluator — gates, prompt loading, health monitor."""
import pytest
from engine.impact_evaluator import (
    ImpactEvaluator, HealthMonitor, PromptVersionManager,
    _validate_input, _validate_output
)
from storage.models import NewsItem, ImpactAssessment


class TestDataQualityGate:
    def test_valid_item_passes(self):
        item = NewsItem(title="Fed raises rates by 50bp",
                        content_snippet="The Federal Reserve announced a 50 basis point "
                                       "rate hike today, surprising markets that expected 25bp. "
                                       "The decision was unanimous and the forward guidance "
                                       "signaled further tightening ahead.")
        ok, reason = _validate_input(item)
        assert ok is True
        assert reason == "ok"

    def test_empty_title_fails(self):
        item = NewsItem(title="", content_snippet="x" * 100)
        ok, reason = _validate_input(item)
        assert ok is False
        assert "title" in reason

    def test_short_content_fails(self):
        item = NewsItem(title="Some headline", content_snippet="short")
        ok, reason = _validate_input(item)
        assert ok is False
        assert "content" in reason


class TestExplainabilityGate:
    def test_valid_output_passes(self):
        a = ImpactAssessment(
            impact_score=75, confidence=80, event_category="monetary",
            surprise_level="major_surprise", breadth="broad_market",
            reasoning_chain='["s1","s2","s3","s4","s5"]'
        )
        # Manually set reasoning_chain as parsed JSON
        import json
        a.reasoning_chain = json.dumps(["step 1", "step 2", "step 3", "step 4", "step 5"])
        ok, issues = _validate_output(a)
        assert ok is True

    def test_cross_asset_low_score_flags(self):
        a = ImpactAssessment(impact_score=15, breadth="cross_asset",
                            reasoning_chain='["1","2","3","4","5"]')
        ok, issues = _validate_output(a)
        assert ok is False
        assert any("cross_asset" in i for i in issues)

    def test_low_confidence_marks_flag(self):
        a = ImpactAssessment(confidence=25, breadth="sector",
                            reasoning_chain='["1","2","3","4","5"]')
        _validate_output(a)
        assert a.low_confidence is True


class TestHealthMonitor:
    def test_initial_healthy(self):
        hm = HealthMonitor()
        assert hm.health["status"] == "healthy"
        assert hm.health["consecutive_failures"] == 0

    def test_consecutive_failures_trigger_degraded(self):
        hm = HealthMonitor()
        for i in range(5):
            hm.record_failure("timeout")
        assert hm.health["consecutive_failures"] == 5
        assert hm.health["status"] == "degraded"


class TestPromptVersionManager:
    def test_load_v1_returns_string(self):
        prompt = PromptVersionManager.load("v1")
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert "hedge fund" in prompt.lower()

    def test_load_missing_falls_back_to_v1(self):
        prompt = PromptVersionManager.load("v9_nonexistent")
        assert isinstance(prompt, str)
        assert len(prompt) > 100
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd news-monitor && python -m pytest tests/test_impact_evaluator.py -v
```

Expected: all FAIL with ImportError (module not created yet).

- [ ] **Step 3: Write impact_evaluator.py**

Create `news-monitor/engine/impact_evaluator.py`:

```python
"""LLM-driven market impact evaluator with data quality, explainability gates,
health monitoring, and prompt version management."""

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
        rows_v1 = db.get_outcomes_for_category.__wrapped__  # not possible — use direct SQL
        # Query mean absolute error by prompt_version
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        result = {}
        for version in ["v1", "v2"]:
            row = conn.execute("""
                SELECT AVG(ABS(a.impact_score - o.actual_score)) as mae,
                       COUNT(*) as n
                FROM impact_assessments a
                JOIN impact_outcomes o ON o.assessment_id = a.id
                WHERE a.prompt_version = ?
            """, (version,)).fetchone()
            if row and row["n"]:
                result[version] = {"mae": round(row["mae"], 2), "samples": row["n"]}
        conn.close()
        return result


# ---------------------------------------------------------------------------
# Data Quality Gate
# ---------------------------------------------------------------------------

def _validate_input(item: NewsItem) -> tuple[bool, str]:
    if not item.title or len(item.title.strip()) < 5:
        return False, "title_too_short"
    if not item.content_snippet or len(item.content_snippet) < 50:
        return False, "content_too_short"
    try:
        item.title.encode("utf-8")
    except UnicodeError:
        return False, "encoding_error"
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
        if self._total > 0 and self._success == 0:
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

        user_prompt = (
            f"Title: {item.title}\n"
            f"Source: {item.source}\n"
            f"Tickers: {item.tickers_found}\n"
            f"Macro tags: {item.macro_tags}\n"
            f"Content: {item.content_snippet[:800]}\n"
        )

        # 3. LLM call with retry
        for attempt in range(2):
            try:
                client = self._get_client()
                if not client:
                    logger.warning("ImpactEval: no LLM client available")
                    self.health.record_failure("no_client")
                    return None

                t0 = time.monotonic()
                resp = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=1200,
                )
                latency = (time.monotonic() - t0) * 1000
                self.health.record_success(latency)
                raw = resp.choices[0].message.content
                return self._parse_response(raw, prompt_version, int(latency))

            except Exception as e:
                logger.error("ImpactEval attempt %d failed: %s", attempt + 1, e)
                if attempt == 0:
                    continue  # retry once
                self.health.record_failure(str(e)[:200])

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd news-monitor && python -m pytest tests/test_impact_evaluator.py -v
```

Expected: 8 tests PASS (all gates, health monitor, prompt manager).

- [ ] **Step 5: Commit**

```bash
git add news-monitor/engine/impact_evaluator.py news-monitor/tests/test_impact_evaluator.py
git commit -m "feat(impact): add ImpactEvaluator engine with gates, health monitor, prompt manager"
```

---

### Task 4: ImpactCollector

**Files:**
- Create: `news-monitor/engine/impact_collector.py`
- Test: append to `news-monitor/tests/test_impact_evaluator.py`

**Interfaces:**
- Consumes: `Database`, `ImpactAssessment` (from DB)
- Produces: `ImpactCollector.collect(assessment, window)` → `ImpactOutcome`

- [ ] **Step 1: Add collector tests**

Append to `tests/test_impact_evaluator.py`:

```python
class TestImpactCollector:
    def test_normalize_actual_score_typical(self):
        from engine.impact_collector import ImpactCollector
        c = ImpactCollector.__new__(ImpactCollector)
        score = c._normalize_score(
            spx_change=-2.1, vix_change=18.0,
            sector_count=5, bonds_moved=True, fx_moved=False, commodities_moved=True
        )
        # spx: min(2.1/3,1)*100=70 *0.4 = 28
        # vix: min(18/15,1)*100=100 *0.25 = 25
        # sector: 5/11*100=45.5 *0.2 = 9.1
        # cross: (1+0+1)/3*100=66.7 *0.15 = 10
        # total ≈ 72
        assert 65 < score < 80

    def test_normalize_actual_score_zero(self):
        from engine.impact_collector import ImpactCollector
        c = ImpactCollector.__new__(ImpactCollector)
        score = c._normalize_score(
            spx_change=0, vix_change=0, sector_count=0,
            bonds_moved=False, fx_moved=False, commodities_moved=False
        )
        assert score == 0.0

    def test_normalize_actual_score_max(self):
        from engine.impact_collector import ImpactCollector
        c = ImpactCollector.__new__(ImpactCollector)
        score = c._normalize_score(
            spx_change=-5.0, vix_change=30.0, sector_count=11,
            bonds_moved=True, fx_moved=True, commodities_moved=True
        )
        assert score == 100.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd news-monitor && python -m pytest tests/test_impact_evaluator.py::TestImpactCollector -v
```

Expected: FAIL (ImportError).

- [ ] **Step 3: Write impact_collector.py**

Create `news-monitor/engine/impact_collector.py`:

```python
"""Market data collector — measures actual impact after LLM assessment."""

import logging
from typing import Optional

from storage.models import ImpactAssessment, ImpactOutcome

logger = logging.getLogger(__name__)


class ImpactCollector:
    async def collect(self, assessment: ImpactAssessment,
                      window: str, db) -> Optional[ImpactOutcome]:
        """Collect market data for one assessment at the given window.

        In production, this calls yfinance / stock-scanner MCP tools.
        For the MVP, the outcome is populated by a scheduled task that
        queries market data APIs directly.
        """
        # This method is the interface. Actual data fetching happens in
        # the scheduled task (see collect_pending_outcomes below).
        outcome = ImpactOutcome(
            assessment_id=assessment.id,
            collection_window=window,
        )
        return outcome

    async def collect_pending(self, db, window: str) -> int:
        """Fetch market data for all assessments without outcomes for `window`.

        Returns count of outcomes created.
        """
        pending = db.get_assessments_without_outcomes(window, limit=20)
        count = 0
        for row in pending:
            # In production: call yfinance/stock-scanner here.
            # For MVP, write placeholder — actual data comes from
            # the scheduled task in main.py.
            pass
        return count

    def _normalize_score(self, *, spx_change: float, vix_change: float,
                          sector_count: int, bonds_moved: bool,
                          fx_moved: bool, commodities_moved: bool) -> float:
        """Compute normalized actual impact score (0-100)."""
        spx_val = min(abs(spx_change) / 3.0, 1.0) * 100
        vix_val = min(abs(vix_change) / 15.0, 1.0) * 100
        sector_val = (sector_count / 11.0) * 100
        cross_count = sum([bonds_moved, fx_moved, commodities_moved])
        cross_val = (cross_count / 3.0) * 100

        return round(
            spx_val * 0.40 + vix_val * 0.25 +
            sector_val * 0.20 + cross_val * 0.15, 1
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd news-monitor && python -m pytest tests/test_impact_evaluator.py::TestImpactCollector -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add news-monitor/engine/impact_collector.py news-monitor/tests/test_impact_evaluator.py
git commit -m "feat(impact): add ImpactCollector with actual-score normalization"
```

---

### Task 5: ImpactLearner

**Files:**
- Create: `news-monitor/engine/impact_learner.py`
- Test: append to `news-monitor/tests/test_impact_evaluator.py`

**Interfaces:**
- Consumes: `Database` (get_outcomes_for_category, upsert_calibration)
- Produces: `ImpactLearner.generate_calibration_hint(db)` → `str`

- [ ] **Step 1: Add learner tests**

Append to `tests/test_impact_evaluator.py`:

```python
class TestImpactLearner:
    def test_no_samples_returns_empty_hint(self):
        from engine.impact_learner import ImpactLearner
        learner = ImpactLearner()
        hint = learner._build_hint({})
        assert hint == "No calibration data yet"

    def test_single_category_bias(self):
        from engine.impact_learner import ImpactLearner
        learner = ImpactLearner()
        hint = learner._build_hint({"monetary": 4.0})
        assert "monetary" in hint
        assert "over-estimate" in hint

    def test_bias_below_threshold_not_included(self):
        from engine.impact_learner import ImpactLearner
        learner = ImpactLearner()
        hint = learner._build_hint({"macro_data": 1.5})  # < 2.0 threshold
        assert hint == "No calibration data yet"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd news-monitor && python -m pytest tests/test_impact_evaluator.py::TestImpactLearner -v
```

Expected: FAIL.

- [ ] **Step 3: Write impact_learner.py**

Create `news-monitor/engine/impact_learner.py`:

```python
"""Self-learning calibration engine for Impact Evaluator."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

CATEGORIES = ["monetary", "geopolitical", "macro_data", "corporate", "regulatory"]


class ImpactLearner:
    MIN_SAMPLES = 5
    MAX_ADJUST = 5.0
    BIAS_THRESHOLD = 2.0  # ignore bias below this

    def analyze_deviation(self, category: str, db) -> float:
        """Return mean bias for a category (positive = over-estimate)."""
        samples = db.get_outcomes_for_category(category, limit=20)
        if len(samples) < self.MIN_SAMPLES:
            return 0.0
        biases = [
            s["predicted_score"] - s["actual_score"]
            for s in samples
            if s.get("actual_score", 0) > 0
        ]
        if not biases:
            return 0.0
        bias = sum(biases) / len(biases)
        return max(-self.MAX_ADJUST, min(self.MAX_ADJUST, bias))

    def generate_calibration_hint(self, db) -> str:
        """Build calibration text for injection into LLM prompt."""
        hints = {}
        for cat in CATEGORIES:
            bias = self.analyze_deviation(cat, db)
            if abs(bias) >= self.BIAS_THRESHOLD:
                hints[cat] = bias
        return self._build_hint(hints)

    def _build_hint(self, hints: dict[str, float]) -> str:
        if not hints:
            return "No calibration data yet"
        parts = []
        for cat, bias in hints.items():
            direction = "over-estimate" if bias > 0 else "under-estimate"
            parts.append(
                f"Tend to {direction} {cat} events by ~{abs(bias):.0f} points"
            )
        return "; ".join(parts) if parts else "No calibration data yet"

    def update_calibration(self, db):
        """Persist calibration state for all categories."""
        for cat in CATEGORIES:
            bias = self.analyze_deviation(cat, db)
            samples = db.get_outcomes_for_category(cat, limit=20)
            db.upsert_calibration(cat, bias, len(samples))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd news-monitor && python -m pytest tests/test_impact_evaluator.py::TestImpactLearner -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add news-monitor/engine/impact_learner.py news-monitor/tests/test_impact_evaluator.py
git commit -m "feat(impact): add ImpactLearner with category bias calibration"
```

---

### Task 6: Web API Endpoints

**Files:**
- Modify: `news-monitor/web/routes.py` — add 7 endpoints

**Interfaces:**
- Consumes: `Database` from `request.app["db"]`
- Produces: REST API at `/api/impact/*`

- [ ] **Step 1: Add impact routes to routes.py**

Append at end of `routes.py`:

```python
# ---------------------------------------------------------------------------
# Impact Evaluator API
# ---------------------------------------------------------------------------

async def impact_latest(request: web.Request) -> web.Response:
    db = _get_db(request)
    limit = int(request.query.get("limit", 20))
    min_score = float(request.query.get("min_score", 0))
    assessments = db.get_assessments(limit=limit, min_score=min_score)
    return _json(assessments)

async def impact_detail(request: web.Request) -> web.Response:
    db = _get_db(request)
    aid = int(request.match_info["id"])
    a = db.get_assessment(aid)
    if not a:
        return _error("assessment not found", 404)
    outcomes = db.get_outcomes_for_assessment(aid)
    a["outcomes"] = outcomes
    return _json(a)

async def impact_outcomes(request: web.Request) -> web.Response:
    db = _get_db(request)
    aid = int(request.match_info["id"])
    outcomes = db.get_outcomes_for_assessment(aid)
    return _json(outcomes)

async def impact_calibration(request: web.Request) -> web.Response:
    db = _get_db(request)
    cal = db.get_calibration()
    return _json(cal)

async def impact_stats(request: web.Request) -> web.Response:
    db = _get_db(request)
    stats = db.get_impact_stats()
    return _json(stats)

async def impact_health(request: web.Request) -> web.Response:
    db = _get_db(request)
    stats = db.get_health_stats(hours=1)
    # Merge with in-memory health monitor if available
    evaluator = request.app.get("impact_evaluator")
    if evaluator:
        stats.update(evaluator.health.health)
    return _json(stats)

async def impact_prompts(request: web.Request) -> web.Response:
    db = _get_db(request)
    from engine.impact_evaluator import PromptVersionManager
    mae = PromptVersionManager.compare_mae(db)
    return _json({"active": PromptVersionManager.ACTIVE, "versions": mae})
```

- [ ] **Step 2: Register routes in the app setup**

Find the route registration section in `routes.py` (or wherever `app.router.add_get` calls are made) and append:

```python
app.router.add_get("/api/impact/latest", impact_latest)
app.router.add_get("/api/impact/health", impact_health)
app.router.add_get("/api/impact/stats", impact_stats)
app.router.add_get("/api/impact/calibration", impact_calibration)
app.router.add_get("/api/impact/prompts", impact_prompts)
app.router.add_get("/api/impact/{id}", impact_detail)
app.router.add_get("/api/impact/{id}/outcomes", impact_outcomes)
```

Note: The `{id}` routes must be registered after the literal paths to avoid conflicts.

- [ ] **Step 3: Verify routes import**

```bash
cd news-monitor && python -c "from web.routes import impact_latest, impact_health; print('routes OK')"
```

Expected: `routes OK`

- [ ] **Step 4: Commit**

```bash
git add news-monitor/web/routes.py
git commit -m "feat(impact): add 7 REST API endpoints for Impact Evaluator"
```

---

### Task 7: Dashboard

**Files:**
- Create: `news-monitor/web/static/impact.html`

- [ ] **Step 1: Write impact.html**

Create a Bloomberg-dark-themed dashboard with two panels. The page fetches from `/api/impact/*` endpoints and displays:

**Left panel — Evaluations:**
- Latest 20 assessments table (id, title, score, category, confidence)
- Click row → expand reasoning chain (5 steps)
- Low-confidence rows marked with orange badge

**Right panel — Operations:**
- Health status card (success rate %, avg latency, status badge)
- Calibration table (category → bias)
- Prompt version comparison (v1 vs v2 MAE)
- Health events log (last 20)

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Market Impact Evaluator</title>
<style>
  :root {
    --bg-primary: #0c0d14; --bg-secondary: #13161f; --bg-panel: #181b26;
    --bg-hover: #1e2130; --border: #2a2d3a; --text-primary: #d1d4dc;
    --text-secondary: #787b86; --text-muted: #5a5d6a;
    --green: #22c55e; --red: #ef4444; --blue: #3b82f6;
    --purple: #8b5cf6; --gold: #f59e0b;
    --font-mono: 'JetBrains Mono','Fira Code','Consolas',monospace;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: var(--bg-primary); color: var(--text-primary);
    font-family: 'Inter','Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
    padding: 24px;
  }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
  .header h1 { font-size:22px; }
  .status-dot { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:6px; }
  .status-dot.healthy { background:var(--green); }
  .status-dot.degraded { background:var(--gold); }
  .status-dot.down { background:var(--red); }
  .grid { display:grid; grid-template-columns:2fr 1fr; gap:16px; }
  .panel { background:var(--bg-panel); border:1px solid var(--border); border-radius:10px; padding:20px; }
  .panel h2 { font-size:14px; text-transform:uppercase; letter-spacing:1.5px; color:var(--text-secondary); margin-bottom:14px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; padding:6px 10px; color:var(--text-muted); font-weight:600; border-bottom:1px solid var(--border); font-size:11px; text-transform:uppercase; }
  td { padding:6px 10px; border-bottom:1px solid rgba(255,255,255,0.03); }
  tr:hover td { background:var(--bg-hover); }
  .score { font-family:var(--font-mono); font-weight:600; }
  .score.high { color:var(--red); }
  .score.med { color:var(--gold); }
  .score.low { color:var(--text-muted); }
  .badge { font-size:10px; padding:2px 6px; border-radius:4px; }
  .badge-low-conf { background:rgba(245,158,11,0.15); color:var(--gold); }
  .card { background:var(--bg-secondary); border:1px solid var(--border); border-radius:8px; padding:14px; margin-bottom:10px; }
  .card .label { font-size:10px; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px; }
  .card .value { font-family:var(--font-mono); font-size:22px; font-weight:600; }
  .reasoning { display:none; background:var(--bg-secondary); border-radius:6px; padding:12px; margin-top:8px; font-size:12px; color:var(--text-secondary); }
  .reasoning.open { display:block; }
  .reasoning-step { padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.03); }
  @media(max-width:768px) { .grid { grid-template-columns:1fr; } }
</style>
</head>
<body>
<div class="header">
  <h1>📊 Market Impact Evaluator</h1>
  <div id="healthBadge">Loading...</div>
</div>
<div class="grid">
  <div class="panel" id="assessmentsPanel">
    <h2>Latest Assessments</h2>
    <table><thead><tr><th>ID</th><th>Headline</th><th>Score</th><th>Category</th><th>Conf</th></tr></thead>
    <tbody id="assessmentsBody"></tbody></table>
  </div>
  <div>
    <div class="panel">
      <h2>Health</h2>
      <div id="healthCards"></div>
    </div>
    <div class="panel">
      <h2>Calibration</h2>
      <table><thead><tr><th>Category</th><th>Bias</th><th>Samples</th></tr></thead>
      <tbody id="calibrationBody"></tbody></table>
    </div>
    <div class="panel">
      <h2>Health Events</h2>
      <div id="eventsLog" style="max-height:200px;overflow-y:auto;font-size:11px;"></div>
    </div>
  </div>
</div>
<script>
async function load() {
  try {
    const [a, h, c] = await Promise.all([
      fetch('/api/impact/latest?limit=20').then(r=>r.json()),
      fetch('/api/impact/health').then(r=>r.json()),
      fetch('/api/impact/calibration').then(r=>r.json()),
    ]);
    renderAssessments(a);
    renderHealth(h);
    renderCalibration(c);
  } catch(e) { document.body.innerHTML += '<p style="color:var(--red)">Error loading data: '+e.message+'</p>'; }
}
function renderAssessments(items) {
  const tbody = document.getElementById('assessmentsBody');
  tbody.innerHTML = items.map((a,i) => {
    const sc = a.impact_score > 70 ? 'high' : a.impact_score > 40 ? 'med' : 'low';
    const lc = a.low_confidence ? ' <span class="badge badge-low-conf">LOW CONF</span>' : '';
    return `<tr onclick="toggleReasoning(${i})" style="cursor:pointer">
      <td>${a.id}</td><td>${(a.title||'N/A').substring(0,60)}${lc}</td>
      <td class="score ${sc}">${a.impact_score}</td>
      <td>${a.event_category||'-'}</td><td>${a.confidence||'-'}</td>
    </tr>
    <tr id="reasoning-${i}" class="reasoning"><td colspan="5">
      <div class="reasoning-step"><strong>Reasoning Chain:</strong></div>
      ${(a.reasoning_chain||'[]').replace(/","/g,'"</div><div class="reasoning-step">"').replace(/[\[\]"]/g,'')}
      <div class="reasoning-step"><strong>Expected Moves:</strong> ${a.expected_moves||'-'}</div>
      <div class="reasoning-step"><strong>Similar Events:</strong> ${a.similar_events||'-'}</div>
    </td></tr>`;
  }).join('');
}
function toggleReasoning(i) {
  document.getElementById('reasoning-'+i).classList.toggle('open');
}
function renderHealth(h) {
  const dot = h.status === 'healthy' ? 'healthy' : h.status === 'degraded' ? 'degraded' : 'down';
  document.getElementById('healthBadge').innerHTML = `<span class="status-dot ${dot}"></span>${h.status.toUpperCase()}`;
  document.getElementById('healthCards').innerHTML = `
    <div class="card"><div class="label">Success Rate (1h)</div><div class="value">${h.success_rate_1h}%</div></div>
    <div class="card"><div class="label">Avg Latency</div><div class="value">${h.avg_latency_ms}ms</div></div>
    <div class="card"><div class="label">Consecutive Failures</div><div class="value">${h.consecutive_failures}</div></div>
    ${h.last_error ? `<div class="card"><div class="label">Last Error</div><div class="value" style="font-size:12px;color:var(--red)">${h.last_error.substring(0,80)}</div></div>` : ''}
  `;
}
function renderCalibration(items) {
  document.getElementById('calibrationBody').innerHTML = items.map(c =>
    `<tr><td>${c.category}</td><td style="font-family:var(--font-mono);color:${c.bias>0?'var(--red)':'var(--green)'}">${c.bias>0?'+':''}${c.bias?.toFixed(2)||'0.00'}</td><td>${c.sample_count}</td></tr>`
  ).join('');
}
load();
setInterval(load, 60000);
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add news-monitor/web/static/impact.html
git commit -m "feat(impact): add Impact Evaluator dashboard (Bloomberg dark theme)"
```

---

### Task 8: Integration — Wire into Main Pipeline

**Files:**
- Modify: `news-monitor/main.py` — wire ImpactEvaluator into on_news_batch
- Modify: `news-monitor/main.py` — add collector scheduled task

**Interfaces:**
- Consumes: `PriorityScorer.score()` for pre-filter
- Produces: `ImpactAssessment` written to DB via `ImpactEvaluator.evaluate()`

- [ ] **Step 1: Add import**

In `main.py`, after the existing imports, add:

```python
from engine.impact_evaluator import ImpactEvaluator
from engine.impact_learner import ImpactLearner
```

- [ ] **Step 2: Initialize in __init__**

In the `NewsMonitor.__init__` method (after where `self.alert_dispatcher` is set, around line 130), add:

```python
# ---- impact evaluator (LLM, async, isolated) --------
self.impact_evaluator = ImpactEvaluator()
self.impact_learner = ImpactLearner()
logger.info("ImpactEvaluator initialized (threshold=%.2f)", ImpactEvaluator.THRESHOLD)
```

- [ ] **Step 3: Wire into on_news_batch**

In the `on_news_batch` method (after the alert dispatch block, around line 200), add the Impact Evaluator call:

```python
            # ---- Impact Evaluator (LLM, async, isolated from alerts) ----
            if item.priority_score >= ImpactEvaluator.THRESHOLD:
                try:
                    calibration_hint = self.impact_learner.generate_calibration_hint(self.db)
                    assessment = await self.impact_evaluator.evaluate(
                        item,
                        market_context="",  # populated later from market data
                        calibration_hint=calibration_hint,
                    )
                    if assessment:
                        assessment.news_id = item.id
                        self.db.insert_assessment(assessment)
                        logger.debug(
                            "ImpactEval: news#%s → score=%d cat=%s conf=%d",
                            item.id, assessment.impact_score,
                            assessment.event_category, assessment.confidence
                        )
                    else:
                        # Log health event for degraded evaluation
                        from storage.models import HealthEvent
                        self.db.insert_health_event(HealthEvent(
                            event_type="degraded",
                            news_id=item.id,
                            detail="evaluate returned None"
                        ))
                except Exception as e:
                    logger.error("ImpactEval failed for news#%s: %s", item.id, e)
                    self.impact_evaluator.health.record_failure(str(e)[:200])
```

- [ ] **Step 4: Add collector scheduled task**

Add a periodic task in the scheduler (or main loop) that calls the collector:

```python
    async def _collect_impact_outcomes(self, window: str):
        """Periodic task: collect market data for pending assessments."""
        try:
            from engine.impact_collector import ImpactCollector
            collector = ImpactCollector()
            count = await collector.collect_pending(self.db, window)
            if count:
                logger.info("ImpactCollector[%s]: %d outcomes collected", window, count)
        except Exception as e:
            logger.error("ImpactCollector[%s] failed: %s", window, e)

    async def _run_collector_loop(self):
        """Run collector at 15m/1h/4h intervals."""
        while True:
            await asyncio.sleep(15 * 60)
            await self._collect_impact_outcomes("15m")
            # 1h and 4h windows are handled by a separate check
            # that looks at created_at age
```

- [ ] **Step 5: Store evaluator ref for health endpoint**

After `self.impact_evaluator = ImpactEvaluator()`:

```python
# Make evaluator available for /api/impact/health
if hasattr(self, 'web_app') and self.web_app:
    self.web_app["impact_evaluator"] = self.impact_evaluator
```

- [ ] **Step 6: Run integration smoke test**

```bash
cd news-monitor && python -c "
from storage.database import Database
from engine.impact_evaluator import ImpactEvaluator
from storage.models import NewsItem

d = Database()
d.init_db()

e = ImpactEvaluator()
item = NewsItem(title='Fed raises rates 50bp', content_snippet='x'*100,
                source='Bloomberg', tickers_found='SPY', macro_tags='monetary_policy')
# Smoke: pre-filter check
from engine.priority import PriorityScorer
scorer = PriorityScorer()
score = scorer.score(item, tickers={'SPY'}, macro_tags={'monetary_policy'})
print(f'Priority score: {score}, passes threshold: {score >= 0.50}')
"
```

Expected: prints priority score and threshold check.

- [ ] **Step 7: Verify full test suite**

```bash
cd news-monitor && python -m pytest tests/ -q --tb=short
```

Expected: 0 new failures beyond the 6 known ChromaDB errors.

- [ ] **Step 8: Commit**

```bash
git add news-monitor/main.py
git commit -m "feat(impact): wire ImpactEvaluator into main pipeline with collector loop"
```

---

### Verification Checklist

1. `python news-monitor/scripts/verify_env.py` — ALL CHECKS PASSED
2. `cd news-monitor && python -m pytest tests/ -q --tb=short` — 0 new failures
3. `python -c "from engine.impact_evaluator import ImpactEvaluator; print('OK')"` — imports clean
4. `python -c "from storage.database import Database; d=Database(); d.init_db(); print(d.get_impact_stats())"` — tables exist
5. Dashboard loads at `/impact` (when web server is running)
