# V2 事件升级功能移植 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 v1-stable 上已验证的"连续事件升级推送"功能移植进 V2(main)，适配 V2 的流水线架构，不触碰 ECS 生产。

**Architecture:** 事件升级是**事件线级**（对聚合事件推送），与 V2 **逐条新闻**的流水线（INGEST→SCREEN→EVALUATE→DISPATCH→DEEP）正交。因此：聚类挂进 IngestStage 喂 `event_lines`；`EventEscalator` 作为 `main.py` 里一个独立的 5 分钟定时 sweep 循环运行，复用现有 `AlertDispatcher` 推送（Option A：给 dispatcher 补 `dispatch_event`，不强塞进流水线）。

**Tech Stack:** Python 3.12, SQLite, pytest, asyncio, yfinance（MarketSnapshot）。

## Global Constraints

- 全程只在 `main` 分支操作，**不部署、不碰 ECS、不 cherry-pick 孤儿代码**。
- **移植来源唯一真相 = `v1-stable` 分支**（worktree: `D:/class1/.claude/worktrees/v1-stable/`）。纯搬运文件用 `git show v1-stable:<path>` 取，逐字节一致。
- 提交格式：`[Phase] 描述`；测试跑不过不得进入下一 Task。
- 每个 Task 结束跑对应测试；全部 Task 结束跑 V2 全量（基线：360 passed，含 vector_store 的 `close()` 修复）。
- Windows 环境：DB 测试用 `tmp_path`，连接及时关闭（避免文件锁）。

---

### Task 1: DB schema 地基（impact_assessments 缺列 + event_lines 升级列 + 4 个查询方法）

这是**最高风险项**：escalator 的 `get_peak_impact_for_news_ids` 读 `impact_assessments.sentiment`，而 V2 建表/INSERT 都没有该列 — 不补会直接抛异常。V2 的 `models.py` 已声明这些字段，缺的只是 DB 层持久化。

**Files:**
- Modify: `news-monitor/storage/database.py`（`init_db` 的两处 CREATE TABLE + `_migrations` 列表 + 新增 5 个方法；`insert_assessment` 的 INSERT 扩展）
- Modify: `news-monitor/storage/models.py`（`EventLine` +5 字段）
- Test: `news-monitor/tests/test_event_escalation_db.py`（从 v1-stable 移植）

**Interfaces:**
- Produces:
  - `Database.migrate_event_escalation() -> None`
  - `Database.get_active_event_lines(active_window_hours:int=12) -> list[dict]`
  - `Database.update_event_escalation(event_id:int, **fields) -> None`
  - `Database.get_event_members(event_id:int) -> list[dict]`
  - `Database.get_peak_impact_for_news_ids(news_ids:list[int]) -> tuple[float,str,str]`（返回 `(peak_impact, category, sentiment)`）
  - `EventLine` 新字段：`escalation_state:str="NONE"`, `peak_impact:float=0.0`, `dominant_category:str=""`, `dominant_sentiment:str=""`, `alerted_at:Optional[datetime]=None`

- [ ] **Step 1: 移植 DB 测试（先失败）**

```bash
cd D:/class1
git show v1-stable:news-monitor/tests/test_event_escalation_db.py > news-monitor/tests/test_event_escalation_db.py
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_event_escalation_db.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'migrate_event_escalation'`（或 `no such column: sentiment`）

- [ ] **Step 3: `models.py` — EventLine 追加 5 字段**

在 `EventLine` dataclass（约 line 55）末尾追加（保持与其它字段同缩进）：

```python
    escalation_state: str = "NONE"   # NONE|ALERTED|CONFIRMED|CLOSED
    peak_impact: float = 0.0
    dominant_category: str = ""
    dominant_sentiment: str = ""
    alerted_at: Optional[datetime] = None
```

（`Optional`/`datetime` 已在文件顶部 import；若无则补 `from typing import Optional` / `from datetime import datetime`。）

- [ ] **Step 4: `database.py` — `event_lines` 建表加升级列**

在 `init_db` 里 `event_lines` 的 `CREATE TABLE` 中，把 `is_active INTEGER DEFAULT 1` 改成带逗号并追加 5 列：

```sql
                    is_active INTEGER DEFAULT 1,
                    escalation_state TEXT DEFAULT 'NONE',
                    peak_impact REAL DEFAULT 0.0,
                    dominant_category TEXT DEFAULT '',
                    dominant_sentiment TEXT DEFAULT '',
                    alerted_at TEXT
```

