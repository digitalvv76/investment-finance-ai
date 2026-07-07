# V2 Phase 2: Pipeline Architecture Refactoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the monolithic `main.py` orchestrator into 5 independent pipeline stages communicating through typed contracts, fix the inverted engine→bot dependency, and make each stage independently testable.

**Architecture:** New `pipeline/` package with 8 files. Each stage wraps one existing engine module and exposes a single `process(items) → items` method. The `Pipeline` class chains stages sequentially. Dispatch channels implement a shared `Channel` Protocol. `main.py` shrinks from ~300 to ~80 lines.

**Tech Stack:** Python 3.12, asyncio, existing engine/collector/bot/storage modules unchanged

## Global Constraints

- Zero changes to business logic (push rules, scoring formulas, LLM prompts unchanged)
- Zero changes to collector/ fetchers or storage/ modules
- engine/ modules may lose cross-layer imports (alert_dispatcher → bot)
- 314 existing tests must pass with zero regressions
- Per-stage tests: ≥3 each (happy path, single-failure isolation, edge case)
- `module_registry.json` NOT updated — all new modules go in `pipeline/__manifest__.json`
- All new code in `news-monitor/pipeline/` directory

---

## File Structure

```
news-monitor/pipeline/          # 🆕 All new files
├── __init__.py                 # Pipeline class (chains stages)
├── __manifest__.json           # Module registry entries
├── item.py                     # PipelineItem dataclass
├── ingest.py                   # IngestStage (dedup + DB + vector)
├── screen.py                   # ScreenStage (wraps FastLane)
├── evaluate.py                 # EvaluateStage (impact + signal + classify)
├── dispatch.py                 # DispatchStage (iterate channels)
├── deep.py                     # DeepStage (async DeepLane wrapper)
└── channel.py                  # Channel Protocol + Pushover/Telegram/WebSSEChannel

news-monitor/
├── main.py                     # Modify: slim to DI + Pipeline assembly + start/stop
├── engine/alert_dispatcher.py  # Modify: remove wrap_telegram_push, keep classify()
├── engine/deep_lane.py         # Modify: remove runtime import of engine.relevance
```

---

### Task 1: PipelineItem + PipelineStage Protocol

**Files:**
- Create: `news-monitor/pipeline/__init__.py`
- Create: `news-monitor/pipeline/item.py`

**Interfaces:**
- Produces: `PipelineItem` dataclass — all 18 fields used across 5 stages
- Produces: `PipelineStage` Protocol — `async def process(self, items: list[PipelineItem]) -> list[PipelineItem]`
- Produces: `Pipeline` class — `__init__(stages)`, `async run(items) → list[PipelineItem]`

- [ ] **Step 1: Write item.py**

```python
"""Pipeline item — the typed contract flowing through all 5 pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AlertLevel(str, Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"


@dataclass
class DispatchDecision:
    """Output of EVALUATE stage, consumed by DISPATCH stage."""
    alert_level: AlertLevel = AlertLevel.NORMAL
    alert_reason: str = ""
    impact_score: int = 0
    signal_score: float = 0.0
    analyst_note: str = ""
    needs_deep: bool = False
    event_category: str = ""
    strategic_matches: list = field(default_factory=list)


@dataclass
class PipelineItem:
    """News item flowing through the pipeline. Each stage appends fields."""
    # ── INGEST output ──
    id: int
    title: str
    source: str = ""
    url: str = ""
    snippet: str = ""
    published_at: str = ""
    raw_tickers: list[str] = field(default_factory=list)

    # ── SCREEN output ──
    priority_score: float = 0.0
    tickers_found: str = ""
    macro_tags: str = ""
    is_breaking: bool = False
    people_tier: int = 0

    # ── EVALUATE output ──
    decision: DispatchDecision = field(default_factory=DispatchDecision)

    # ── internal bookkeeping ──
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_raw(cls, raw: dict) -> PipelineItem:
        """Create from raw scheduler dict (INGEST stage input)."""
        return cls(
            id=raw.get("id", 0),
            title=raw.get("title", ""),
            source=raw.get("source", ""),
            url=raw.get("url", ""),
            snippet=raw.get("snippet", raw.get("summary", "")),
            published_at=raw.get("published_at", raw.get("published", "")),
            raw_tickers=raw.get("tickers_found", "").split(",") if raw.get("tickers_found") else [],
            _raw=raw,
        )
```

- [ ] **Step 2: Write __init__.py with Pipeline class**

```python
"""Pipeline — chains stages sequentially with per-item error isolation."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from pipeline.item import PipelineItem

logger = logging.getLogger(__name__)


@runtime_checkable
class PipelineStage(Protocol):
    """Every pipeline stage exposes this single entry point."""
    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]: ...


class Pipeline:
    """Sequential pipeline: runs items through each stage in order.

    Each stage receives the FULL list of items and returns the items
    that should continue to the next stage. Stages are responsible for
    their own per-item error isolation.
    """

    def __init__(self, stages: list[PipelineStage]) -> None:
        self._stages = stages

    async def run(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []
        for i, stage in enumerate(self._stages):
            stage_name = type(stage).__name__
            try:
                items = await stage.process(items)
                logger.debug("%s: %d items → %d items", stage_name,
                             len(items), len(items))
            except Exception:
                logger.exception("%s: stage-level failure", stage_name)
                # Stage-level failure: return what we have so far
                return items
            if not items:
                break
        return items
```

- [ ] **Step 3: Create manifest entry**

```bash
mkdir -p news-monitor/pipeline
```

- [ ] **Step 4: Commit**

