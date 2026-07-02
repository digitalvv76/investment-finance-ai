# Market Impact Evaluator — 开发规格文档

> **状态**: 待审核 | **创建**: 2026-07-02 | **版本**: v1.0
> **目标**: 构建基于 LLM 的市场影响评估系统，独立于现有手机告警体系，具备自学习能力

---

## 一、目标与范围

### 1.1 要解决的问题
现有 PriorityScorer（9因子规则匹配）对宏观数据/政策事件评分偏低：
- CPI 超预期 → 评分 0.29（应为 ~0.85）
- 关税升级 → 评分 0.21（应为 ~0.90）
- Fed 降息 → 评分 0.36（应为 ~0.82）

根因：规则系统无法从纯文本中理解事件上下文和预期差幅度。

### 1.2 设计目标
| 指标 | 当前 | 目标 |
|------|------|------|
| 与基准平均偏差 | 0.37 | <0.15 |
| N7 关税识别 | 0.21 (NORMAL) | >75 (正确识别为极端) |
| N3 CPI 识别 | 0.29 (NORMAL) | >70 (正确识别为重大) |
| 推理可解释性 | 无 | 5步推理链 |
| 自校准能力 | 无 | 基于历史偏差自动调整 |

### 1.3 不做的事
- ❌ 不修改 AlertDispatcher 或 PriorityScorer
- ❌ 不触发手机震动
- ❌ 不改变现有 Telegram 告警通道
- ✅ Dashboard 展示 + Telegram 独立推送

---

## 二、架构设计

### 2.1 双轨并行

```
现有轨道（冻结）：
  📰新闻 → PriorityScorer → StrategicDetector → AlertDispatcher → 📳手机震动

新轨道（独立）：
  📰新闻 → ImpactEvaluator(LLM) → ImpactAssessment
                                      ├── 📊 Dashboard
                                      ├── 📲 Telegram 独立推送
                                      └── 📥 ImpactLearner → 校准数据
```

### 2.2 数据流

```
[1] 新闻进入 → FastLane 处理
[2] FastLane 推送后 → ImpactEvaluator.evaluate(title, content)
[3] LLM 返回结构化 JSON → 存入 impact_assessments 表
[4] 如果 score >= 50 → Dashboard SSE 推送 + Telegram 发送
[5] 24h 后 → ImpactCollector 采集 SPX/VIX/板块数据
[6] 计算预测偏差 → 存入 impact_outcomes + 更新 calibration_state
[7] 下次 LLM 调用时 → 注入最新校准提示
```

---