- [ ] **Step 5: `database.py` — `impact_assessments` 建表加 6 列**

在 `impact_assessments` 的 `CREATE TABLE` 中，`breadth` 之后补入（放在 `reasoning_chain` 前，与 v1-stable 一致）：

```sql
                    urgency TEXT DEFAULT 'INFO',
                    sentiment TEXT DEFAULT '',
                    greed_index INTEGER DEFAULT 50,
                    flash_note TEXT DEFAULT '',
                    key_points TEXT DEFAULT '',
                    risk_flags TEXT DEFAULT '',
```

- [ ] **Step 6: `database.py` — 迁移列表（幂等 ALTER）替换旧单条**

把原来只 ALTER `analyst_note` 的 try/except 块替换为列表循环：

```python
            # Migrations: add new columns to existing databases (idempotent)
            _migrations = [
                "ALTER TABLE impact_assessments ADD COLUMN analyst_note TEXT DEFAULT ''",
                "ALTER TABLE impact_assessments ADD COLUMN urgency TEXT DEFAULT 'INFO'",
                "ALTER TABLE impact_assessments ADD COLUMN sentiment TEXT DEFAULT ''",
                "ALTER TABLE impact_assessments ADD COLUMN greed_index INTEGER DEFAULT 50",
                "ALTER TABLE impact_assessments ADD COLUMN flash_note TEXT DEFAULT ''",
                "ALTER TABLE impact_assessments ADD COLUMN key_points TEXT DEFAULT ''",
                "ALTER TABLE impact_assessments ADD COLUMN risk_flags TEXT DEFAULT ''",
            ]
            for stmt in _migrations:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass  # column already exists
```

- [ ] **Step 7: `database.py` — 新增 escalation 方法**

在 `insert_news` 方法之前插入（逐字节取自 v1-stable，避免手抄错）：

```bash
cd D:/class1
git show v1-stable:news-monitor/storage/database.py | sed -n '/def migrate_event_escalation/,/return (float(row\["impact_score"\]/p'
```

把上面输出的 5 个方法（`migrate_event_escalation` / `get_active_event_lines` / `update_event_escalation` / `get_event_members` / `get_peak_impact_for_news_ids`）粘入 `Database` 类。核对方法体与本计划顶部 Interfaces 段签名一致。

- [ ] **Step 8: `database.py` — `insert_assessment` 的 INSERT 扩展**

把 `insert_assessment` 里 `INSERT INTO impact_assessments (...)` 的列清单与 `VALUES` 占位符、以及传参元组，按 v1-stable 扩展为含 `urgency, sentiment, greed_index, flash_note, key_points, risk_flags`（共 20 个占位符）。取参考：

```bash
git show v1-stable:news-monitor/storage/database.py | sed -n '/INSERT INTO impact_assessments/,/latency_ms)/p'
```

- [ ] **Step 9: 跑测试确认通过**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_event_escalation_db.py -v`
Expected: PASS（4 passed）

- [ ] **Step 10: 回归 — 确认没打断现有 DB / impact 测试**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_database.py tests/test_impact_evaluator.py tests/test_impact_push.py -q`
Expected: 全 PASS

- [ ] **Step 11: Commit**

```bash
cd D:/class1
git add news-monitor/storage/database.py news-monitor/storage/models.py news-monitor/tests/test_event_escalation_db.py
git commit -m "[V2-escalation] DB schema: impact_assessments 缺列 + event_lines 升级列 + 查询方法"
```

---

### Task 2: 配置层（event-escalation.json + loader.load_event_escalation）

**Files:**
- Create: `news-monitor/config/event-escalation.json`
- Modify: `news-monitor/config/loader.py`（新增 `load_event_escalation`）
- Test: `news-monitor/tests/test_event_escalation_config.py`（移植）

**Interfaces:**
- Produces: `ConfigLoader.load_event_escalation() -> dict`（含 `alert_trigger / market_confirm / close / cooldown_hours / max_pushes_per_event / sweep_interval_minutes`，带缓存）

- [ ] **Step 1: 移植配置文件 + 测试**

```bash
cd D:/class1
git show v1-stable:news-monitor/config/event-escalation.json > news-monitor/config/event-escalation.json
git show v1-stable:news-monitor/tests/test_event_escalation_config.py > news-monitor/tests/test_event_escalation_config.py
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_event_escalation_config.py -v`
Expected: FAIL — `AttributeError: 'ConfigLoader' object has no attribute 'load_event_escalation'`