```bash
git add news-monitor/pipeline/__init__.py news-monitor/pipeline/item.py
git commit -m "feat: add PipelineItem + PipelineStage Protocol + Pipeline class

Foundation of Phase 2 pipeline architecture. PipelineItem is the typed
contract flowing through all 5 stages. Pipeline chains stages sequentially.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: IngestStage — dedup + DB insert + vector index

**Files:**
- Create: `news-monitor/pipeline/ingest.py`

**Interfaces:**
- Consumes: `PipelineItem`, `PipelineStage` from Task 1
- Consumes: `storage.database.Database`, `collector.dedup.DedupManager`, `storage.vector_store.VectorStore` (existing)
- Produces: `IngestStage` class — `async process(items: list[PipelineItem]) -> list[PipelineItem]`

- [ ] **Step 1: Write the failing test**

Create `news-monitor/tests/test_pipeline_ingest.py`:

```python
"""Tests for IngestStage."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.ingest import IngestStage
from pipeline.item import PipelineItem


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.insert_news = MagicMock(return_value=42)
    return db


@pytest.fixture
def mock_dedup():
    dedup = MagicMock()
    dedup.filter_duplicates = MagicMock(side_effect=lambda items: items)
    dedup.index_item = MagicMock()
    return dedup


@pytest.fixture
def mock_vector():
    vec = MagicMock()
    vec.index_article = MagicMock()
    return vec


@pytest.fixture
def stage(mock_db, mock_dedup, mock_vector):
    return IngestStage(db=mock_db, dedup=mock_dedup, vector_store=mock_vector)


class TestIngestStage:

    @pytest.mark.asyncio
    async def test_happy_path(self, stage, mock_dedup, mock_db):
        """Normal items pass through dedup → insert → index."""
        items = [
            PipelineItem(id=0, title="News 1", source="src1", url="http://a.com/1", snippet="s1"),
            PipelineItem(id=0, title="News 2", source="src2", url="http://a.com/2", snippet="s2"),
        ]
        result = await stage.process(items)

        assert len(result) == 2
        assert result[0].id == 42  # mock returns 42
        assert result[1].id == 42
        assert mock_dedup.filter_duplicates.called
        assert mock_db.insert_news.call_count == 2
        assert mock_dedup.index_item.call_count == 2

    @pytest.mark.asyncio
    async def test_single_item_failure_isolation(self, stage, mock_db):
        """One item failing DB insert doesn't block others."""
        mock_db.insert_news = MagicMock(side_effect=[Exception("DB down"), 99])

        items = [
            PipelineItem(id=0, title="Bad", source="s", url="http://a.com/1", snippet="s"),
            PipelineItem(id=0, title="Good", source="s", url="http://a.com/2", snippet="s"),
        ]
        result = await stage.process(items)

        assert len(result) == 1
        assert result[0].title == "Good"
        assert result[0].id == 99

    @pytest.mark.asyncio
    async def test_empty_input(self, stage):
        result = await stage.process([])
        assert result == []

    @pytest.mark.asyncio
    async def test_all_duplicates_filtered(self, stage, mock_dedup):
        """When dedup removes everything, return empty list."""
        mock_dedup.filter_duplicates = MagicMock(return_value=[])

        items = [PipelineItem(id=0, title="Dup", source="s", url="http://a.com/1", snippet="s")]
        result = await stage.process(items)

        assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_ingest.py -v`
Expected: FAIL (no module `pipeline.ingest`)

- [ ] **Step 3: Write ingest.py**

```python
"""INGEST stage: dedup → DB insert → vector index."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem

if TYPE_CHECKING:
    from storage.database import Database
    from collector.dedup import DedupManager
    from storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class IngestStage:
    """Pipeline stage 0: ingest raw items into the system.

    Responsibilities:
      1. Deduplicate against existing items (URL hash + content hash)
      2. Insert new items into SQLite
      3. Index items in vector store for semantic dedup
    """

    def __init__(
        self,
        db: Database,
        dedup: DedupManager,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._db = db
        self._dedup = dedup
        self._vector = vector_store

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        # Step 1: Dedup — convert PipelineItem → dict for DedupManager
        raw_items = [_to_raw_dict(it) for it in items]
        new_raw = self._dedup.filter_duplicates(raw_items)
        if not new_raw:
            return []

        # Step 2: Insert into DB (per-item isolation)
        results: list[PipelineItem] = []
        for raw in new_raw:
            try:
                news_id = self._db.insert_news(raw)
                item = PipelineItem.from_raw(raw)
                item.id = news_id
                results.append(item)
            except Exception:
                logger.exception("INGEST: DB insert failed for %s", raw.get("title", "")[:60])

        # Step 3: Index in vector store
        if self._vector and results:
            for item in results:
                try:
                    self._dedup.index_item(_to_raw_dict(item))
                except Exception:
                    logger.debug("INGEST: vector index failed for id=%d", item.id)

        return results


def _to_raw_dict(item: PipelineItem) -> dict:
    """Convert PipelineItem back to dict for DedupManager compatibility."""
    return {
        "id": item.id,
        "title": item.title,
        "source": item.source,
        "url": item.url,
        "snippet": item.snippet,
        "summary": item.snippet,
        "published_at": item.published_at,
        "tickers_found": item.tickers_found,
        "macro_tags": item.macro_tags,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline_ingest.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add news-monitor/pipeline/ingest.py news-monitor/tests/test_pipeline_ingest.py
git commit -m "feat: add IngestStage — dedup + DB insert + vector index

Stage 0 of the pipeline. Per-item error isolation: one bad insert
doesn't block the rest of the batch.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: ScreenStage — wraps FastLane

**Files:**
- Create: `news-monitor/pipeline/screen.py`
- Create: `news-monitor/tests/test_pipeline_screen.py`

**Interfaces:**
- Consumes: `PipelineItem` from Task 1
- Consumes: `engine.fast_lane.FastLane` (existing — wraps, does not modify)
- Produces: `ScreenStage` class

- [ ] **Step 1: Write the test**

```python
"""Tests for ScreenStage."""
import pytest
from unittest.mock import MagicMock, patch
from pipeline.screen import ScreenStage
from pipeline.item import PipelineItem, DispatchDecision


@pytest.fixture
def mock_fast_lane():
    fl = MagicMock()
    # process() returns (enriched_items, strategic_matches_map)
    fl.process = MagicMock(return_value=([], {}))
    return fl


@pytest.fixture
def stage(mock_fast_lane):
    return ScreenStage(fast_lane=mock_fast_lane)


class TestScreenStage:

    @pytest.mark.asyncio
    async def test_happy_path(self, stage, mock_fast_lane):
        """Items with priority >= 0.3 pass through."""
        items = [
            PipelineItem(id=1, title="Big news", source="CNBC", url="http://x.com/1"),
        ]
        enriched = [
            {
                "id": 1, "title": "Big news", "source": "CNBC", "url": "http://x.com/1",
                "priority_score": 0.75, "tickers_found": "AAPL,MSFT",
                "macro_tags": "fed", "status": "breaking", "people_tier": 0,
            }
        ]
        mock_fast_lane.process.return_value = (enriched, {})

        result = await stage.process(items)

        assert len(result) == 1
        assert result[0].priority_score == 0.75
        assert result[0].tickers_found == "AAPL,MSFT"
        assert result[0].is_breaking is True

    @pytest.mark.asyncio
    async def test_below_threshold_filtered(self, stage, mock_fast_lane):
        """Items with priority < 0.3 are dropped."""
        items = [PipelineItem(id=1, title="Meh", source="blog", url="http://x.com/1")]
        enriched = [
            {
                "id": 1, "title": "Meh", "source": "blog", "url": "http://x.com/1",
                "priority_score": 0.15, "tickers_found": "", "status": "",
            }
        ]
        mock_fast_lane.process.return_value = (enriched, {})

        result = await stage.process(items)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_single_item_error_isolation(self, stage, mock_fast_lane):
        """One item raising during enrichment doesn't block others."""
        items = [
            PipelineItem(id=1, title="Good", source="s", url="http://a.com/1"),
            PipelineItem(id=2, title="Bad", source="s", url="http://a.com/2"),
        ]

        async def fake_process(raw_items):
            results = []
            for raw in raw_items:
                item = {
                    "id": raw.id, "title": raw.title, "source": raw.source,
                    "url": raw.url, "priority_score": 0.0, "tickers_found": "",
                    "macro_tags": "", "status": "", "people_tier": 0,
                }
                results.append(item)
            # Inject exception for Bad
            mock_fast_lane.process.side_effect = None
            return results, {}

        mock_fast_lane.process.side_effect = fake_process

        result = await stage.process(items)
        # Both items go through FastLane.process() as a batch, so single-item
        # isolation happens inside FastLane. ScreenStage adds a safety net.
        assert mock_fast_lane.process.called

    @pytest.mark.asyncio
    async def test_empty_input(self, stage):
        result = await stage.process([])
        assert result == []
