# Market Impact Evaluator — 设计文档

> **版本**: v1.0 | **日期**: 2026-07-03 | **状态**: 设计已确认，待实施计划

---

## 一、背景与目标

### 问题

PriorityScorer（9因子规则引擎）对宏观事件的评估平均偏差 0.37，N7 关税（0.21→NORMAL）、N3 CPI 超预期（0.29→NORMAL）等重大事件被漏判。

### 目标

基于 LLM 五步推理链的市场影响评估器，偏差从 0.37 降到 <0.15，同时支持推理可解释性和自校准。

---

## 二、架构：异步管线式（方案 C）

```
News → Dedup → PriorityScorer → [score ≥ 0.50] → ImpactEvaluator (async, isolated)
                                                         │
                                              ┌──────────┼──────────┐
                                              │          │          │
                                         Data Quality  LLM Eval  Explainability
                                            Gate        Gate        Gate
                                              │          │          │
                                              └──────────┼──────────┘
                                                         │
                                              ┌──────────┼──────────┐
                                              │          │          │
                                          DB Write   Collector   Learner
                                                       │
                                                 15m/1h/4h 分层
```

### 隔离保证

- 不连接 AlertDispatcher
- 不写入 `news.priority_score`
- 独立表 (`impact_assessments` / `impact_outcomes` / `calibration_state` / `health_events`)
- 独立 API (`/api/impact/*`)
- 独立 Dashboard (`/impact`)

---

## 三、核心模块

### 3.1 Data Quality Gate (`engine/impact_evaluator.py` 内)

```python
def _validate_input(item: NewsItem) -> tuple[bool, str]:
    """Return (pass, reason)."""
    if not item.title or len(item.title.strip()) < 5:
        return False, "title_too_short"
    if not item.content_snippet or len(item.content_snippet) < 50:
        return False, "content_too_short"
    # Encoding sanity check
    try:
        item.title.encode('utf-8')
    except UnicodeError:
        return False, "encoding_error"
    return True, "ok"
```

不合格 → 记录 `health_events` 表，类型 `quality_reject`，跳过该条。

### 3.2 LLM 五步推理 (`engine/impact_evaluator.py`)

- **Provider**: DeepSeek (主) → Anthropic (备)，静态优先级
- **Timeout**: 30s SDK + 45s asyncio hard timeout
- **Retry**: 1 次重试，仍失败 → 记录 `health_events`，跳过
- **Prompt**: Hedge Fund 分析师角色，5 步推理 + 严格 JSON Schema 输出

```python
class ImpactEvaluator:
    THRESHOLD = 0.50  # PriorityScorer score 下限

    async def evaluate(self, item: NewsItem, market_context: dict) -> ImpactAssessment | None:
        # 1. Data Quality Gate
        # 2. Build prompt with market_context + calibration_hint
        # 3. LLM call with retry
        # 4. Explainability Gate (validate output)
        # 5. Return ImpactAssessment or None (degraded)
```

**LLM 输出 Schema**:
```json
{
  "impact_score": 0-100,
  "confidence": 0-100,
  "event_category": "monetary|geopolitical|macro_data|corporate|regulatory|other",
  "surprise_level": "expected|minor_surprise|major_surprise|shock",
  "breadth": "single_stock|sector|broad_market|cross_asset",
  "reasoning_chain": ["step1", "step2", "step3", "step4", "step5"],
  "similar_historical_events": ["Event (date): description"],
  "expected_sectors_affected": ["Tech", "Financials"],
  "expected_asset_moves": {"equities": "direction", "bonds": "direction", "fx": "direction", "commodities": "direction"},
  "calibration_note": "tendency description"
}
```

### 3.3 Explainability Gate (`engine/impact_evaluator.py` 内)

```python
def _validate_output(assessment: ImpactAssessment) -> tuple[bool, list[str]]:
    issues = []
    # 1. 推理链完整性
    if len(assessment.reasoning_chain) != 5:
        issues.append("reasoning_chain not 5 steps")
    if any(not step for step in assessment.reasoning_chain):
        issues.append("empty reasoning step")
    # 2. 分数-类别一致性
    if assessment.breadth == "cross_asset" and assessment.impact_score < 30:
        issues.append("cross_asset with low score")
    if assessment.event_category == "monetary" and assessment.impact_score < 20:
        issues.append("monetary event scored too low")
    # 3. 置信度标记
    if assessment.confidence < 40:
        assessment.low_confidence = True
    return len(issues) == 0, issues
```