## 三、新增文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `engine/impact_evaluator.py` | 新建 | LLM 评估器核心 |
| `engine/impact_collector.py` | 新建 | 事后市场数据采集 |
| `engine/impact_learner.py` | 新建 | 自学习校准引擎 |
| `storage/models.py` | 修改 | 新增 3 张表 |
| `storage/database.py` | 修改 | 新增 CRUD 方法 |
| `web/routes.py` | 修改 | 新增 /api/impact/* 端点 |
| `web/static/impact.html` | 新建 | Dashboard 评估面板 |
| `main.py` | 修改 | 集成 ImpactEvaluator |
| `tests/test_impact_evaluator.py` | 新建 | 测试套件 |

---

## 四、数据模型

### 4.1 impact_assessments（评估记录）

```sql
CREATE TABLE impact_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER,                   -- FK → news_items.id
    impact_score REAL NOT NULL,        -- 0-100 LLM 预测
    confidence REAL NOT NULL,          -- 0-100 置信度
    event_category TEXT NOT NULL,      -- monetary|geopolitical|macro_data|corporate|regulatory|other
    surprise_level TEXT NOT NULL,      -- expected|minor_surprise|major_surprise|shock
    breadth TEXT NOT NULL,             -- single_stock|sector|broad_market|cross_asset
    reasoning_chain TEXT NOT NULL,     -- JSON array of 5 reasoning steps
    similar_events TEXT,               -- JSON array of historical comparisons
    expected_moves TEXT,               -- JSON: {equities, bonds, fx, commodities}
    calibration_note TEXT,             -- 注入的校准提示
    llm_model TEXT,                    -- 使用的模型
    llm_latency_ms INTEGER,           -- LLM 响应时间
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.2 impact_outcomes（实际结果）

```sql
CREATE TABLE impact_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL,    -- FK → impact_assessments.id
    spx_change_pct REAL,               -- 标普500变动%
    vix_change_pct REAL,               -- VIX变动%
    sector_changes TEXT,               -- JSON: {sector: change_pct}
    actual_score REAL NOT NULL,        -- 归一化实际影响 0-100
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assessment_id) REFERENCES impact_assessments(id)
);
```

### 4.3 calibration_state（校准状态）

```sql
CREATE TABLE calibration_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT UNIQUE NOT NULL,     -- event_category 或 'global'
    bias REAL NOT NULL DEFAULT 0,      -- 平均偏差（正=过估）
    mae REAL NOT NULL DEFAULT 0,       -- 平均绝对误差
    sample_count INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 五、模块规格

### 5.1 ImpactEvaluator (`engine/impact_evaluator.py`)

```python
class ImpactEvaluator:
    """LLM-driven market impact evaluator."""

    def __init__(self, db: Database, trainer=None):
        self.db = db
        self.trainer = trainer
        self._client = None  # DeepSeek OpenAI client

    async def evaluate(self, news_item: NewsItem) -> ImpactAssessment:
        """Evaluate a news item's market impact.
        
        Returns ImpactAssessment dataclass with:
            - impact_score: float (0-100)
            - confidence: float (0-100)
            - event_category: str
            - surprise_level: str
            - breadth: str
            - reasoning_chain: list[str] (5 steps)
            - similar_events: list[str]
            - expected_moves: dict
            - calibration_note: str
        """
        
    def _build_prompt(self, title, content, calibration) -> str:
        """Build the LLM evaluation prompt."""
        
    async def _call_llm(self, prompt: str) -> dict:
        """Call DeepSeek with structured output, 30s timeout."""
        
    def _parse_response(self, raw: str) -> ImpactAssessment:
        """Parse LLM JSON response, validate fields."""
```

**Prompt 设计要点**：
- System prompt 设定为"顶级对冲基金宏观分析师"
- 5 步推理链：事件类型 → 惊喜幅度 → 市场广度 → 历史先例 → 当前情绪
- 严格 JSON 输出格式
- 注入 calibration_note（来自 ImpactLearner）

### 5.2 ImpactCollector (`engine/impact_collector.py`)

```python
class ImpactCollector:
    """Collect actual market data after an event for calibration."""

    def __init__(self):
        self._collect_delay_hours = 24  # 等市场反应充分

    async def collect_outcome(self, assessment: ImpactAssessment) -> ImpactOutcome:
        """Collect actual market impact for an assessment.
        
        数据源：stock-scanner MCP (tradingview_quote, tradingview_technicals)
        采集指标：
            - SPX 变动%（相对于评估时间点）
            - VIX 变动%
            - 11个 GICS 板块各自变动%
            - 10Y 收益率变动
            - USD 指数变动
        """
        
    def normalize_to_score(self, market_data: dict) -> float:
        """将市场数据归一化为 0-100 actual_score。
        
        权重：SPX Δ 40% + VIX Δ 25% + 板块广度 20% + 跨资产 15%
        """
```

### 5.3 ImpactLearner (`engine/impact_learner.py`)

```python
class ImpactLearner:
    """Self-learning calibration engine."""

    def __init__(self, db: Database):
        self.db = db
        self._min_samples = 5  # 最少样本数才生成校准提示

    def compute_calibration(self) -> dict:
        """分析所有 (预测, 实际) 对，生成校准参数。
        
        Returns:
            {
                "global_bias": +3.2,     # 全局过估 3.2 分
                "global_mae": 8.7,        # 平均绝对误差
                "per_category": {
                    "monetary": {"bias": -2.1, "mae": 6.3},
                    "macro_data": {"bias": +5.4, "mae": 10.2},
                    ...
                }
            }
        """
        
    def get_calibration_hint(self) -> str:
        """生成注入 LLM Prompt 的校准提示文本。
        
        例: "Based on past 25 assessments, this evaluator tends to 
              OVERestimate macro_data events by 5.4 points and 
              UNDERestimate geopolitical events by 3.1 points."
        """
        
    def update_calibration_state(self):
        """定期更新 calibration_state 表（每次有新的 outcome 后触发）"""
```

---

## 六、API 端点

### 6.1 新增路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/impact/recent` | 最近评估列表 `?limit=20` |
| GET | `/api/impact/{id}` | 单条评估详情（含推理链） |
| GET | `/api/impact/stats` | 汇总统计（准确率/偏差/样本数） |
| GET | `/api/impact/calibration` | 当前校准状态 |
| GET | `/api/impact/trend` | 准确率趋势数据（供图表用） |
| POST | `/api/impact/evaluate/{news_id}` | 手动触发评估 |

### 6.2 响应格式示例

```json
GET /api/impact/recent?limit=5

{
  "assessments": [
    {
      "id": 1,
      "news_id": 42,
      "title": "US announces 25% tariff on imported autos",
      "impact_score": 85,
      "confidence": 78,
      "event_category": "geopolitical",
      "surprise_level": "major_surprise",
      "breadth": "cross_asset",
      "reasoning_chain": [
        "Step 1: Trade war escalation → geopolitical shock category",
        "Step 2: 25% tariff exceeds market expectations of 10-15%",
        "Step 3: Auto sector directly hit, supply chain ripples globally",
        "Step 4: Similar to 2018 steel tariffs which caused SPX -2.3%",
        "Step 5: VIX at 22, fear regime amplifies negative news"
      ],
      "has_outcome": false,
      "created_at": "2026-07-02T21:30:00"
    }
  ],
  "stats": {
    "total_assessments": 42,
    "with_outcomes": 15,
    "avg_gap": 6.3,
    "trend": "improving"
  }
}
```

---

## 七、Telegram 推送设计

### 7.1 推送规则

| 参数 | 值 |
|------|-----|
| 触发条件 | impact_score ≥ 50 |
| 推送频率 | 每 30 分钟最多 1 条 |
| 推送通道 | Bot 主频道，`disable_notification=True`（静默） |
| 格式 | Markdown 卡片 |
| 用户控制 | `/impact_on` `/impact_off` |

### 7.2 推送格式

```
📊 Market Impact: 85/100
🟠 Major — Cross-Asset

美国宣布对进口汽车加征25%关税

📈 预期影响:
• 汽车板块: 重挫
• 避险资产: 资金涌入
• 波动率: VIX 可能飙升

🧠 推理: 贸易战升级→全球供应链冲击→风险偏好骤降

📅 类似: 2018-03 钢铝关税 (SPX -2.3%)

⚠️ 非手机告警 | /impact_off 关闭
```

### 7.3 Bot 命令

| 命令 | 说明 |
|------|------|
| `/impact_on` | 开启影响评估推送 |
| `/impact_off` | 关闭影响评估推送 |
| `/impact_status` | 查看当前推送状态和统计 |
| `/impact_last` | 查看最近一条评估 |

---

## 八、Dashboard 页面 (`web/static/impact.html`)

### 8.1 布局

```
┌────────────────────────────────────────────────┐
│  📊 Market Impact Evaluator                    │
│  评估面板  |  学习统计  |  校准状态             │
├────────────────────────────────────────────────┤
│  ┌──────────────────┐  ┌──────────────────┐    │
│  │ 最新评估列表      │  │ 准确率趋势图      │    │
│  │ (表格,可展开推理) │  │ (预测vs实际散点)  │    │
│  └──────────────────┘  └──────────────────┘    │
│  ┌──────────────────┐  ┌──────────────────┐    │
│  │ 按类型偏差        │  │ 校准提示文本      │    │
│  │ (柱状图)          │  │ (当前注入Prompt)  │    │
│  └──────────────────┘  └──────────────────┘    │
└────────────────────────────────────────────────┘
```

### 8.2 图表
- 预测 vs 实际散点图（理想 45° 线）
- 按事件类型的偏差柱状图
- 滚动 MAE 趋势线

---

## 九、集成到 main.py

```python
# main.py 中 NewsMonitor 类的变更

class NewsMonitor:
    def __init__(self):
        # ... 现有初始化 ...
        
        # 新增：影响评估器
        self.impact_evaluator = ImpactEvaluator(self.db, self.trainer)
        self.impact_collector = ImpactCollector()
        self.impact_learner = ImpactLearner(self.db)
    
    async def on_news_batch(self, items):
        # ... 现有处理 ...
        
        # 新增：对高优先级新闻异步评估
        for item in items:
            if item.priority_score >= 0.3:  # fast_lane 通过的
                asyncio.create_task(self._evaluate_impact(item))
    
    async def _evaluate_impact(self, item):
        assessment = await self.impact_evaluator.evaluate(item)
        self.db.save_impact_assessment(assessment)
        
        # Dashboard SSE 推送
        if self.web_dashboard:
            await self.web_dashboard.broadcast_impact(assessment)
        
        # Telegram 推送（如果 score >= 50 且用户开启）
        if assessment.impact_score >= 50:
            await self._send_impact_telegram(assessment)
```

---

## 十、测试计划

### 10.1 单元测试 (`tests/test_impact_evaluator.py`)

| 测试 | 说明 |
|------|------|
| `test_evaluate_returns_valid_json` | LLM 返回合法 JSON |
| `test_score_range` | impact_score 在 0-100 |
| `test_five_reasoning_steps` | reasoning_chain 含 5 步 |
| `test_timeout_handling` | LLM 超时后优雅降级 |
| `test_calibration_injection` | 校准提示正确注入 prompt |
| `test_16_benchmark_cases` | 16 条案例偏差 < 0.15 |
| `test_normalize_to_score` | 市场数据归一化正确 |

### 10.2 集成测试

| 测试 | 说明 |
|------|------|
| `test_full_pipeline` | 评估 → 存储 → 采集 → 学习 全链路 |
| `test_dashboard_api` | /api/impact/* 端点响应正确 |
| `test_telegram_push` | Telegram 推送格式正确 |
| `test_dual_track_isolation` | 新系统不影响现有告警 |

---

## 十一、实施步骤（9步）

| 步 | 模块 | 预估 | 依赖 |
|----|------|------|------|
| 1 | 数据模型 (models.py + database.py) | 30min | — |
| 2 | ImpactEvaluator 核心 | 1h | 1 |
| 3 | 16条基准验证 | 30min | 2 |
| 4 | ImpactCollector | 1h | — |
| 5 | ImpactLearner | 1h | 1, 4 |
| 6 | Web API (routes.py) | 30min | 1, 2 |
| 7 | Dashboard 页面 (impact.html) | 1h | 6 |
| 8 | Telegram 推送集成 | 30min | 2 |
| 9 | 集成测试 + main.py 挂载 | 30min | 全部 |
| **总计** | | **~6.5h** | |

---

## 十二、风险与缓解

| 风险 | 缓解 |
|------|------|
| DeepSeek API 限流 | 评分 < 0.5 的新闻跳过 LLM，规则评分直接使用 |
| LLM 输出格式不稳定 | 重试机制 + JSON 修复 + 降级到规则评分 |
| 市场数据采集失败 | yfinance/stock-scanner 双源回退 |
| 冷启动（无校准数据） | 前 20 条评估不使用校准提示 |
| 过度依赖 LLM 评估 | 保留规则评分为 baseline，定期对比 |

---

> **审核后开始实施** | 设计对应网页版: `web/static/impact-proposal.html`