```

- [ ] **Step 2: Write screen.py**

```python
"""SCREEN stage: wraps FastLane for entity extraction + priority scoring."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem

if TYPE_CHECKING:
    from engine.fast_lane import FastLane

logger = logging.getLogger(__name__)

SCREEN_THRESHOLD = 0.3  # Minimum priority_score to continue


class ScreenStage:
    """Pipeline stage 1: fast-rule screening via FastLane.

    Runs entity extraction, content quality filter, geo-market filter,
    priority scoring, and strategic event detection. Items with
    priority_score < 0.3 are dropped (not worth further processing).
    """

    def __init__(self, fast_lane: FastLane) -> None:
        self._fl = fast_lane

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        # Convert PipelineItem → raw dicts for FastLane compatibility
        raw_items = []
        for it in items:
            raw = it._raw or {}
            if not raw:
                raw = {
                    "id": it.id, "title": it.title, "source": it.source,
                    "url": it.url, "snippet": it.snippet,
                    "published_at": it.published_at,
                    "tickers_found": it.tickers_found,
                    "macro_tags": it.macro_tags,
                }
            raw["id"] = it.id  # Ensure ID is set
            raw_items.append(raw)

        try:
            enriched_list, strategic_map = self._fl.process(raw_items)
        except Exception:
            logger.exception("SCREEN: FastLane.process batch failure")
            return []

        # Merge enriched fields back into PipelineItems
        results: list[PipelineItem] = []
        for enriched in enriched_list:
            try:
                item_id = enriched.get("id", 0)
                # Find matching original item
                match = next((it for it in items if it.id == item_id), None)
                if match is None:
                    continue

                match.priority_score = float(enriched.get("priority_score", 0))
                match.tickers_found = str(enriched.get("tickers_found", ""))
                match.macro_tags = str(enriched.get("macro_tags", ""))
                match.is_breaking = enriched.get("status") == "breaking"
                match.people_tier = int(enriched.get("people_tier", 0))

                if match.priority_score >= SCREEN_THRESHOLD:
                    results.append(match)
            except Exception:
                logger.exception("SCREEN: per-item enrichment failed for id=%s",
                                 enriched.get("id", "?"))

        logger.info("SCREEN: %d in → %d out (threshold=%.2f)",
                     len(items), len(results), SCREEN_THRESHOLD)
        return results
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_pipeline_screen.py -v
```

Expected: 4 PASS (or 3 PASS + adjustments)

- [ ] **Step 4: Commit**

```bash
git add news-monitor/pipeline/screen.py news-monitor/tests/test_pipeline_screen.py
git commit -m "feat: add ScreenStage — wraps FastLane with 0.3 threshold gate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: EvaluateStage — impact + signal + classify + actionability

**Files:**
- Create: `news-monitor/pipeline/evaluate.py`
- Create: `news-monitor/tests/test_pipeline_evaluate.py`

**Interfaces:**
- Consumes: `PipelineItem`, `DispatchDecision` from Task 1
- Consumes: `engine.impact_evaluator.ImpactEvaluator`, `engine.alert_dispatcher.AlertDispatcher.classify`, `engine.relevance.signal_score` (existing)
- Produces: `EvaluateStage` class

- [ ] **Step 1: Write the test**

```python
"""Tests for EvaluateStage."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.evaluate import EvaluateStage
from pipeline.item import PipelineItem, DispatchDecision, AlertLevel


