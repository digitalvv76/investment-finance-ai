# 持续演进事件 · 事件级升级推送 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让系统识别 24h 滚动演进的高影响事件（如美伊冲突），给予事件级升级推送而非逐条静音，每事件最多 3 次推送（手机 ≤2）。

**Architecture:** 激活已有但休眠的新闻聚类（NewsCluster → EventLine），新增 EventEscalator 在调度器 `_tick_5min` 周期扫描活跃事件，跑 `NONE→ALERTED→CONFIRMED→CLOSED` 状态机，复用 AlertDispatcher 多通道推送。市场确认复用 impact_collector 的 yfinance 取价并加油价，带时间对齐 + 方向闸。

**Tech Stack:** Python 3.12, aiohttp, yfinance, SQLite, pytest/pytest-asyncio。分支 `v1-stable`（生产），部署经 Docker + `deploy_ecs.sh`。

## Global Constraints

- 分支 `v1-stable`；不碰 V2/main。修复流程：本地验证 → commit → deploy → ECS 观察 → cherry-pick 回 main。
- 逐条推送链路（FastLane + main.on_news_batch dispatch）**不改动**；事件级为独立并行链路。
- 所有阈值来自 `config/event-escalation.json`，代码不硬编码。
- 阈值确认值：ALERT = `source_count≥3 且 peak_impact≥70`（12h 活跃）；市场确认 = `|ΔSPX|≥0.2% 或 ΔVIX≥+5% 或 |Δ油|≥0.5%`（时间对齐 + 方向一致）；CLOSE = `回吐>50% 或 静默≥6h`；冷却 `3h`；每事件 `≤3` 次推送。
- 新增/修改模块须同步更新 `config/module_registry.json`。
- DB schema 变更走 `/db-migration`（迁移 + 回滚脚本）；SQLite 用 `ADD COLUMN`，对既有行安全。
- 错误隔离：单事件/取价/LLM 失败不得中断 sweep 或调度器其他 tick。

---

## 文件结构

| 文件 | 动作 | 职责 |
|------|------|------|
| `config/event-escalation.json` | 新 | 全部阈值 |
| `config/loader.py` | 改 | 加 `load_event_escalation()` |
| `storage/models.py` | 改 | EventLine 加 5 字段 |
| `storage/database.py` | 改 | 迁移 + `get_active_event_lines` / `update_event_escalation` / `get_event_members` / `get_peak_impact_for_news_ids` |
| `engine/alert_dispatcher.py` | 改 | 加 `dispatch_event()` |
| `engine/market_snapshot.py` | 新 | 自指定时刻起的 ΔSPX/ΔVIX/Δ布伦特 |
| `engine/cluster.py` | 改 | 修 `find_or_create_event` 让第二条印证新闻建簇 + 回填动量字段 |
| `engine/event_escalator.py` | 新 | 状态机 + sweep |
| `collector/scheduler.py` | 改 | DI `cluster` / `escalator`；`_insert_and_notify` 聚类；`_tick_5min` sweep |
| `main.py` | 改 | 实例化 cluster + market_snapshot + escalator 并注入 scheduler |
| `scripts/migrate_event_escalation.py` | 新 | 迁移 + 回滚 |

---

## Task 1: 升级配置 + 加载器

**Files:**
- Create: `news-monitor/config/event-escalation.json`
- Modify: `news-monitor/config/loader.py`
- Test: `news-monitor/tests/test_event_escalation_config.py`

**Interfaces:**
- Produces: `ConfigLoader.load_event_escalation() -> dict`（含键 `alert_trigger`/`market_confirm`/`close`/`cooldown_hours`/`max_pushes_per_event`）

- [ ] **Step 1: 写配置文件**

```json
{
  "alert_trigger": { "min_source_count": 3, "min_peak_impact": 70, "active_window_hours": 12 },
  "market_confirm": {
    "spx_pct": 0.2, "vix_pct": 5.0, "brent_pct": 0.5,
    "time_aligned": true, "direction_gated": true,
    "oil_relevant_categories": ["geopolitical", "macro_data"]
  },
  "close": { "reversal_retrace_pct": 50, "silence_hours": 6 },
  "cooldown_hours": 3,
  "max_pushes_per_event": 3,
  "sweep_interval_minutes": 5
}
```

- [ ] **Step 2: 写失败测试**

```python
# tests/test_event_escalation_config.py
from config.loader import ConfigLoader

def test_load_event_escalation_defaults():
    cfg = ConfigLoader().load_event_escalation()
    assert cfg["alert_trigger"]["min_source_count"] == 3
    assert cfg["alert_trigger"]["min_peak_impact"] == 70
    assert cfg["market_confirm"]["spx_pct"] == 0.2
    assert cfg["market_confirm"]["vix_pct"] == 5.0
    assert cfg["market_confirm"]["brent_pct"] == 0.5
    assert cfg["close"]["silence_hours"] == 6
    assert cfg["cooldown_hours"] == 3
    assert cfg["max_pushes_per_event"] == 3
```

- [ ] **Step 3: 运行确认失败**

Run: `cd news-monitor && python -m pytest tests/test_event_escalation_config.py -v`
Expected: FAIL — `AttributeError: 'ConfigLoader' object has no attribute 'load_event_escalation'`

- [ ] **Step 4: 实现加载器**

在 `config/loader.py` 中，参照现有 `load_settings` 的风格（同目录读取 + 缓存）加入：

```python
import json
from pathlib import Path

def load_event_escalation(self) -> dict:
    """Load event-escalation thresholds (config/event-escalation.json)."""
    path = Path(__file__).resolve().parent / "event-escalation.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
```

- [ ] **Step 5: 运行确认通过**

Run: `cd news-monitor && python -m pytest tests/test_event_escalation_config.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add news-monitor/config/event-escalation.json news-monitor/config/loader.py news-monitor/tests/test_event_escalation_config.py
git commit -m "feat: event-escalation config + loader"
```

---

## Task 2: EventLine 字段 + DB 迁移 + 查询方法

**Files:**
- Modify: `news-monitor/storage/models.py` (EventLine dataclass)
- Modify: `news-monitor/storage/database.py`
- Test: `news-monitor/tests/test_event_escalation_db.py`