不合格 → `low_confidence = True`，仍存储但 Dashboard 上标记为"低置信度"。

### 3.4 ImpactCollector (`engine/impact_collector.py`)

分层采集，scheduler 三个定时任务：

| 延迟 | 采集内容 | 用途 |
|------|---------|------|
| 15 分钟 | SPX Δ%, VIX Δ% | 即时反应 |
| 1 小时 | + 板块变动 | 市场消化后 |
| 4 小时 | + 跨资产联动 | 完整收盘数据 |

```python
class ImpactCollector:
    async def collect_15m(self, assessment: ImpactAssessment) -> ImpactOutcome: ...
    async def collect_1h(self, assessment: ImpactAssessment) -> ImpactOutcome: ...
    async def collect_4h(self, assessment: ImpactAssessment) -> ImpactOutcome: ...
```

**Actual Score 归一化**:

| 维度 | 公式 | 权重 |
|------|------|------|
| 标普变动 | `min(|SPX_Δ%| / 0.03, 1.0) × 100` | 40% |
| VIX 变动 | `min(|VIX_Δ%| / 0.15, 1.0) × 100` | 25% |
| 板块广度 | `(affected_sectors / 11) × 100` | 20% |
| 跨资产联动 | `(bonds + fx + commodities moved) / 3 × 100` | 15% |

### 3.5 ImpactLearner (`engine/impact_learner.py`)

**校准策略**: 适中 — 累计 5 样本后开始校准，每次 ±5 点。

```python
class ImpactLearner:
    MIN_SAMPLES = 5
    MAX_ADJUST = 5.0

    def analyze_deviation(self, category: str) -> float:
        """按事件类型计算 bias = mean(predicted - actual)."""
        samples = db.get_outcomes_for_category(category, limit=20)
        if len(samples) < self.MIN_SAMPLES:
            return 0.0
        bias = mean(s.predicted.score - s.actual.score for s in samples)
        return clamp(bias, -self.MAX_ADJUST, self.MAX_ADJUST)

    def generate_calibration_hint(self) -> str:
        """生成注入 Prompt 的校准文本."""
        hints = []
        for cat in ['monetary', 'geopolitical', 'macro_data', 'corporate', 'regulatory']:
            bias = self.analyze_deviation(cat)
            if abs(bias) >= 2.0:
                direction = "over-estimate" if bias > 0 else "under-estimate"
                hints.append(f"Tend to {direction} {cat} events by ~{abs(bias):.0f} points")
        return "; ".join(hints) if hints else "No calibration data yet"
```

### 3.6 Prompt Version Manager (`engine/impact_evaluator.py` 内)

```python
class PromptVersionManager:
    VERSIONS = {
        "v1": "prompts/impact_v1.txt",  # 原始 Hedge Fund 分析师
        "v2": "prompts/impact_v2.txt",  # 备选版本 (待创建)
    }
    ACTIVE = "v1"

    @classmethod
    def load(cls, version: str = None) -> str: ...

    @classmethod
    def compare_mae(cls) -> dict:
        """A/B 对比两个版本的 MAE."""
        # 查询按 version 分组的 outcome 偏差
        ...
```

手动 A/B 测试 → MAE 对比 → 手动切换。不做自动切换。

### 3.7 Health Monitor (`engine/impact_evaluator.py` 内)

```python
class HealthMonitor:
    ERROR_THRESHOLD = 5  # 连续失败次数触发告警

    def record_success(self, latency_ms: float): ...
    def record_failure(self, reason: str): ...
    def record_degradation(self, gate: str, reason: str): ...

    @property
    def health(self) -> dict:
        return {
            "success_rate_1h": ...,
            "avg_latency_ms": ...,
            "consecutive_failures": ...,
            "last_error": ...,
            "status": "healthy" | "degraded" | "down",
        }
```

`/api/impact/health` 端点返回此数据。连续失败 5 次 → Telegram 通知（不震动，非紧急通道）。

---

## 四、数据模型

### 4.1 新表