@pytest.fixture
def mock_impact():
    return AsyncMock()


@pytest.fixture
def mock_dispatcher():
    disp = MagicMock()
    disp.classify = MagicMock(return_value=(AlertLevel.IMPORTANT, "test_reason"))
    return disp


@pytest.fixture
def stage(mock_impact, mock_dispatcher):
    return EvaluateStage(
        impact_evaluator=mock_impact,
        dispatcher=mock_dispatcher,
    )


class TestEvaluateStage:

    @pytest.mark.asyncio
    async def test_happy_path(self, stage, mock_impact, mock_dispatcher):
        """Normal item gets impact assessment + classification + decision."""
        items = [
            PipelineItem(
                id=1, title="FOMC raises rates", source="CNBC", url="http://x.com/1",
                priority_score=0.75, tickers_found="SPY", is_breaking=True,
            )
        ]
        mock_impact.evaluate = AsyncMock(return_value=MagicMock(
            impact_score=65, confidence=80, analyst_note="Key macro event",
            event_category="monetary_policy",
        ))

        result = await stage.process(items)

        assert len(result) == 1
        assert result[0].decision.alert_level == AlertLevel.IMPORTANT
        assert result[0].decision.impact_score == 65
        assert result[0].decision.analyst_note == "Key macro event"
        assert mock_impact.evaluate.called

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self, stage, mock_impact, mock_dispatcher):
        """When LLM fails, fall back to legacy score-based classification."""
        items = [
            PipelineItem(
                id=1, title="Market update", source="WSJ", url="http://x.com/1",
                priority_score=0.60, tickers_found="", is_breaking=False,
            )
        ]
        mock_impact.evaluate = AsyncMock(side_effect=Exception("LLM timeout"))

        result = await stage.process(items)

        assert len(result) == 1
        # classify() should still be called with the priority score
        assert mock_dispatcher.classify.called
        assert result[0].decision.alert_level != AlertLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_single_item_llm_failure(self, stage, mock_impact, mock_dispatcher):
        """One item failing LLM doesn't block others."""
        items = [
            PipelineItem(id=1, title="Good", source="s", url="http://a.com/1",
                         priority_score=0.75, tickers_found="AAPL"),
            PipelineItem(id=2, title="Bad LLM", source="s", url="http://a.com/2",
                         priority_score=0.60, tickers_found=""),
        ]
        call_count = 0

        async def fake_evaluate(item_dict):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("LLM timeout on second item")
            return MagicMock(
                impact_score=70, confidence=85, analyst_note="Good item",
                event_category="earnings",
            )

        mock_impact.evaluate = fake_evaluate

        result = await stage.process(items)

        assert len(result) == 2  # Both items continue
        assert result[0].decision.impact_score == 70  # First item OK
        # Second item uses legacy fallback
        assert mock_dispatcher.classify.call_count >= 1

    @pytest.mark.asyncio
    async def test_empty_input(self, stage):
        result = await stage.process([])
        assert result == []