**Interfaces:**
- Consumes: `Database._get_conn()`, `Database.get_recent_news(hours)`
- Produces:
  - `EventLine.escalation_state: str='NONE'`, `peak_impact: float=0.0`, `dominant_category: str=''`, `dominant_sentiment: str=''`, `alerted_at: Optional[datetime]=None`
  - `Database.migrate_event_escalation() -> None` (幂等 ADD COLUMN)
  - `Database.get_active_event_lines(active_window_hours: int) -> list[dict]`
  - `Database.update_event_escalation(event_id: int, **fields) -> None`
  - `Database.get_event_members(event_id: int) -> list[dict]`
  - `Database.get_peak_impact_for_news_ids(news_ids: list[int]) -> tuple[float, str, str]`  # (peak_impact, category, sentiment)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_event_escalation_db.py
import pytest
from storage.database import Database
from storage.models import NewsItem, EventLine, ImpactAssessment

@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    d.migrate_event_escalation()
    return d

def test_migration_adds_columns(db):
    with db._get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_lines)").fetchall()}
    assert {"escalation_state", "peak_impact", "dominant_category",
            "dominant_sentiment", "alerted_at"} <= cols

def test_migration_idempotent(db):
    db.migrate_event_escalation()  # second call must not raise
    assert True

def test_update_and_read_escalation(db):
    with db._get_conn() as conn:
        conn.execute("INSERT INTO event_lines (title, news_ids, source_count, "
                     "first_seen, last_updated, is_active) VALUES "
                     "('US-Iran', '1,2,3', 3, datetime('now'), datetime('now'), 1)")
    db.update_event_escalation(1, escalation_state="ALERTED", peak_impact=95.0)
    rows = db.get_active_event_lines(active_window_hours=12)
    assert rows[0]["escalation_state"] == "ALERTED"
    assert rows[0]["peak_impact"] == 95.0

def test_peak_impact_for_news_ids(db):
    a = ImpactAssessment(news_id=1, impact_score=40, event_category="geopolitical", sentiment="BEARISH")
    b = ImpactAssessment(news_id=2, impact_score=95, event_category="geopolitical", sentiment="BEARISH")
    db.insert_assessment(a); db.insert_assessment(b)
    peak, cat, sent = db.get_peak_impact_for_news_ids([1, 2])
    assert peak == 95
    assert cat == "geopolitical"
    assert sent == "BEARISH"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd news-monitor && python -m pytest tests/test_event_escalation_db.py -v`
Expected: FAIL — `AttributeError: ... 'migrate_event_escalation'`

- [ ] **Step 3: EventLine 加字段**

在 `storage/models.py` 的 `EventLine` dataclass 末尾追加：

```python
    escalation_state: str = "NONE"      # NONE|ALERTED|CONFIRMED|CLOSED
    peak_impact: float = 0.0
    dominant_category: str = ""
    dominant_sentiment: str = ""
    alerted_at: Optional[datetime] = None
```

- [ ] **Step 4: 实现迁移 + 查询方法**

在 `storage/database.py` 加入（`ADD COLUMN` 幂等，检查 PRAGMA）：

```python
def migrate_event_escalation(self) -> None:
    """Idempotently add escalation columns to event_lines."""
    cols_defs = [
        ("escalation_state", "TEXT DEFAULT 'NONE'"),
        ("peak_impact", "REAL DEFAULT 0.0"),
        ("dominant_category", "TEXT DEFAULT ''"),
        ("dominant_sentiment", "TEXT DEFAULT ''"),
        ("alerted_at", "TEXT"),
    ]
    with self._get_conn() as conn:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(event_lines)").fetchall()}
        for name, ddl in cols_defs:
            if name not in existing:
                conn.execute(f"ALTER TABLE event_lines ADD COLUMN {name} {ddl}")

def get_active_event_lines(self, active_window_hours: int = 12) -> list[dict]:
    with self._get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM event_lines WHERE is_active = 1 "
            "AND last_updated > datetime('now', ?) "
            "ORDER BY last_updated DESC",
            (f"-{active_window_hours} hours",),
        ).fetchall()
        return [dict(r) for r in rows]