- [ ] **Step 3: `loader.py` — 移入 load_event_escalation 方法**

```bash
git show v1-stable:news-monitor/config/loader.py | sed -n '/def load_event_escalation/,/return .*_event_escalation/p'
```

把该方法粘入 `ConfigLoader` 类（缓存属性名与 v1-stable 一致，如 `self._event_escalation`）。核对它读的是 `config/event-escalation.json`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_event_escalation_config.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: Commit**

```bash
cd D:/class1
git add news-monitor/config/event-escalation.json news-monitor/config/loader.py news-monitor/tests/test_event_escalation_config.py
git commit -m "[V2-escalation] 配置: event-escalation.json + ConfigLoader.load_event_escalation"
```

---

### Task 3: 推送出口（AlertDispatcher.dispatch_event + _format_event_body）

Option A：给 V2 的 dispatcher 补事件级推送方法。V2 已有 `_pushover_emergency/_pushover_high/_telegram_triple/pushover_available`；**只缺 `_format_event_body`**，需一并移入。

**Files:**
- Modify: `news-monitor/engine/alert_dispatcher.py`（新增 `dispatch_event` + `_format_event_body`）
- Test: `news-monitor/tests/test_dispatch_event.py`（移植）

**Interfaces:**
- Consumes: `AlertLevel`（V2 `engine/alert_dispatcher.py` 已有）、`DispatchResult`（同文件）、`_pushover_emergency/_pushover_high/_telegram_triple/pushover_available`（V2 已有）
- Produces: `async AlertDispatcher.dispatch_event(event:dict, level, telegram_push_fn=None) -> DispatchResult`；`AlertDispatcher._format_event_body(event:dict) -> str`

- [ ] **Step 1: 移植测试**

```bash
cd D:/class1
git show v1-stable:news-monitor/tests/test_dispatch_event.py > news-monitor/tests/test_dispatch_event.py
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_dispatch_event.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'dispatch_event'`

- [ ] **Step 3: 移入 `_format_event_body`**

```bash
git show v1-stable:news-monitor/engine/alert_dispatcher.py | sed -n '/def _format_event_body/,/^    def /p'
```

把 `_format_event_body`（不含下一个 `def` 起始行）粘入 `AlertDispatcher` 类。

- [ ] **Step 4: 移入 `dispatch_event`**

粘入以下方法（逐字节取自 v1-stable，已核对依赖在 V2 均存在）：

```python
    async def dispatch_event(self, event: dict, level, telegram_push_fn=None):
        from engine.alert_dispatcher import AlertLevel, DispatchResult  # local to avoid cycle
        channels: list[str] = []
        body = self._format_event_body(event)
        item = {
            "title": event.get("title", ""),
            "source": f"事件聚合({event.get('source_count', 0)}源)",
            "url": event.get("url", ""),
            "_event_body": body,
            "_flash_note": body,      # telegram: format_fast_alert renders _flash_note
            "_analyst_note": body,    # pushover: _pushover renders _analyst_note
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

- [ ] **Step 5: 跑测试确认通过**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_dispatch_event.py tests/test_alert_dispatcher.py -v`
Expected: 全 PASS（test_dispatch_event 3 passed + 现有 dispatcher 测试不回归）

- [ ] **Step 6: Commit**

```bash
cd D:/class1
git add news-monitor/engine/alert_dispatcher.py news-monitor/tests/test_dispatch_event.py
git commit -m "[V2-escalation] AlertDispatcher.dispatch_event 事件级推送 (Option A)"
```

---

### Task 4: 聚类种子逻辑（cluster.py singleton-seeding）

V2 的 `find_or_create_event` 无匹配时返回 `None`，事件永远攒不到 2 源，escalator 的 `min_source_count=3` 门槛就无从触发。补 v1-stable 的"从既有单例种出事件"逻辑。

**Files:**
- Modify: `news-monitor/engine/cluster.py`（改"No match"分支 + 新增 `_find_similar_singleton`）
- Test: `news-monitor/tests/test_cluster.py`（若 v1-stable 版含种子用例则移植/合并）

**Interfaces:**
- Consumes: `NewsCluster._create_event`, `_add_to_event`, `SIMILARITY_THRESHOLD`, `DedupManager.title_similarity`（V2 均已有）
- Produces: `NewsCluster._find_similar_singleton(item:NewsItem, recent:list[dict]) -> Optional[dict]`；`find_or_create_event` 可返回种出的 `event_id`