```sql
-- 评估记录
CREATE TABLE impact_assessments (
    id INTEGER PRIMARY KEY,
    news_id INTEGER,
    impact_score REAL,
    confidence REAL,
    event_category TEXT,
    surprise_level TEXT,
    breadth TEXT,
    reasoning_chain TEXT,      -- JSON
    similar_events TEXT,       -- JSON
    expected_moves TEXT,       -- JSON
    calibration_note TEXT,
    low_confidence INTEGER DEFAULT 0,
    prompt_version TEXT DEFAULT 'v1',
    latency_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 事后实际数据 (每条评估最多 3 条 outcome: 15m/1h/4h)
CREATE TABLE impact_outcomes (
    id INTEGER PRIMARY KEY,
    assessment_id INTEGER,
    collection_window TEXT,     -- '15m' | '1h' | '4h'
    spx_change_pct REAL,
    vix_change_pct REAL,
    sector_changes TEXT,       -- JSON
    actual_score REAL,
    collected_at TIMESTAMP
);

-- 校准状态
CREATE TABLE calibration_state (
    id INTEGER PRIMARY KEY,
    category TEXT UNIQUE,
    bias REAL,
    sample_count INTEGER,
    last_updated TIMESTAMP
);

-- 健康事件 (Data Quality 失败 / LLM 降级 / 错误)
CREATE TABLE health_events (
    id INTEGER PRIMARY KEY,
    event_type TEXT,           -- 'quality_reject' | 'llm_timeout' | 'llm_parse_error' | 'degraded'
    news_id INTEGER,
    detail TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.2 不变更现有表

不修改 `news` / `event_lines` / `feedback` / `preferences` / `training_docs` 任何字段。

---

## 五、API

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/impact/latest?limit=20` | GET | 最近评估列表 |
| `/api/impact/<id>` | GET | 单条评估详情（含推理链） |
| `/api/impact/<id>/outcomes` | GET | 该评估的实际结果 |
| `/api/impact/calibration` | GET | 当前校准状态 |
| `/api/impact/stats` | GET | 汇总: MAE/样本数/最佳最差 |
| `/api/impact/health` | GET | 健康检查: 成功率/延迟/错误 |
| `/api/impact/prompts` | GET | 当前 Prompt 版本 + MAE 对比 |

---

## 六、Telegram 推送

| 规则 | 配置 |
|------|------|
| 触发 | `impact_score ≥ 50` |
| 通道 | 独立，不震动 |
| 频率 | 每 30 分钟最多 1 条 |
| 控制 | `/impact_on` `/impact_off` |
| 格式 | Markdown 卡片 |

格式示例:
```
📊 Market Impact: 78/100  🟠 Major
美国对进口汽车加征25%关税

📈 预期: 汽车重挫 | 避险涌入 | VIX飙升
🧠 推理: 贸易战升级→供应链冲击→风险偏好骤降→跨资产联动
📅 类似: 2018-03-01 钢铝关税: -2.3%

⚠️ 非手机告警  /impact_off 关闭
```

---

## 七、Dashboard

两个面板:

**评估面板**: 最新评估列表 / 推理链展开 / 预测 vs 实际散点图 / 校准曲线 / 偏差仪表 / 低置信度标记

**运维面板** (`/impact`): 成功率趋势 / 平均延迟 / 降级事件列表 / 连续错误告警状态 / Prompt 版本对比

---

## 八、需求确认清单

| # | 需求 | 决策 |
|---|------|------|
| 1 | 评估范围 | 每条新闻（score ≥ 0.50 预过滤） |
| 2 | 预过滤门槛 | PriorityScorer ≥ 0.50 |
| 3 | 采集窗口 | 分层: 15m / 1h / 4h |
| 4 | 校准策略 | 适中: 5 样本 / ±5 点 |
| 5 | 容错 | 重试 1 次后跳过 |
| 6 | Data Quality Gate | ✅ |
| 7 | Explainability Gate | ✅ |
| 8 | Health Monitor | ✅ |
| 9 | PolicyAgent (RL) | ❌ → 规则校准替代 |
| 10 | Auto-evolution | ❌ → Prompt 版本管理替代 |

---

## 九、实施估算

| # | 模块 | 文件 | 预估 |
|---|------|------|------|
| 1 | 数据模型 | `storage/models.py` + `storage/database.py` | 45min |
| 2 | LLM 评估器 | `engine/impact_evaluator.py` | 1.5h |
| 3 | 实际影响采集 | `engine/impact_collector.py` | 1h |
| 4 | 自学习引擎 | `engine/impact_learner.py` | 1.5h |
| 5 | Web API | `web/routes.py` | 45min |
| 6 | Dashboard | `web/static/impact.html` | 1.5h |
| 7 | 集成测试 | `tests/test_impact_evaluator.py` | 30min |
| **总计** | | | **~7.5h** |