def update_event_escalation(self, event_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with self._get_conn() as conn:
        conn.execute(f"UPDATE event_lines SET {cols} WHERE id = ?",
                     (*fields.values(), event_id))

def get_event_members(self, event_id: int) -> list[dict]:
    with self._get_conn() as conn:
        row = conn.execute("SELECT news_ids FROM event_lines WHERE id = ?",
                           (event_id,)).fetchone()
        if not row or not row["news_ids"]:
            return []
        ids = [int(x) for x in row["news_ids"].split(",") if x.strip().isdigit()]
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        members = conn.execute(
            f"SELECT * FROM news WHERE id IN ({ph})", ids
        ).fetchall()
        return [dict(m) for m in members]

def get_peak_impact_for_news_ids(self, news_ids: list[int]) -> tuple[float, str, str]:
    if not news_ids:
        return (0.0, "", "")
    ph = ",".join("?" * len(news_ids))
    with self._get_conn() as conn:
        row = conn.execute(
            f"SELECT impact_score, event_category, sentiment FROM impact_assessments "
            f"WHERE news_id IN ({ph}) ORDER BY impact_score DESC LIMIT 1", news_ids
        ).fetchone()
        if not row:
            return (0.0, "", "")
        return (float(row["impact_score"] or 0), row["event_category"] or "", row["sentiment"] or "")
```

同时在 `event_lines` 建表 SQL（fresh DB 路径）中加入相同列，避免新库缺列。

- [ ] **Step 5: 运行确认通过**

Run: `cd news-monitor && python -m pytest tests/test_event_escalation_db.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 提交**

```bash
git add news-monitor/storage/models.py news-monitor/storage/database.py news-monitor/tests/test_event_escalation_db.py
git commit -m "feat: EventLine escalation fields + migration + queries"
```

---

## Task 3: AlertDispatcher 事件级入口 `dispatch_event`

**Files:**
- Modify: `news-monitor/engine/alert_dispatcher.py`
- Test: `news-monitor/tests/test_dispatch_event.py`

**Interfaces:**
- Consumes: `AlertLevel`, `AlertDispatcher._pushover_emergency`, `_pushover_high`, `_telegram_triple`, `pushover_available`
- Produces: `AlertDispatcher.dispatch_event(event: dict, level: AlertLevel, telegram_push_fn=None) -> DispatchResult`
  - `event` 键：`title`, `source_count`, `peak_impact`, `market_note`(可选), `url`(可选)
  - CRITICAL→pushover_emergency + telegram_triple；IMPORTANT→pushover_high + telegram_alert；NORMAL→telegram_alert（不打电话）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_dispatch_event.py
import pytest
from engine.alert_dispatcher import AlertDispatcher, AlertLevel

@pytest.mark.asyncio
async def test_dispatch_event_important_calls_telegram(monkeypatch):
    d = AlertDispatcher()
    sent = []
    async def fake_push(item, disable_notification=True):
        sent.append((item["title"], disable_notification))
    # no pushover creds → pushover skipped, telegram still fires
    res = await d.dispatch_event(
        {"title": "美伊冲突升级", "source_count": 4, "peak_impact": 95},
        AlertLevel.IMPORTANT, telegram_push_fn=fake_push,
    )
    assert "telegram_alert" in res.channels_used
    assert sent and sent[0][1] is False  # not silent

@pytest.mark.asyncio
async def test_dispatch_event_normal_is_silent(monkeypatch):
    d = AlertDispatcher()
    sent = []
    async def fake_push(item, disable_notification=True):
        sent.append(disable_notification)
    res = await d.dispatch_event(
        {"title": "事件降级", "source_count": 4, "peak_impact": 60},
        AlertLevel.NORMAL, telegram_push_fn=fake_push,
    )
    assert sent == [True]  # silent
```

- [ ] **Step 2: 运行确认失败**

Run: `cd news-monitor && python -m pytest tests/test_dispatch_event.py -v`
Expected: FAIL — `AttributeError: ... 'dispatch_event'`

- [ ] **Step 3: 实现 `dispatch_event`**

在 `alert_dispatcher.py` `AlertDispatcher` 类内加入（复用现有 pushover/telegram 方法；body 用模板，LLM 文案为可选增强，失败回退模板）：

```python
def _format_event_body(self, event: dict) -> str:
    parts = [
        f"📊 事件级警报 · {event.get('source_count', 0)} 家来源印证",
        f"峰值影响 {int(event.get('peak_impact', 0))}",
    ]
    if event.get("market_note"):
        parts.append(event["market_note"])
    return " | ".join(parts)

async def dispatch_event(self, event: dict, level, telegram_push_fn=None):
    from engine.alert_dispatcher import AlertLevel, DispatchResult  # local to avoid cycle
    channels: list[str] = []
    body = self._format_event_body(event)
    item = {
        "title": event.get("title", ""),
        "source": f"事件聚合({event.get('source_count', 0)}源)",
        "url": event.get("url", ""),
        "_event_body": body,
    }
    if level == AlertLevel.CRITICAL:
        logger.warning("EVENT CRITICAL: %s | %s", item["title"][:80], body)
        if self.pushover_available:
            await self._pushover_emergency(item); channels.append("pushover_emergency")
        if telegram_push_fn:
            await self._telegram_triple(item, telegram_push_fn); channels.append("telegram_triple")
    elif level == AlertLevel.IMPORTANT:
        logger.info("EVENT IMPORTANT: %s | %s", item["title"][:80], body)
        if self.pushover_available:
            await self._pushover_high(item); channels.append("pushover_high")
        if telegram_push_fn:
            await telegram_push_fn(item, disable_notification=False); channels.append("telegram_alert")
    else:  # NORMAL — close/de-escalation, telegram only, silent
        if telegram_push_fn:
            await telegram_push_fn(item, disable_notification=True); channels.append("telegram_alert")
    return DispatchResult(level=level, channels_used=channels, reason=body)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd news-monitor && python -m pytest tests/test_dispatch_event.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add news-monitor/engine/alert_dispatcher.py news-monitor/tests/test_dispatch_event.py
git commit -m "feat: AlertDispatcher.dispatch_event for event-level alerts"
```

---

## Task 4: MarketSnapshot（复用 yfinance + 加油价）

**Files:**
- Create: `news-monitor/engine/market_snapshot.py`
- Test: `news-monitor/tests/test_market_snapshot.py`

**Interfaces:**
- Produces: `MarketSnapshot.since(start_time: datetime) -> dict`（键 `spx_pct`, `vix_pct`, `brent_pct`；取价失败对应键为 `None`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_market_snapshot.py
import pytest
from datetime import datetime, timedelta
from engine.market_snapshot import MarketSnapshot

@pytest.mark.asyncio
async def test_since_returns_pct_dict(monkeypatch):
    ms = MarketSnapshot()
    async def fake_change(symbol, start):
        return {"^GSPC": -0.45, "^VIX": 16.6, "BZ=F": 5.9}[symbol]
    monkeypatch.setattr(ms, "_pct_change_since", fake_change)
    out = await ms.since(datetime.now() - timedelta(hours=1))
    assert out["spx_pct"] == -0.45
    assert out["vix_pct"] == 16.6
    assert out["brent_pct"] == 5.9

@pytest.mark.asyncio
async def test_since_handles_fetch_failure(monkeypatch):
    ms = MarketSnapshot()
    async def boom(symbol, start):
        raise RuntimeError("yfinance down")
    monkeypatch.setattr(ms, "_pct_change_since", boom)
    out = await ms.since(datetime.now())
    assert out == {"spx_pct": None, "vix_pct": None, "brent_pct": None}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd news-monitor && python -m pytest tests/test_market_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.market_snapshot`

- [ ] **Step 3: 实现 MarketSnapshot**

```python
# engine/market_snapshot.py
"""Point-in-time market delta since a reference time. Reuses yfinance."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime

import yfinance as yf

logger = logging.getLogger(__name__)

_SPX, _VIX, _BRENT = "^GSPC", "^VIX", "BZ=F"


class MarketSnapshot:
    async def _pct_change_since(self, symbol: str, start: datetime) -> float | None:
        """% change of `symbol` from the close/price at `start` to latest."""
        def _fetch():
            hist = yf.Ticker(symbol).history(period="1d", interval="5m")
            if hist is None or hist.empty:
                return None
            after = hist[hist.index >= start.astimezone(hist.index.tz)] if hist.index.tz else hist
            base = after["Close"].iloc[0] if not after.empty else hist["Close"].iloc[0]
            last = hist["Close"].iloc[-1]
            if not base:
                return None
            return round((last - base) / base * 100, 3)
        try:
            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning("MarketSnapshot %s failed: %s", symbol, e)
            return None

    async def since(self, start_time: datetime) -> dict:
        try:
            spx, vix, brent = await asyncio.gather(
                self._pct_change_since(_SPX, start_time),
                self._pct_change_since(_VIX, start_time),
                self._pct_change_since(_BRENT, start_time),
            )
            return {"spx_pct": spx, "vix_pct": vix, "brent_pct": brent}
        except Exception as e:
            logger.warning("MarketSnapshot.since failed: %s", e)
            return {"spx_pct": None, "vix_pct": None, "brent_pct": None}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd news-monitor && python -m pytest tests/test_market_snapshot.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add news-monitor/engine/market_snapshot.py news-monitor/tests/test_market_snapshot.py
git commit -m "feat: MarketSnapshot — delta since reference time (SPX/VIX/Brent)"
```

---

## Task 5: 激活并修复聚类（第二条印证新闻建簇）

**Files:**
- Modify: `news-monitor/engine/cluster.py`
- Test: `news-monitor/tests/test_cluster.py` (追加)

**Interfaces:**
- Consumes: `Database.get_recent_news(hours)`, `Database.update_news_status(id, status, **kwargs)`, `Database._get_conn`
- Produces: `NewsCluster.find_or_create_event(item)` 现在会在发现相似**孤立**近期新闻时创建 EventLine（含双方），返回新 `event_line_id`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cluster.py (追加)
def test_second_similar_article_creates_event(cluster, mock_db):
    # 现有 mock_db fixture 模式；recent 含一条无 event_line_id 的相似孤立新闻
    from storage.models import NewsItem
    existing = {"id": 1, "title": "US strikes Iran nuclear sites", "event_line_id": None}
    mock_db.get_recent_news.return_value = [existing]
    item = NewsItem(id=2, title="US launches strikes on Iran targets")
    event_id = cluster.find_or_create_event(item)
    assert event_id is not None  # 第二条印证 → 建簇
```

- [ ] **Step 2: 运行确认失败**

Run: `cd news-monitor && python -m pytest tests/test_cluster.py::TestNewsCluster::test_second_similar_article_creates_event -v`
Expected: FAIL — 返回 None（当前 singleton 不建簇）

- [ ] **Step 3: 修复 `find_or_create_event`**

在 `cluster.py` `find_or_create_event` 里，`best_match` 为空的分支替换为：查找相似的**孤立**近期新闻，命中则建簇并把两条都挂上：

```python
        if best_match:
            self._add_to_event(item, best_match)
            return best_match

        # No existing event line — check for a similar *singleton* to seed a new event.
        seed = self._find_similar_singleton(item, recent)
        if seed:
            event_id = self._create_event(item)
            # attach the seed article too
            self.db.update_news_status(seed["id"], seed.get("status", "pending"),
                                       event_line_id=event_id)
            self._add_to_event(item, event_id)
            return event_id
        return None
```

并新增辅助方法：

```python
    def _find_similar_singleton(self, item, recent):
        """Find a recent article with no event_line_id that is similar enough."""
        best_score, best = 0.0, None
        for r in recent:
            if r.get("event_line_id"):
                continue
            if r.get("id") == item.id:
                continue
            score = DedupManager.title_similarity(item.title, r.get("title", ""))
            if score > best_score and score >= SIMILARITY_THRESHOLD:
                best_score, best = score, r
        return best
```

- [ ] **Step 4: 运行确认通过（含回归）**

Run: `cd news-monitor && python -m pytest tests/test_cluster.py -v`
Expected: PASS（新用例 + 原有全绿）

- [ ] **Step 5: 提交**

```bash
git add news-monitor/engine/cluster.py news-monitor/tests/test_cluster.py
git commit -m "fix: cluster forms event line on second corroborating article"
```

---

## Task 6: EventEscalator — 动量 + ALERT 触发（NONE→ALERTED）

**Files:**
- Create: `news-monitor/engine/event_escalator.py`
- Test: `news-monitor/tests/test_event_escalator.py`

**Interfaces:**
- Consumes: `ConfigLoader.load_event_escalation`, `Database.get_active_event_lines`, `get_event_members`, `get_peak_impact_for_news_ids`, `update_event_escalation`, `AlertDispatcher.dispatch_event`, `AlertLevel`, `MarketSnapshot`
- Produces:
  - `EventEscalator(db, dispatcher, market, config_loader, telegram_push_provider=None)`
  - `EventEscalator.compute_momentum(event: dict) -> dict`（键 `source_count`, `peak_impact`, `category`, `sentiment`）
  - `EventEscalator.evaluate(event: dict) -> Optional[str]`（返回发生的转换名或 None）
  - `EventEscalator.sweep() -> None`（Task 8 补全循环）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_event_escalator.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from engine.event_escalator import EventEscalator
from engine.alert_dispatcher import AlertLevel

@pytest.fixture
def esc():
    db = MagicMock()
    cfg = MagicMock()
    cfg.load_event_escalation.return_value = {
        "alert_trigger": {"min_source_count": 3, "min_peak_impact": 70, "active_window_hours": 12},
        "market_confirm": {"spx_pct": 0.2, "vix_pct": 5.0, "brent_pct": 0.5,
                           "time_aligned": True, "direction_gated": True,
                           "oil_relevant_categories": ["geopolitical", "macro_data"]},
        "close": {"reversal_retrace_pct": 50, "silence_hours": 6},
        "cooldown_hours": 3, "max_pushes_per_event": 3,
    }
    dispatcher = MagicMock()
    dispatcher.dispatch_event = AsyncMock()
    market = MagicMock()
    return EventEscalator(db, dispatcher, market, cfg)

@pytest.mark.asyncio
async def test_alert_trigger_fires(esc):
    esc.db.get_event_members.return_value = [{"id": 1, "source": "A"}, {"id": 2, "source": "B"}, {"id": 3, "source": "C"}]
    esc.db.get_peak_impact_for_news_ids.return_value = (95.0, "geopolitical", "BEARISH")
    event = {"id": 10, "escalation_state": "NONE", "title": "US-Iran", "news_ids": "1,2,3", "source_count": 3}
    transition = await esc.evaluate(event)
    assert transition == "NONE->ALERTED"
    esc.dispatcher.dispatch_event.assert_awaited_once()
    args, kwargs = esc.dispatcher.dispatch_event.call_args
    assert args[1] == AlertLevel.IMPORTANT
    esc.db.update_event_escalation.assert_called()  # state persisted

@pytest.mark.asyncio
async def test_no_alert_below_threshold(esc):
    esc.db.get_event_members.return_value = [{"id": 1, "source": "A"}, {"id": 2, "source": "B"}]
    esc.db.get_peak_impact_for_news_ids.return_value = (95.0, "geopolitical", "BEARISH")
    event = {"id": 11, "escalation_state": "NONE", "title": "x", "news_ids": "1,2", "source_count": 2}
    assert await esc.evaluate(event) is None
    esc.dispatcher.dispatch_event.assert_not_awaited()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd news-monitor && python -m pytest tests/test_event_escalator.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.event_escalator`

- [ ] **Step 3: 实现 escalator 骨架 + ALERT 转换**

```python
# engine/event_escalator.py
"""Event-level escalation state machine (NONE→ALERTED→CONFIRMED→CLOSED)."""
from __future__ import annotations
import logging
from datetime import datetime

from engine.alert_dispatcher import AlertLevel

logger = logging.getLogger(__name__)


class EventEscalator:
    def __init__(self, db, dispatcher, market, config_loader, telegram_push_provider=None):
        self.db = db
        self.dispatcher = dispatcher
        self.market = market
        self._cfg = config_loader.load_event_escalation()
        self._tg_provider = telegram_push_provider  # zero-arg callable -> telegram_push_fn|None

    def _tg(self):
        return self._tg_provider() if self._tg_provider else None

    def compute_momentum(self, event: dict) -> dict:
        members = self.db.get_event_members(event["id"])
        source_count = len({m.get("source", "") for m in members if m.get("source")})
        ids = [m["id"] for m in members if m.get("id")]
        peak, category, sentiment = self.db.get_peak_impact_for_news_ids(ids)
        return {"source_count": max(source_count, event.get("source_count", 0)),
                "peak_impact": peak, "category": category, "sentiment": sentiment}

    async def evaluate(self, event: dict):
        state = event.get("escalation_state", "NONE")
        if state == "NONE":
            return await self._maybe_alert(event)
        # CONFIRMED / CLOSE handled in Task 7 / Task 8
        return None

    async def _maybe_alert(self, event: dict):
        m = self.compute_momentum(event)
        t = self._cfg["alert_trigger"]
        if m["source_count"] >= t["min_source_count"] and m["peak_impact"] >= t["min_peak_impact"]:
            await self.dispatcher.dispatch_event(
                {"title": event.get("title", ""), "source_count": m["source_count"],
                 "peak_impact": m["peak_impact"]},
                AlertLevel.IMPORTANT, telegram_push_fn=self._tg(),
            )
            self.db.update_event_escalation(
                event["id"], escalation_state="ALERTED",
                peak_impact=m["peak_impact"], dominant_category=m["category"],
                dominant_sentiment=m["sentiment"], alerted_at=datetime.now().isoformat(),
            )
            logger.warning("Event #%s ALERTED (src=%d peak=%d)",
                           event["id"], m["source_count"], int(m["peak_impact"]))
            return "NONE->ALERTED"
        return None
```

- [ ] **Step 4: 运行确认通过**

Run: `cd news-monitor && python -m pytest tests/test_event_escalator.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add news-monitor/engine/event_escalator.py news-monitor/tests/test_event_escalator.py
git commit -m "feat: EventEscalator momentum + ALERT trigger"
```

---

## Task 7: EventEscalator — 市场确认（ALERTED→CONFIRMED）

**Files:**
- Modify: `news-monitor/engine/event_escalator.py`
- Test: `news-monitor/tests/test_event_escalator.py` (追加)

**Interfaces:**
- Consumes: `MarketSnapshot.since`, `event["alerted_at"]`, `event["dominant_sentiment"]`, `event["dominant_category"]`
- Produces: `EventEscalator._market_confirmed(event) -> tuple[bool, str]`；`evaluate` 对 ALERTED 态调用之，确认则发 CRITICAL 并转 CONFIRMED

- [ ] **Step 1: 写失败测试**

```python
# tests/test_event_escalator.py (追加)
from unittest.mock import AsyncMock
from datetime import datetime, timedelta

@pytest.mark.asyncio
async def test_market_confirm_bearish_down(esc):
    esc.market.since = AsyncMock(return_value={"spx_pct": -0.45, "vix_pct": 16.6, "brent_pct": 5.9})
    event = {"id": 10, "escalation_state": "ALERTED", "title": "US-Iran",
             "alerted_at": (datetime.now()-timedelta(hours=1)).isoformat(),
             "dominant_sentiment": "BEARISH", "dominant_category": "geopolitical"}
    transition = await esc.evaluate(event)
    assert transition == "ALERTED->CONFIRMED"
    args, kwargs = esc.dispatcher.dispatch_event.call_args
    assert args[1] == AlertLevel.CRITICAL

@pytest.mark.asyncio
async def test_market_confirm_wrong_direction_blocked(esc):
    # bearish event but market went UP → not confirmed
    esc.market.since = AsyncMock(return_value={"spx_pct": +0.8, "vix_pct": -3.0, "brent_pct": -1.0})
    event = {"id": 10, "escalation_state": "ALERTED", "title": "x",
             "alerted_at": (datetime.now()-timedelta(hours=1)).isoformat(),
             "dominant_sentiment": "BEARISH", "dominant_category": "geopolitical"}
    assert await esc.evaluate(event) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd news-monitor && python -m pytest tests/test_event_escalator.py -k market_confirm -v`
Expected: FAIL — ALERTED 态目前返回 None

- [ ] **Step 3: 实现市场确认**

在 `event_escalator.py` 的 `evaluate` 里，把 ALERTED 分支接上，并新增 `_market_confirmed`：

```python
    async def evaluate(self, event: dict):
        state = event.get("escalation_state", "NONE")
        if state == "NONE":
            return await self._maybe_alert(event)
        if state == "ALERTED":
            return await self._maybe_confirm(event)
        return None

    async def _maybe_confirm(self, event: dict):
        confirmed, note = await self._market_confirmed(event)
        if not confirmed:
            return None
        await self.dispatcher.dispatch_event(
            {"title": event.get("title", ""), "source_count": event.get("source_count", 0),
             "peak_impact": event.get("peak_impact", 0), "market_note": note},
            AlertLevel.CRITICAL, telegram_push_fn=self._tg(),
        )
        self.db.update_event_escalation(event["id"], escalation_state="CONFIRMED")
        logger.warning("Event #%s CONFIRMED by market (%s)", event["id"], note)
        return "ALERTED->CONFIRMED"

    async def _market_confirmed(self, event: dict) -> tuple[bool, str]:
        alerted_at = event.get("alerted_at")
        if not alerted_at:
            return (False, "")
        start = datetime.fromisoformat(alerted_at)
        mc = self._cfg["market_confirm"]
        snap = await self.market.since(start)
        sent = (event.get("dominant_sentiment") or "").upper()
        bearish = "BEAR" in sent  # BEARISH / CAUTIOUSLY_BEARISH
        spx, vix, oil = snap.get("spx_pct"), snap.get("vix_pct"), snap.get("brent_pct")
        # VIX up = risk-off, direction-agnostic to bull/bear
        if vix is not None and vix >= mc["vix_pct"]:
            return (True, f"VIX +{vix:.1f}%")
        if spx is not None:
            if bearish and spx <= -mc["spx_pct"]:
                return (True, f"SPX {spx:.2f}%")
            if not bearish and spx >= mc["spx_pct"]:
                return (True, f"SPX +{spx:.2f}%")
        if oil is not None and event.get("dominant_category") in mc["oil_relevant_categories"]:
            if bearish and oil >= mc["brent_pct"]:  # supply-risk → oil up
                return (True, f"Brent +{oil:.1f}%")
        return (False, "")
```

- [ ] **Step 4: 运行确认通过**

Run: `cd news-monitor && python -m pytest tests/test_event_escalator.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add news-monitor/engine/event_escalator.py news-monitor/tests/test_event_escalator.py
git commit -m "feat: EventEscalator market confirmation (time-aligned + direction gate)"
```

---

## Task 8: EventEscalator — CLOSE + 冷却 + 幂等 + sweep 循环

**Files:**
- Modify: `news-monitor/engine/event_escalator.py`
- Test: `news-monitor/tests/test_event_escalator.py` (追加)

**Interfaces:**
- Consumes: `event["last_updated"]`, `Database.get_active_event_lines`
- Produces: `EventEscalator.sweep()`（遍历活跃事件，逐个 `evaluate`，异常隔离）；CLOSE 转换；冷却与幂等

- [ ] **Step 1: 写失败测试**

```python
# tests/test_event_escalator.py (追加)
@pytest.mark.asyncio
async def test_close_on_silence(esc):
    old = (datetime.now()-timedelta(hours=7)).isoformat()
    event = {"id": 10, "escalation_state": "CONFIRMED", "title": "x",
             "last_updated": old, "source_count": 4, "peak_impact": 95}
    transition = await esc.evaluate(event)
    assert transition and transition.endswith("->CLOSED")
    args, kwargs = esc.dispatcher.dispatch_event.call_args
    assert args[1] == AlertLevel.NORMAL  # telegram only

@pytest.mark.asyncio
async def test_sweep_isolates_errors(esc):
    esc.db.get_active_event_lines.return_value = [
        {"id": 1, "escalation_state": "NONE", "news_ids": "1", "source_count": 1, "title": "a"},
        {"id": 2, "escalation_state": "NONE", "news_ids": "2", "source_count": 1, "title": "b"},
    ]
    async def boom(ev):
        raise RuntimeError("bad event")
    esc.evaluate = boom  # both raise
    await esc.sweep()  # must not raise
    assert True
```

- [ ] **Step 2: 运行确认失败**

Run: `cd news-monitor && python -m pytest tests/test_event_escalator.py -k "close_on_silence or sweep_isolates" -v`
Expected: FAIL — CONFIRMED 态返回 None；`sweep` 不存在

- [ ] **Step 3: 实现 CLOSE + sweep**

在 `event_escalator.py` 加入，并把 `evaluate` 的 CONFIRMED/ALERTED 态接入 CLOSE 判定：

```python
    async def evaluate(self, event: dict):
        state = event.get("escalation_state", "NONE")
        if state == "NONE":
            return await self._maybe_alert(event)
        if state == "ALERTED":
            closed = await self._maybe_close(event)
            return closed or await self._maybe_confirm(event)
        if state == "CONFIRMED":
            return await self._maybe_close(event)
        return None

    async def _maybe_close(self, event: dict):
        last = event.get("last_updated")
        if not last:
            return None
        silence_h = self._cfg["close"]["silence_hours"]
        age = (datetime.now() - datetime.fromisoformat(str(last))).total_seconds() / 3600
        if age >= silence_h:
            await self.dispatcher.dispatch_event(
                {"title": f"事件收尾 — {event.get('title','')}",
                 "source_count": event.get("source_count", 0),
                 "peak_impact": event.get("peak_impact", 0),
                 "market_note": f"静默{int(age)}h，事件降温"},
                AlertLevel.NORMAL, telegram_push_fn=self._tg(),
            )
            prev = event.get("escalation_state", "")
            self.db.update_event_escalation(event["id"], escalation_state="CLOSED", is_active=0)
            logger.info("Event #%s CLOSED (silence %.1fh)", event["id"], age)
            return f"{prev}->CLOSED"
        return None

    async def sweep(self) -> None:
        try:
            window = self._cfg["alert_trigger"]["active_window_hours"]
            events = self.db.get_active_event_lines(active_window_hours=window)
        except Exception as e:
            logger.error("EventEscalator.sweep list failed: %s", e)
            return
        for ev in events:
            try:
                await self.evaluate(ev)
            except Exception as e:
                logger.error("EventEscalator evaluate failed for #%s: %s", ev.get("id"), e)
```

> 幂等说明：`evaluate` 按 `escalation_state` 分派，每态只发一次对应推送并立即写库改态；同一事件二次 sweep 时状态已推进，不会重复推。冷却由 `alerted_at` + 状态机天然实现（ALERTED 态只会转 CONFIRMED/CLOSED，不会再发 ALERT）。

- [ ] **Step 4: 运行确认通过**

Run: `cd news-monitor && python -m pytest tests/test_event_escalator.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add news-monitor/engine/event_escalator.py news-monitor/tests/test_event_escalator.py
git commit -m "feat: EventEscalator CLOSE + sweep loop with error isolation"
```

---

## Task 9: 接线 — 调度器聚类 + sweep + main.py 装配

**Files:**
- Modify: `news-monitor/collector/scheduler.py`
- Modify: `news-monitor/main.py`
- Test: `news-monitor/tests/test_scheduler.py` (追加)

**Interfaces:**
- Consumes: `NewsCluster.find_or_create_event`, `EventEscalator.sweep`
- Produces: `NewsScheduler(config, db, dedup=None, cluster=None, escalator=None)`；`_insert_and_notify` 聚类；`_tick_5min` 末尾 sweep

- [ ] **Step 1: 写失败测试**

```python
# tests/test_scheduler.py (追加)
@pytest.mark.asyncio
async def test_tick_5min_runs_escalator_sweep(scheduler_setup):
    s = scheduler_setup
    from unittest.mock import AsyncMock
    s.escalator = AsyncMock()
    await s._tick_5min()
    s.escalator.sweep.assert_awaited_once()

@pytest.mark.asyncio
async def test_insert_and_notify_clusters(scheduler_setup):
    s = scheduler_setup
    from unittest.mock import MagicMock
    from storage.models import NewsItem
    s.cluster = MagicMock()
    await s._insert_and_notify([NewsItem(id=5, title="US strikes Iran")])
    s.cluster.find_or_create_event.assert_called()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd news-monitor && python -m pytest tests/test_scheduler.py -k "escalator_sweep or clusters" -v`
Expected: FAIL — `escalator`/`cluster` 未接入

- [ ] **Step 3: 改调度器 DI + 接线**

`scheduler.py` `__init__` 签名与字段：

```python
    def __init__(self, config: ConfigLoader, db: Database, dedup=None, cluster=None, escalator=None):
        ...
        self.dedup = dedup
        self.cluster = cluster
        self.escalator = escalator
```

`_insert_and_notify` 在 insert+index 之后、notify 之前加聚类：

```python
        for item in items:
            self.db.insert_news(item)
            if self.dedup:
                self.dedup.index_item(item)
            if self.cluster:
                try:
                    self.cluster.find_or_create_event(item)
                except Exception as e:
                    logger.debug("cluster failed for %s: %s", item.id, e)

        await self._notify_callbacks(items)
```

`_tick_5min` 末尾（`_insert_and_notify` 之后）加 sweep：

```python
        if items:
            await self._insert_and_notify(items)

        if self.escalator:
            try:
                await self.escalator.sweep()
            except Exception as e:
                logger.error("escalator sweep failed: %s", e)
```

- [ ] **Step 4: main.py 装配**

在 `main.py` `__init__` 中：迁移 + 实例化 cluster/market/escalator，并注入 scheduler。

- 在 `self.db = Database(db_path)`（~L106）之后：`self.db.migrate_event_escalation()`
- 在 `self.vector_store = VectorStore(...)`（~L110）之后：
```python
        from engine.cluster import NewsCluster
        from engine.market_snapshot import MarketSnapshot
        from engine.event_escalator import EventEscalator
        self.cluster = NewsCluster(self.db, vector_store=self.vector_store)
        self.market_snapshot = MarketSnapshot()
```
- 在 `self.alert_dispatcher = AlertDispatcher()`（~L140）之后：
```python
        self.escalator = EventEscalator(
            self.db, self.alert_dispatcher, self.market_snapshot, self.config,
            telegram_push_provider=lambda: (
                self.alert_dispatcher.wrap_telegram_push(self.bot) if getattr(self, "bot", None) else None
            ),
        )
```
- 把 scheduler 构造（~L122）改为：
```python
        self.scheduler = NewsScheduler(
            self.config, self.db, self.dedup,
            cluster=self.cluster, escalator=self.escalator,
        )
```

> 注意：`self.bot` 若在 L122 之后才创建，`telegram_push_provider` 用 lambda 延迟取用，装配顺序无碍。

- [ ] **Step 5: 运行确认通过（含调度器回归）**

Run: `cd news-monitor && python -m pytest tests/test_scheduler.py -v`
Expected: PASS（新用例 + 原有全绿）

- [ ] **Step 6: 更新模块注册表 + 提交**

在 `config/module_registry.json` 为 `engine/event_escalator.py`、`engine/market_snapshot.py`、`engine/cluster.py` 补 `tests` 映射与 `related_scripts`。

```bash
git add news-monitor/collector/scheduler.py news-monitor/main.py news-monitor/tests/test_scheduler.py config/module_registry.json
git commit -m "feat: wire clustering + escalator sweep into scheduler/main"
```

---

## Task 10: 端到端集成测试（美伊场景）

**Files:**
- Test: `news-monitor/tests/test_event_escalation_e2e.py`

**Interfaces:**
- Consumes: 真实 `Database`（tmp）、`EventEscalator`、mock `AlertDispatcher.dispatch_event`、mock `MarketSnapshot.since`

- [ ] **Step 1: 写集成测试**

```python
# tests/test_event_escalation_e2e.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta
from storage.database import Database
from storage.models import NewsItem, ImpactAssessment, EventLine
from engine.event_escalator import EventEscalator
from engine.alert_dispatcher import AlertLevel
from config.loader import ConfigLoader

@pytest.mark.asyncio
async def test_us_iran_rolling_event(tmp_path):
    db = Database(str(tmp_path / "e2e.db"))
    db.migrate_event_escalation()
    # 3 家来源、峰值 impact 95 的美伊事件簇
    for i, src in enumerate(["ZeroHedge", "Reuters", "Bloomberg"], start=1):
        db.insert_news(NewsItem(id=i, title="US strikes Iran", source=src, status="fast_pushed"))
        db.insert_assessment(ImpactAssessment(news_id=i, impact_score=95 if i == 1 else 60,
                                              event_category="geopolitical", sentiment="BEARISH"))
    with db._get_conn() as conn:
        conn.execute("INSERT INTO event_lines (id, title, news_ids, source_count, "
                     "first_seen, last_updated, is_active, escalation_state) VALUES "
                     "(1,'US-Iran','1,2,3',3,datetime('now'),datetime('now'),1,'NONE')")

    dispatcher = MagicMock(); dispatcher.dispatch_event = AsyncMock()
    market = MagicMock()
    esc = EventEscalator(db, dispatcher, market, ConfigLoader())

    # sweep 1: NONE→ALERTED (响铃)
    await esc.sweep()
    assert dispatcher.dispatch_event.await_args_list[-1].args[1] == AlertLevel.IMPORTANT

    # 模拟市场向下 → sweep 2: ALERTED→CONFIRMED (警笛)
    market.since = AsyncMock(return_value={"spx_pct": -0.5, "vix_pct": 17.0, "brent_pct": 6.0})
    await esc.sweep()
    assert dispatcher.dispatch_event.await_args_list[-1].args[1] == AlertLevel.CRITICAL

    # 把 last_updated 拨到 7h 前 → sweep 3: CONFIRMED→CLOSED (Telegram 收尾)
    with db._get_conn() as conn:
        conn.execute("UPDATE event_lines SET last_updated = ? WHERE id = 1",
                     ((datetime.now()-timedelta(hours=7)).isoformat(),))
    await esc.sweep()
    assert dispatcher.dispatch_event.await_args_list[-1].args[1] == AlertLevel.NORMAL

    # 恰好 3 次推送，不刷屏
    assert dispatcher.dispatch_event.await_count == 3
```

- [ ] **Step 2: 运行确认通过**

Run: `cd news-monitor && python -m pytest tests/test_event_escalation_e2e.py -v`
Expected: PASS — 恰好 1×ALERT + 1×FLASH + 1×CLOSE

- [ ] **Step 3: 全量回归**

Run: `cd news-monitor && python -m pytest -q`
Expected: 全绿（原 353 + 新增用例）

- [ ] **Step 4: 提交**

```bash
git add news-monitor/tests/test_event_escalation_e2e.py
git commit -m "test: US-Iran rolling event e2e — exactly 3 pushes, no spam"
```

---

## Task 11: DB 迁移脚本 + 回滚 + 部署

**Files:**
- Create: `news-monitor/scripts/migrate_event_escalation.py`

**Interfaces:**
- Consumes: `Database.migrate_event_escalation`

- [ ] **Step 1: 写迁移/回滚脚本**

```python
# scripts/migrate_event_escalation.py
"""Apply or roll back event_lines escalation columns. Run inside container."""
import sys
from storage.database import Database

NEW_COLS = ["escalation_state", "peak_impact", "dominant_category",
            "dominant_sentiment", "alerted_at"]

def rollback(db_path: str):
    # SQLite ADD COLUMN is safe & additive; rollback = recreate without cols.
    db = Database(db_path)
    with db._get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(event_lines)").fetchall()
                if r[1] not in NEW_COLS]
        col_list = ", ".join(cols)
        conn.execute(f"CREATE TABLE event_lines_bak AS SELECT {col_list} FROM event_lines")
        conn.execute("DROP TABLE event_lines")
        conn.execute("ALTER TABLE event_lines_bak RENAME TO event_lines")
    print("rolled back escalation columns")

if __name__ == "__main__":
    path = sys.argv[2] if len(sys.argv) > 2 else "/app/data/news.db"
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback(path)
    else:
        Database(path).migrate_event_escalation()
        print("migration applied")
```

- [ ] **Step 2: 本地隔离验证（不碰生产）**

Run: `cd news-monitor && python -m pytest -q`
Expected: 全绿。

- [ ] **Step 3: 会话结束前检查**

Run: `python news-monitor/scripts/dev_checklist.py`
Expected: Git 干净 → 测试通过 → HISTORY.md 已更新 → 凭证完整 → 远程已同步

- [ ] **Step 4: 提交 + 推送**

```bash
git add news-monitor/scripts/migrate_event_escalation.py HISTORY.md
git commit -m "feat: event-escalation migration/rollback script + HISTORY sync"
git push origin v1-stable
```

- [ ] **Step 5: 部署 ECS（人工确认后）**

```bash
# 迁移在容器内先跑（app 启动也会自动 migrate，此为显式保险）
ssh root@47.76.50.77 "docker exec news-monitor python scripts/migrate_event_escalation.py"
# 部署新镜像
bash news-monitor/scripts/deploy_ecs.sh
# 观察：sweep 日志 + IOPS
ssh root@47.76.50.77 "docker logs --since 10m news-monitor 2>&1 | grep -iE 'Event #|ALERTED|CONFIRMED|CLOSED'"
```

- [ ] **Step 6: 验证生效后 cherry-pick 回 main**

在主窗口 `D:\class1`：`git cherry-pick <本分支相关 commit 范围>`

---

## Self-Review（对照 spec）

- **Spec §1.3 聚类死代码** → Task 5 修复并激活 ✅
- **Spec §6 数据模型** → Task 2 五字段 + 迁移 ✅
- **Spec §7 状态机/阈值** → Task 6(ALERT)/7(CONFIRMED)/8(CLOSE+冷却+幂等) ✅
- **Spec §8 市场确认（时间对齐+方向闸）** → Task 7 `_market_confirmed` ✅
- **Spec §9 错误处理** → Task 4(取价)/8(sweep 隔离)/9(接线 try/except) ✅
- **Spec §10 测试** → Task 6-8 单测 + Task 10 e2e（恰好 3 推送）✅
- **Spec §11 配置** → Task 1 ✅
- **Spec §12 部署（V1 铁律）** → Task 11 ✅
- **类型一致性**：`dispatch_event(event, level, telegram_push_fn=)` 在 Task 3 定义、Task 6/7/8 一致调用；`MarketSnapshot.since` 返回 `{spx_pct,vix_pct,brent_pct}` 在 Task 4 定义、Task 7 一致消费；`get_peak_impact_for_news_ids -> (peak,cat,sent)` Task 2 定义、Task 6 一致消费 ✅
- **占位符扫描**：无 TBD/TODO；每步含实际代码与命令 ✅