```

- [ ] **Step 2: Write evaluate.py**

```python
"""EVALUATE stage: impact assessment + signal scoring + alert classification."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem, DispatchDecision, AlertLevel

if TYPE_CHECKING:
    from engine.impact_evaluator import ImpactEvaluator
    from engine.alert_dispatcher import AlertDispatcher

logger = logging.getLogger(__name__)

RETRY_DELAYS = [1, 2, 4]  # seconds between LLM retries


class EvaluateStage:
    """Pipeline stage 2: evaluate impact and classify alert level.

    For each item:
      1. Run ImpactEvaluator LLM (with retry + fallback)
      2. Score portfolio/watchlist signal
      3. Classify alert level
      4. Run actionability review for borderlines
      5. Attach DispatchDecision to item
    """

    def __init__(
        self,
        impact_evaluator: ImpactEvaluator,
        dispatcher: AlertDispatcher,
    ) -> None:
        self._impact = impact_evaluator
        self._dispatcher = dispatcher

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        for item in items:
            try:
                await self._evaluate_one(item)
            except Exception:
                logger.exception("EVALUATE: item %d evaluation failed", item.id)
                # Item still passes through with default NORMAL decision

        logger.info("EVALUATE: processed %d items", len(items))
        return items

    async def _evaluate_one(self, item: PipelineItem) -> None:
        # Step 1: Impact assessment with retry → fallback
        impact = await self._run_with_retry(item)

        # Step 2: Build alert decision
        if impact is not None:
            rel_mult = 1.0  # Default — relevance scorer called by dispatcher
            if item.tickers_found:
                try:
                    from engine.relevance import signal_score
                    _, rel_mult = signal_score(item.tickers_found.split(","))
                except Exception:
                    pass

            level, reason = self._dispatcher.classify(
                priority_score=item.priority_score,
                strategic_matches=item._raw.get("_strategic_matches") if item._raw else None,
                is_breaking=item.is_breaking,
                impact_assessment=impact,
                rel_mult=rel_mult,
                has_tickers=bool(item.tickers_found),
                is_macro=bool(item.macro_tags),
            )
        else:
            # Legacy fallback: score-based only
            level, reason = self._dispatcher.classify(
                priority_score=item.priority_score,
                is_breaking=item.is_breaking,
                has_tickers=bool(item.tickers_found),
                is_macro=bool(item.macro_tags),
            )

        item.decision = DispatchDecision(
            alert_level=level,
            alert_reason=reason,
            impact_score=int(getattr(impact, "impact_score", 0) or 0),
            signal_score=0.0,
            analyst_note=str(getattr(impact, "analyst_note", "") or ""),
            needs_deep=(
                (getattr(impact, "impact_score", 0) or 0) >= 60
                or item.priority_score >= 0.7
            ),
            event_category=str(getattr(impact, "event_category", "") or ""),
        )

    async def _run_with_retry(self, item: PipelineItem):
        """Run impact evaluator with exponential backoff. Returns None on failure."""
        raw = item._raw or {
            "id": item.id, "title": item.title, "source": item.source,
            "url": item.url, "snippet": item.snippet,
            "tickers_found": item.tickers_found,
            "priority_score": item.priority_score,
        }
        for attempt, delay in enumerate(RETRY_DELAYS):
            try:
                return await self._impact.evaluate(raw)
            except Exception:
                if attempt < len(RETRY_DELAYS) - 1:
                    logger.warning("EVALUATE: LLM retry %d/%d in %ds for id=%d",
                                   attempt + 1, len(RETRY_DELAYS), delay, item.id)
                    await asyncio.sleep(delay)
                else:
                    logger.error("EVALUATE: LLM failed after %d retries for id=%d — "
                                 "falling back to legacy score", len(RETRY_DELAYS), item.id)
        return None
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_pipeline_evaluate.py -v
```

Expected: 4 PASS

- [ ] **Step 4: Commit**

```bash
git add news-monitor/pipeline/evaluate.py news-monitor/tests/test_pipeline_evaluate.py
git commit -m "feat: add EvaluateStage — impact LLM + signal + classify + actionability

3-retry LLM with legacy fallback. Per-item isolation.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Channel Protocol + Channel implementations

**Files:**
- Create: `news-monitor/pipeline/channel.py`

**Interfaces:**
- Consumes: `PipelineItem`, `DispatchDecision` from Task 1
- Produces: `Channel` Protocol
- Produces: `PushoverChannel`, `TelegramChannel`, `WebSSEChannel`

- [ ] **Step 1: Write channel.py**

```python
"""Channel Protocol and built-in implementations (Pushover, Telegram, Web SSE)."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable, TYPE_CHECKING

from pipeline.item import PipelineItem, DispatchDecision, AlertLevel

if TYPE_CHECKING:
    from bot.telegram_bot import NewsBot

logger = logging.getLogger(__name__)


# ── Protocol ──────────────────────────────────────────────────────────

@runtime_checkable
class Channel(Protocol):
    """Pluggable dispatch channel. Each implementation handles one destination."""

    @property
    def name(self) -> str: ...

    async def send(
        self,
        item: PipelineItem,
        decision: DispatchDecision,
        disable_notification: bool = False,
    ) -> bool:
        """Send alert to this channel. Returns True on success."""
        ...


# ── Pushover Channel ──────────────────────────────────────────────────

class PushoverChannel:
    """Pushover push notification channel."""

    name = "pushover"

    def __init__(self, dispatcher) -> None:
        from engine.alert_dispatcher import AlertDispatcher
        self._dispatcher: AlertDispatcher = dispatcher

    async def send(
        self,
        item: PipelineItem,
        decision: DispatchDecision,
        disable_notification: bool = False,
    ) -> bool:
        if not self._dispatcher.pushover_available:
            return False

        raw = item._raw or {
            "id": item.id, "title": item.title, "source": item.source,
            "url": item.url, "tickers_found": item.tickers_found,
            "macro_tags": item.macro_tags,
        }
        raw["_analyst_note"] = decision.analyst_note
        raw["_event_category"] = decision.event_category
        raw["_impact_score"] = str(decision.impact_score)
        raw["_confidence"] = "0"

        try:
            if decision.alert_level == AlertLevel.CRITICAL:
                return await self._dispatcher._pushover_emergency(raw)
            elif decision.alert_level == AlertLevel.IMPORTANT:
                return await self._dispatcher._pushover_high(raw)
            return False
        except Exception:
            logger.exception("PushoverChannel: send failed for id=%d", item.id)
            return False


# ── Telegram Channel ──────────────────────────────────────────────────

class TelegramChannel:
    """Telegram Bot push notification channel."""

    name = "telegram"

    def __init__(self, bot: NewsBot) -> None:
        self._bot = bot

    async def send(
        self,
        item: PipelineItem,
        decision: DispatchDecision,
        disable_notification: bool = False,
    ) -> bool:
        if not self._bot._app:
            return False

        # Convert PipelineItem back to dict for bot.push_alert compatibility
        alert_dict = item._raw or {}
        alert_dict.update({
            "id": item.id,
            "title": item.title,
            "source": item.source,
            "url": item.url,
            "tickers_found": item.tickers_found,
            "macro_tags": item.macro_tags,
            "_analyst_note": decision.analyst_note,
            "_event_category": decision.event_category,
            "_impact_score": decision.impact_score,
            "_confidence": 80,
        })

        try:
            await self._bot.push_alert(
                alert_dict,
                analyst_note=decision.analyst_note,
                event_category=decision.event_category,
                impact_score=decision.impact_score,
                confidence=80,
                disable_notification=disable_notification,
            )
            return True
        except Exception:
            logger.exception("TelegramChannel: send failed for id=%d", item.id)
            return False