- [ ] **Step 1: 同步 v1-stable 的 cluster 测试（若有新增用例）**

```bash
cd D:/class1
git diff main v1-stable -- news-monitor/tests/test_cluster.py
```
若有差异（新增单例种子用例），把 v1-stable 版覆盖过来：
```bash
git show v1-stable:news-monitor/tests/test_cluster.py > news-monitor/tests/test_cluster.py
```
若无差异，跳过本步。

- [ ] **Step 2: 跑测试看当前状态**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_cluster.py -v`
Expected: 种子用例 FAIL（若已移植）；否则先记录基线全绿

- [ ] **Step 3: 替换 `find_or_create_event` 的"No match"分支**

把 `cluster.py` 里：

```python
        # No match — create a new event line if there are similar items
        # (singletons don't get event lines until a second source confirms)
        return None
```

替换为：

```python
        # No existing event line — check for a similar *singleton* to seed a new event.
        seed = self._find_similar_singleton(item, recent)
        if seed:
            # Seed the event from the pre-existing singleton, then add the new item,
            # so BOTH articles are attached (news_ids has both, source_count = 2).
            seed_item = NewsItem(
                id=seed["id"],
                title=seed.get("title", ""),
                status=seed.get("status", "pending"),
            )
            event_id = self._create_event(seed_item)   # news_ids=seed, count=1
            self.db.update_news_status(seed["id"], seed.get("status", "pending"), event_line_id=event_id)
            self._add_to_event(item, event_id)          # adds new item, count=2
            return event_id
        return None
```

- [ ] **Step 4: 新增 `_find_similar_singleton` 方法**

在 `_add_to_event` 方法之前插入：

```python
    def _find_similar_singleton(self, item: NewsItem, recent: List[dict]) -> Optional[dict]:
        """Find a recent article with no event_line_id that is similar enough.

        Returns the matching singleton row (dict), or None.
        """
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

（确认 `List` / `Optional` 已 import；`DedupManager` 已 import。）

- [ ] **Step 5: 跑测试确认通过**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_cluster.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
cd D:/class1
git add news-monitor/engine/cluster.py news-monitor/tests/test_cluster.py
git commit -m "[V2-escalation] cluster: 单例种子逻辑，事件可攒到 2 源"
```

---

### Task 5: 事件升级引擎 + 市场快照（纯搬运）

**Files:**
- Create: `news-monitor/engine/market_snapshot.py`
- Create: `news-monitor/engine/event_escalator.py`
- Test: `news-monitor/tests/test_event_escalator.py`（移植）

**Interfaces:**
- Consumes: Task 1 的 DB 方法、Task 2 的 `load_event_escalation`、Task 3 的 `dispatch_event`、`MarketSnapshot.since`
- Produces: `EventEscalator(db, dispatcher, market, config_loader, telegram_push_provider=None)`；`async EventEscalator.sweep()`；`async EventEscalator.evaluate(event)`；`MarketSnapshot.since(start) -> dict`

- [ ] **Step 1: 搬运引擎 + 市场快照 + 测试**

```bash
cd D:/class1
git show v1-stable:news-monitor/engine/market_snapshot.py > news-monitor/engine/market_snapshot.py
git show v1-stable:news-monitor/engine/event_escalator.py > news-monitor/engine/event_escalator.py
git show v1-stable:news-monitor/tests/test_event_escalator.py > news-monitor/tests/test_event_escalator.py
```

- [ ] **Step 2: 跑引擎单测确认通过（全 mock，不依赖接线）**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_event_escalator.py -v`
Expected: PASS（6 passed）。若报 `ImportError: AlertLevel`，核对 `event_escalator.py` 顶部 `from engine.alert_dispatcher import AlertLevel` 在 V2 可解析。

- [ ] **Step 3: Commit**

```bash
cd D:/class1
git add news-monitor/engine/market_snapshot.py news-monitor/engine/event_escalator.py news-monitor/tests/test_event_escalator.py
git commit -m "[V2-escalation] 移入 EventEscalator + MarketSnapshot (纯搬运)"
```

---

### Task 6: 接线（IngestStage 聚类 + main.py 实例化 + sweep 循环 + 迁移脚本）

**Files:**
- Modify: `news-monitor/pipeline/ingest.py`（IngestStage 接收 cluster，insert 后调 `find_or_create_event`）
- Modify: `news-monitor/main.py`（migrate 调用、实例化 MarketSnapshot/EventEscalator/NewsCluster、把 cluster 传进 IngestStage、启动 sweep 循环）
- Create: `news-monitor/scripts/migrate_event_escalation.py`（迁移 CLI）
- Test: `news-monitor/tests/test_event_escalation_e2e.py`（移植）

**Interfaces:**
- Consumes: 前述所有；`IngestStage.__init__(db, dedup, vector_store=None, cluster=None)`
- Produces: 运行时 `NewsMonitor._escalator_task`（后台 sweep 循环）

- [ ] **Step 1: 移植端到端测试 + 迁移脚本**

```bash
cd D:/class1
git show v1-stable:news-monitor/tests/test_event_escalation_e2e.py > news-monitor/tests/test_event_escalation_e2e.py
git show v1-stable:news-monitor/scripts/migrate_event_escalation.py > news-monitor/scripts/migrate_event_escalation.py
```

- [ ] **Step 2: 跑 e2e 确认失败**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_event_escalation_e2e.py -v`
Expected: PASS 或 FAIL 取决于其是否只依赖 DB+mock。若 FAIL 记录原因用于 Step 6 复查（该测试 mock dispatcher/market，只需 Task 1 的 DB 方法即可，多半此时已能过）。

- [ ] **Step 3: `ingest.py` — IngestStage 接收并调用 cluster**

`__init__` 签名加 `cluster=None`：

```python
    def __init__(
        self,
        db: Database,
        dedup: DedupManager,
        vector_store: VectorStore | None = None,
        cluster=None,
    ) -> None:
        self._db = db
        self._dedup = dedup
        self._vector = vector_store
        self._cluster = cluster
```

在 `process` 的 Step 2 循环里，`results.append(item)` 之后、`except` 之前插入聚类调用（`news.id` 用刚得到的 `news_id`）：

```python
                if self._cluster is not None:
                    try:
                        news.id = news_id
                        self._cluster.find_or_create_event(news)
                    except Exception:
                        logger.debug("INGEST: clustering failed for id=%d", news_id)
```

- [ ] **Step 4: `main.py` — 迁移 + 实例化 + 传 cluster 进 IngestStage**

在 `__init__` 的 `self.db.init_db()`（line 107）之后追加：

```python
        self.db.migrate_event_escalation()
```

在 `# ---- alert dispatcher` 块之后、构建 Pipeline 之前，新增实例化：

```python
        # ---- event clustering + escalation --------------------------
        from engine.cluster import NewsCluster
        from engine.market_snapshot import MarketSnapshot
        from engine.event_escalator import EventEscalator
        self.cluster = NewsCluster(self.db, vector_store=self.vector_store)
        self.market_snapshot = MarketSnapshot()
        self.escalator = EventEscalator(
            self.db, self.alert_dispatcher, self.market_snapshot, self.config,
            telegram_push_provider=(lambda: self.alert_dispatcher.wrap_telegram_push(self.bot)) if self.bot else None,
        )
```

把 `IngestStage(...)`（line 192）改为传入 cluster：

```python
            IngestStage(db=self.db, dedup=self.dedup, vector_store=self.vector_store, cluster=self.cluster),
```

- [ ] **Step 5: `main.py` — sweep 后台循环**

在 `_run_collector_loop` 之后新增方法：

```python
    async def _run_escalation_loop(self):
        """Periodic event-line escalation sweep (interval from config)."""
        cfg = self.config.load_event_escalation()
        interval = int(cfg.get("sweep_interval_minutes", 5)) * 60
        while True:
            await asyncio.sleep(interval)
            try:
                await self.escalator.sweep()
            except Exception:
                logger.exception("EscalationLoop: sweep failed")
```

在 `start()` 的 `self._collector_task = ...`（line 321）之后追加：

```python
        self._escalator_task = asyncio.create_task(self._run_escalation_loop())
```

在 `stop()` 里 `_collector_task.cancel()` 附近追加对称清理：

```python
        if hasattr(self, '_escalator_task'):
            self._escalator_task.cancel()
```

- [ ] **Step 6: 跑 e2e + 相关全测**

Run: `cd D:/class1/news-monitor && python -m pytest tests/test_event_escalation_e2e.py tests/test_event_escalator.py tests/test_event_escalation_db.py tests/test_event_escalation_config.py tests/test_dispatch_event.py tests/test_cluster.py -v`
Expected: 全 PASS（17+ 项）