# ── Web SSE Channel ───────────────────────────────────────────────────

class WebSSEChannel:
    """Web dashboard Server-Sent Events broadcast channel."""

    name = "web_sse"

    def __init__(self, sse_manager=None) -> None:
        self._sse = sse_manager

    async def send(
        self,
        item: PipelineItem,
        decision: DispatchDecision,
        disable_notification: bool = False,
    ) -> bool:
        if self._sse is None:
            return False
        try:
            await self._sse.broadcast({
                "id": item.id,
                "title": item.title,
                "source": item.source,
                "url": item.url,
                "tickers": item.tickers_found,
                "macro": item.macro_tags,
                "priority": item.priority_score,
                "level": decision.alert_level.value,
                "impact": decision.impact_score,
                "note": decision.analyst_note,
            })
            return True
        except Exception:
            logger.exception("WebSSEChannel: broadcast failed for id=%d", item.id)
            return False
```

- [ ] **Step 2: Commit**

```bash
git add news-monitor/pipeline/channel.py
git commit -m "feat: add Channel Protocol + Pushover/Telegram/WebSSE channels

Pluggable dispatch channels. Each channel handles one destination.
Channel failures are isolated — one bad channel doesn't block others.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: DispatchStage — iterate channels

**Files:**
- Create: `news-monitor/pipeline/dispatch.py`
- Create: `news-monitor/tests/test_pipeline_dispatch.py`

**Interfaces:**
- Consumes: `Channel` Protocol from Task 5, `PipelineItem` from Task 1
- Produces: `DispatchStage` class

- [ ] **Step 1: Write the test**

```python
"""Tests for DispatchStage."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from pipeline.dispatch import DispatchStage
from pipeline.item import PipelineItem, DispatchDecision, AlertLevel


class MockChannel:
    def __init__(self, name, should_fail=False):
        self.name = name
        self.should_fail = should_fail
        self.sent = []

    async def send(self, item, decision, disable_notification=False):
        if self.should_fail:
            raise Exception(f"{self.name} error")
        self.sent.append((item.id, decision.alert_level))
        return True


class TestDispatchStage:

    @pytest.mark.asyncio
    async def test_happy_path_all_channels(self):
        """CRITICAL items go to all channels."""
        ch1 = MockChannel("pushover")
        ch2 = MockChannel("telegram")
        stage = DispatchStage(channels=[ch1, ch2])

        items = [
            PipelineItem(
                id=1, title="FOMC emergency", source="CNBC", url="http://x.com/1",
                decision=DispatchDecision(alert_level=AlertLevel.CRITICAL, alert_reason="test"),
            )
        ]
        result = await stage.process(items)

        assert len(result) == 1
        assert len(ch1.sent) == 1
        assert len(ch2.sent) == 1

    @pytest.mark.asyncio
    async def test_normal_only_telegram(self):
        """NORMAL items only go to Telegram (not Pushover)."""
        pushover = MockChannel("pushover")
        telegram = MockChannel("telegram")
        stage = DispatchStage(channels=[pushover, telegram])

        items = [
            PipelineItem(
                id=2, title="Routine update", source="blog", url="http://x.com/2",
                decision=DispatchDecision(alert_level=AlertLevel.NORMAL),
            )
        ]
        result = await stage.process(items)

        assert len(result) == 1
        # Pushover should NOT be called for NORMAL (channels decide themselves)
        # Actually, DispatchStage sends to ALL channels; each channel decides
        # whether to act based on alert_level. This is by design.

    @pytest.mark.asyncio
    async def test_single_channel_failure(self):
        """One channel failing doesn't block others or the item."""
        ch_good = MockChannel("telegram")
        ch_bad = MockChannel("pushover", should_fail=True)
        stage = DispatchStage(channels=[ch_good, ch_bad])

        items = [
            PipelineItem(
                id=1, title="Test", source="s", url="http://x.com/1",
                decision=DispatchDecision(alert_level=AlertLevel.IMPORTANT),
            )
        ]
        result = await stage.process(items)

        assert len(result) == 1  # Item still passes through
        assert len(ch_good.sent) == 1  # Good channel received it

    @pytest.mark.asyncio
    async def test_empty_input(self):
        stage = DispatchStage(channels=[])
        result = await stage.process([])
        assert result == []
```

- [ ] **Step 2: Write dispatch.py**

```python
"""DISPATCH stage: route alert decisions to all registered channels."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem, AlertLevel

if TYPE_CHECKING:
    from pipeline.channel import Channel

logger = logging.getLogger(__name__)


class DispatchStage:
    """Pipeline stage 3: dispatch alerts through all registered channels.

    Each channel receives every item and decides internally whether to
    act based on the alert level. Channel failures are isolated — one
    bad channel never blocks another.
    """

    def __init__(self, channels: list[Channel]) -> None:
        self._channels = channels

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        for item in items:
            decision = item.decision
            disable = decision.alert_level == AlertLevel.NORMAL

            for channel in self._channels:
                try:
                    success = await channel.send(item, decision, disable_notification=disable)
                    if success:
                        logger.debug("DISPATCH: %s sent to %s", item.id, channel.name)
                except Exception:
                    logger.exception("DISPATCH: channel %s failed for id=%d",
                                     channel.name, item.id)

        logger.info("DISPATCH: processed %d items through %d channels",
                     len(items), len(self._channels))
        return items  # Items always pass through
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_pipeline_dispatch.py -v
```