- [ ] **Step 7: 冒烟 — import main 不炸**

Run: `cd D:/class1/news-monitor && python -c "import main; print('import OK')"`
Expected: `import OK`（无异常）

- [ ] **Step 8: Commit**

```bash
cd D:/class1
git add news-monitor/pipeline/ingest.py news-monitor/main.py news-monitor/scripts/migrate_event_escalation.py news-monitor/tests/test_event_escalation_e2e.py
git commit -m "[V2-escalation] 接线: IngestStage 聚类 + main.py 实例化/sweep 循环 + 迁移脚本"
```

---

### Task 7: V2 全量回归 + 本地影子验证

**Files:**
- Modify: `config/module_registry.json`（注册新模块 event_escalator/market_snapshot 的 tests）
- Modify: `HISTORY.md`, `.claude/SESSION.md`

- [ ] **Step 1: V2 全量测试**

Run: `cd D:/class1/news-monitor && python -m pytest tests/ -q`
Expected: 全 PASS（基线 360 + 新增 ~17，vector_store 的 6 项已由 V2 的 `close()` 修复，不应再报 error）

- [ ] **Step 2: 注册新模块到耦合表**

编辑 `config/module_registry.json`，为 `engine/event_escalator.py`、`engine/market_snapshot.py` 增加条目（`tests` 指向对应测试文件），避免 `session_startup.py` 警告未注册。

- [ ] **Step 3: 本地影子跑（隔离，不推真实通知）**

Run: `cd D:/class1/news-monitor && python scripts/run_v2_local.py`
Expected: 启动无异常，日志出现 `migrate_event_escalation` 与 escalation sweep 循环启动；测试库 `data/v2_test.db` 生成 `event_lines` 升级列；推送通道全禁用（Telegram/Pushover token 空）。观察数分钟无栈崩。

- [ ] **Step 4: 更新历史与会话状态**

追加 `HISTORY.md` 一条移植记录（引用各 Task 的 commit hash）；更新 `.claude/SESSION.md`「本次完成 / 下一步（灰度上 ECS）」。

- [ ] **Step 5: Commit + push**

```bash
cd D:/class1
git add config/module_registry.json HISTORY.md .claude/SESSION.md
git commit -m "[V2-escalation] 注册模块 + 全量回归绿 + 影子验证 + 历史同步 [skip-tests]"
git push origin main
```

---

## Self-Review

**Spec coverage（对照 Explore 分析的 bring-over/adaptation 清单）：**
- ✅ config/event-escalation.json → Task 2
- ✅ engine/event_escalator.py → Task 5
- ✅ engine/market_snapshot.py（隐藏依赖）→ Task 5
- ✅ scripts/migrate_event_escalation.py → Task 6
- ✅ storage/models.py EventLine +5 → Task 1
- ✅ config/loader.py load_event_escalation（隐藏依赖）→ Task 2
- ✅ storage/database.py escalation 方法 + event_lines 列（隐藏依赖）→ Task 1
- ✅ 🔴 impact_assessments sentiment 缺列（最高风险）→ Task 1 Step 5/6/8
- ✅ AlertDispatcher.dispatch_event（+ _format_event_body 隐藏依赖）→ Task 3
- ✅ cluster.py 单例种子 → Task 4
- ✅ sweep 调度（独立循环，非流水线阶段）→ Task 6 Step 5
- ✅ main.py 接线 → Task 6；**丢弃** v1 的 scheduler 注入 + push-formatter/low-impact hunk（V2 已由 EvaluateStage/DispatchDecision 覆盖）
- ✅ 全部 4 个 escalation 测试 + test_dispatch_event + test_cluster → 各 Task

**Placeholder scan:** 纯搬运步骤给了精确 `git show v1-stable:<path>` 取值命令；适配步骤内联了完整代码。无 TBD/TODO。

**Type consistency:** `dispatch_event(event, level, telegram_push_fn=None)`、`get_peak_impact_for_news_ids -> (float,str,str)`、`IngestStage.__init__(..., cluster=None)`、`EventEscalator(db, dispatcher, market, config_loader, telegram_push_provider=None)` 在定义处与调用处一致。

**已知风险：** e2e 测试注释提到本地时间 ISO vs `datetime('now')` UTC 偏差——若 Task 6 Step 6 该测试因时区 flaky，保持 v1-stable 的时间约定不改（属测试环境问题，非功能缺陷）。