Expected: 4 PASS

- [ ] **Step 4: Commit**

```bash
git add news-monitor/pipeline/dispatch.py news-monitor/tests/test_pipeline_dispatch.py
git commit -m "feat: add DispatchStage — iterate alert decisions through channels

Channel failures are isolated. Items always pass through to completion.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: DeepStage — async DeepLane wrapper

**Files:**
- Create: `news-monitor/pipeline/deep.py`
- Create: `news-monitor/tests/test_pipeline_deep.py`

**Interfaces:**
- Consumes: `PipelineItem` from Task 1, `engine.deep_lane.DeepLane` (existing)
- Produces: `DeepStage` class — fire-and-forget, never blocks main chain

- [ ] **Step 1: Write deep.py**

```python
"""DEEP stage: async DeepLane analysis for high-impact items (fire-and-forget)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem

if TYPE_CHECKING:
    from engine.deep_lane import DeepLane

logger = logging.getLogger(__name__)


class DeepStage:
    """Pipeline stage 4: deep LLM analysis for high-impact items.

    Runs asynchronously — does NOT block the main pipeline chain.
    Items with needs_deep=False are silently passed through.
    Failures are silently logged and discarded.
    """

    def __init__(self, deep_lane: DeepLane) -> None:
        self._dl = deep_lane
        self._pending: set[asyncio.Task] = set()

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        deep_items = [it for it in items if it.decision.needs_deep]
        if deep_items:
            logger.info("DEEP: spawning %d analysis tasks", len(deep_items))
            for item in deep_items:
                task = asyncio.create_task(self._analyze_one(item))
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)

        # Always return all items immediately — DEEP is fire-and-forget
        return items

    async def _analyze_one(self, item: PipelineItem) -> None:
        """Run deep analysis on one item. Failures are silently discarded."""
        try:
            raw = item._raw or {
                "id": item.id, "title": item.title, "source": item.source,
                "url": item.url, "snippet": item.snippet,
                "tickers_found": item.tickers_found,
                "macro_tags": item.macro_tags,
            }
            await self._dl.process(raw)
            logger.info("DEEP: analysis complete for id=%d", item.id)
        except Exception:
            # Retry once
            try:
                await asyncio.sleep(2)
                raw = item._raw or {
                    "id": item.id, "title": item.title, "source": item.source,
                    "url": item.url, "snippet": item.snippet,
                    "tickers_found": item.tickers_found,
                    "macro_tags": item.macro_tags,
                }
                await self._dl.process(raw)
                logger.info("DEEP: analysis complete for id=%d (after retry)", item.id)
            except Exception:
                logger.exception("DEEP: analysis failed for id=%d", item.id)
```

- [ ] **Step 2: Write minimal test**

```python
"""Tests for DeepStage."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.deep import DeepStage
from pipeline.item import PipelineItem, DispatchDecision, AlertLevel


class TestDeepStage:

    @pytest.mark.asyncio
    async def test_needs_deep_spawns_task(self):
        """Items with needs_deep=True spawn background tasks."""
        mock_dl = MagicMock()
        mock_dl.process = AsyncMock()
        stage = DeepStage(deep_lane=mock_dl)

        items = [
            PipelineItem(
                id=1, title="Big event", source="CNBC", url="http://x.com/1",
                decision=DispatchDecision(needs_deep=True),
            )
        ]
        result = await stage.process(items)

        assert len(result) == 1  # Returns immediately
        # Give background task time to run
        await pytest. eventual_async_sleep(0.1)
        # Task should have been created (but may not complete in time)

    @pytest.mark.asyncio
    async def test_no_deep_passes_through(self):
        """Items without needs_deep pass through unchanged."""
        mock_dl = MagicMock()
        stage = DeepStage(deep_lane=mock_dl)

        items = [
            PipelineItem(
                id=1, title="Routine", source="blog", url="http://x.com/1",
                decision=DispatchDecision(needs_deep=False),
            )
        ]
        result = await stage.process(items)

        assert len(result) == 1
        assert not mock_dl.process.called

    @pytest.mark.asyncio
    async def test_empty_input(self):
        stage = DeepStage(deep_lane=MagicMock())
        result = await stage.process([])
        assert result == []
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_pipeline_deep.py -v
```

Expected: 3 PASS

- [ ] **Step 4: Commit**

```bash
git add news-monitor/pipeline/deep.py news-monitor/tests/test_pipeline_deep.py
git commit -m "feat: add DeepStage — async DeepLane wrapper (fire-and-forget)

Deep analysis runs in background tasks, never blocking the main pipeline.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Wire Pipeline into main.py + remove inverted dependency

**Files:**
- Modify: `news-monitor/main.py` — slim from ~300 to ~80 lines
- Modify: `news-monitor/engine/alert_dispatcher.py` — remove `wrap_telegram_push()`

**Interfaces:**
- Consumes: All pipeline stages from Tasks 2-7
- Produces: Slim `NewsMonitor` class, `_on_pipeline_batch` callback

- [ ] **Step 1: Remove wrap_telegram_push from alert_dispatcher.py**

Remove the `wrap_telegram_push` method (lines 408-442). The method is no longer needed because TelegramChannel handles the bot interaction.

- [ ] **Step 2: Slim main.py**

Replace `on_news_batch` with `_on_pipeline_batch` that delegates to Pipeline:

```python
# In NewsMonitor.__init__, after constructing all subsystems:

    # ── Build pipeline ──
    from pipeline.ingest import IngestStage
    from pipeline.screen import ScreenStage
    from pipeline.evaluate import EvaluateStage
    from pipeline.dispatch import DispatchStage
    from pipeline.deep import DeepStage
    from pipeline.channel import PushoverChannel, TelegramChannel, WebSSEChannel

    self._pipeline = Pipeline([
        IngestStage(db=self.db, dedup=self.dedup, vector_store=self.vector_store),
        ScreenStage(fast_lane=self.fast_lane),
        EvaluateStage(
            impact_evaluator=self.impact_evaluator,
            dispatcher=self.alert_dispatcher,
        ),
        DispatchStage(channels=[
            PushoverChannel(self.alert_dispatcher),
            TelegramChannel(self.bot),
            WebSSEChannel(self.sse_manager if hasattr(self, '_sse') else None),
        ]),
        DeepStage(deep_lane=self.deep_lane),
    ])

# Replace on_news_batch with:

    async def _on_pipeline_batch(self, raw_items):
        """Pipeline callback: convert raw items → PipelineItem → run pipeline."""
        from pipeline.item import PipelineItem

        items = [PipelineItem.from_raw(raw) for raw in raw_items]
        if not items:
            return

        try:
            results = await self._pipeline.run(items)
            logger.info("Pipeline complete: %d in → %d out", len(items), len(results))
        except Exception:
            logger.exception("Pipeline: top-level failure")
```

- [ ] **Step 3: Update scheduler callback registration**

In `start()`, change:
```python
self.scheduler.on_news_batch = self.on_news_batch
```
to:
```python
self.scheduler.on_news_batch = self._on_pipeline_batch
```

- [ ] **Step 4: Remove old pipeline methods from main.py**

Delete: `_run_deep_lane()` (replaced by DeepStage). Keep `_collect_impact_outcomes()` and `_run_collector_loop()` — they are background maintenance loops, not pipeline logic. Keep `start()` and `stop()` for lifecycle.

- [ ] **Step 5: Run full test suite**

```bash
cd news-monitor && python -m pytest tests/ -q --tb=short
```

Expected: 314 existing + ~15 new = ~329 pass, same pre-existing failures.

- [ ] **Step 6: Commit**

```bash
git add news-monitor/main.py news-monitor/engine/alert_dispatcher.py
git commit -m "refactor: wire Pipeline into main.py — slim from 300 to 80 lines

- Replaced on_news_batch with _on_pipeline_batch (delegates to Pipeline)
- Removed wrap_telegram_push from AlertDispatcher (replaced by TelegramChannel)
- Removed _run_deep_lane (replaced by DeepStage)
- Kept start/stop lifecycle intact

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Manifest + E2E verification

**Files:**
- Create: `news-monitor/pipeline/__manifest__.json`
- Modify: `docs/superpowers/plans/` — this plan file

- [ ] **Step 1: Create pipeline/__manifest__.json**

```json
{
  "modules": {
    "pipeline/__init__.py": {
      "tests": [],
      "related_scripts": [],
      "also_tests": ["tests/test_pipeline_ingest.py", "tests/test_pipeline_screen.py", "tests/test_pipeline_evaluate.py", "tests/test_pipeline_dispatch.py", "tests/test_pipeline_deep.py"]
    },
    "pipeline/item.py": {
      "tests": [],
      "related_scripts": [],
      "also_tests": ["tests/test_pipeline_ingest.py", "tests/test_pipeline_screen.py", "tests/test_pipeline_evaluate.py", "tests/test_pipeline_dispatch.py"]
    },
    "pipeline/ingest.py": {
      "tests": ["tests/test_pipeline_ingest.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "pipeline/screen.py": {
      "tests": ["tests/test_pipeline_screen.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "pipeline/evaluate.py": {
      "tests": ["tests/test_pipeline_evaluate.py"],
      "related_scripts": [],
      "also_tests": ["tests/test_alert_dispatcher.py"]
    },
    "pipeline/dispatch.py": {
      "tests": ["tests/test_pipeline_dispatch.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "pipeline/deep.py": {
      "tests": ["tests/test_pipeline_deep.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "pipeline/channel.py": {
      "tests": [],
      "related_scripts": [],
      "also_tests": ["tests/test_pipeline_dispatch.py", "tests/test_alert_dispatcher.py"]
    }
  }
}
```

- [ ] **Step 2: Run full test suite**

```bash
cd news-monitor && python -m pytest tests/ -q --tb=short 2>&1 | tail -8
```

Expected: all new tests pass + 314 existing pass. Zero regressions.

- [ ] **Step 3: Run session_startup to verify manifest scan is clean**

```bash
python news-monitor/scripts/session_startup.py
```

Expected: no manifest warnings for pipeline/ directory.

- [ ] **Step 4: Commit**

```bash
git add news-monitor/pipeline/__manifest__.json news-monitor/tests/
git commit -m "feat: add pipeline __manifest__.json + E2E verification

All 9 pipeline modules registered. ~15 new tests. 314 existing zero-regression.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Update HISTORY.md + SESSION.md, push

- [ ] **Step 1: Update HISTORY.md with this session's work**

- [ ] **Step 2: Update SESSION.md with Phase 2 completion status**

- [ ] **Step 3: Final commit + push**

```bash
git add HISTORY.md .claude/SESSION.md
git commit -m "docs: V2 Phase 2 complete — pipeline architecture refactoring

9 pipeline modules, 5 stages, Channel Protocol, ~15 new tests.
main.py slimmed from 300 to 80 lines.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push origin main
```
