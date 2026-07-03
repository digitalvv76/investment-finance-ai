# Market Impact Evaluator — 开发规格文档

> **版本**: v1.0  
> **日期**: 2026-07-03  
> **状态**: ⏳ 待实施  
> **预估工时**: ~5.5 小时  
> **参考**: `web/static/impact-proposal.html` (可视化方案)

---

## 一、目标

基于 LLM 的市场影响评估引擎，独立于现有手机告警体系运行，解决规则系统对宏观事件评估不准的问题。

现有 PriorityScorer（9因子规则）对宏观事件评估与基准偏差 **0.37**，目标将偏差降至 **<0.15**。

---

## 二、双轨架构

```
现有轨道 (不变):  News → PriorityScorer → StrategicDetector → AlertDispatcher → 📳 手机震动
新轨道 (独立):   News → ImpactEvaluator (LLM) → ImpactAssessment → 📊 Dashboard + Telegram
```

**隔离原则**:
- ImpactEvaluator **不连接** AlertDispatcher
- 新评分 **不写入** `news.priority_score` 字段
- 新表独立存储
- Dashboard 通过 `/impact` 子页面访问

---

## 三、核心模块

### 3.1 ImpactEvaluator (`engine/impact_evaluator.py`)

LLM 五步推理链评估器：

```python
class ImpactEvaluator:
    def evaluate(self, news_item: NewsItem, market_context: dict) -> ImpactAssessment:
        """
        1. 构建 System Prompt (五步推理)
        2. 调用 DeepSeek LLM (结构化 JSON 输出)
        3. 解析返回 → ImpactAssessment dataclass
        """

class ImpactAssessment:
    impact_score: int       # 0-100
    confidence: int         # 0-100  
    event_category: str     # monetary|geopolitical|macro_data|corporate|regulatory|other
    surprise_level: str     # expected|minor_surprise|major_surprise|shock
    breadth: str            # single_stock|sector|broad_market|cross_asset
    reasoning_chain: list   # 5 step descriptions
    similar_events: list    # historical precedents
    expected_moves: dict    # {equities, bonds, fx, commodities}
    calibration_note: str   # self-correction hint
```

**LLM 推理五步**:
1. **事件类型** — 货币政策 > 地缘政治 > 宏观数据 > 企业财报 > 常规信息
2. **惊喜幅度** — 实际 vs 预期偏差，0.1% CPI 差是噪音，0.5% 是信号
3. **市场广度** — 单股 → 板块 → 大盘 → 跨资产 (股+债+汇+商品)
4. **历史先例** — 过去 2 年类似事件的市场反应
5. **当前情绪** — VIX / Fear & Greed 状态 (恐惧放大负面，贪婪放大正面)

**容错设计**:
- LLM 超时 30s → 返回空评估 (不阻塞管线)
- JSON 解析失败 → 重试 1 次，仍失败则跳过
- DeepSeek 不可用 → 静默降级，不影响 News Monitor 运行

### 3.2 ImpactCollector (`engine/impact_collector.py`)

事后采集实际市场数据，用于验证预测：

```python
class ImpactCollector:
    def collect_actual(self, assessment: ImpactAssessment, 
                       wait_minutes: int = 60) -> ImpactOutcome:
        """
        等待市场反应后采集:
        - SPX Δ% (yfinance mcp__yfinance__get_historical_stock_prices)
        - VIX Δ% 
        - 板块变动 (stock-scanner tradingview_sector_performance)
        - 跨资产联动检测
        """
```

### 3.3 ImpactLearner (`engine/impact_learner.py`)

自学习闭环：

```python
class ImpactLearner:
    def analyze_deviation(self, assessment_id: int) -> dict:
        """预测 vs 实际偏差分析，按事件类型分组"""
    
    def generate_calibration_hint(self) -> str:
        """生成校准提示，注入下轮 LLM Prompt
        e.g. "过去10次 monetary 事件评估平均高估12点，建议降低 monetary baseline"
        """
    
    def update_calibration_state(self):
        """更新 calibration_state 表，供下次评估使用"""
```

**学习维度**:
| 维度 | 跟踪 | 校准动作 |
|------|------|---------|
| 事件类型偏差 | monetary ±X, macro ±Y | 调整该类型 baseline |
| 惊喜幅度 | over-estimate minor surprises | 提高 shock 门槛 |
| 广度误判 | 预测 cross_asset 实际 sector | breadth 降权 |
| 情绪状态 | fear 高估, greed 低估 | VIX 调整系数 |
| 时效衰减 | 旧评估不准 | 加权近期样本 |

---

## 四、数据模型

### 4.1 新 SQLite 表

```sql
-- 存储每次 LLM 评估结果
CREATE TABLE impact_assessments (
    id INTEGER PRIMARY KEY,
    news_id INTEGER,              -- FK → news_items.id
    impact_score REAL,            -- 0-100 LLM 预测
    confidence REAL,              -- 0-100
    event_category TEXT,
    surprise_level TEXT,
    breadth TEXT,
    reasoning_chain TEXT,         -- JSON array
    similar_events TEXT,          -- JSON array
    expected_moves TEXT,          -- JSON
    calibration_note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 存储事后实际市场数据
CREATE TABLE impact_outcomes (
    id INTEGER PRIMARY KEY,
    assessment_id INTEGER,        -- FK → impact_assessments.id
    spx_change_pct REAL,
    vix_change_pct REAL,
    sector_changes TEXT,          -- JSON {sector: change_pct}
    actual_score REAL,            -- 归一化 0-100
    collected_at TIMESTAMP
);

-- 存储校准状态 (自学习)
CREATE TABLE calibration_state (
    id INTEGER PRIMARY KEY,
    category TEXT UNIQUE,         -- event_category or 'global'
    bias REAL,                    -- 平均偏差 (正=过估)
    sample_count INTEGER,
    last_updated TIMESTAMP
);
```

### 4.2 Actual Score 归一化公式

| 维度 | 公式 | 权重 |
|------|------|------|
| 标普变动 | `min(|SPX_Δ%| / 0.03, 1.0) × 100` | 40% |
| VIX 变动 | `min(|VIX_Δ%| / 0.15, 1.0) × 100` | 25% |
| 板块广度 | `(affected_sectors / 11) × 100` | 20% |
| 跨资产联动 | `(bonds + fx + commodities moved) / 3 × 100` | 15% |

**例**: SPX -2.1%, VIX +18%, 5/11 板块跌>2%, 债券异动 → (0.7×40)+(0.72×25)+(0.45×20)+(0.33×15) = **60 (moderate-high)**

---

## 五、API + Dashboard

### 5.1 REST API (`web/routes.py`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/impact/latest?limit=20` | GET | 最近 N 条评估 |
| `/api/impact/<id>` | GET | 单条评估详情 (含推理链) |
| `/api/impact/<id>/outcome` | GET | 单条评估的实际结果 |
| `/api/impact/calibration` | GET | 当前校准状态 |
| `/api/impact/stats` | GET | 汇总统计: MAE/样本数/最佳最差 |

### 5.2 Dashboard 页面 (`web/static/impact.html`)

- 评估列表 — 最近评估的 impact_score 排序
- 推理链展开 — 点击查看 5 步推理详情
- 校准曲线 — X=预测分, Y=实际分, 理想 45° 对角线
- 偏差仪表 — 按事件类型分组显示系统偏差
- 学习面板 — MAE 趋势 / 样本统计 / 最佳最差类别

---

## 六、Telegram 推送

独立于告警通道，**不震动**：

| 规则 | 配置 |
|------|------|
| 触发条件 | `impact_score ≥ 50` (可配置) |
| 频率限制 | 每 30 分钟最多 1 条 |
| 用户控制 | `/impact_on` `/impact_off` |
| 格式 | Markdown 卡片，含评分 + 推理摘要 |
| 时段 | 仅市场时段 (可选) |

**推送格式**:
```
📊 Market Impact: 78/100  🟠 Major — Cross-Asset
美国宣布对进口汽车加征25%关税

📈 预期: 汽车重挫 | 避险涌入 | VIX 飙升
🧠 推理: 贸易战升级→供应链冲击→风险偏好骤降
📅 类似: 2018-03-01 钢铝关税: -2.3%

⚠️ 非手机告警 /impact_off 关闭
```

---

## 七、实施步骤

| # | 模块 | 文件 | 预估 |
|---|------|------|------|
| 1 | 数据模型 | `storage/models.py` + `storage/database.py` | 30min |
| 2 | LLM 评估器 | `engine/impact_evaluator.py` | 1h |
| 3 | 实际影响采集 | `engine/impact_collector.py` | 1h |
| 4 | 自学习引擎 | `engine/impact_learner.py` | 1h |
| 5 | Web API | `web/routes.py` | 30min |
| 6 | Dashboard 页面 | `web/static/impact.html` | 1h |
| 7 | 集成测试 | `tests/test_impact_evaluator.py` | 30min |

**总计: ~5.5 小时**

---

## 八、测试验证

### 基线对比 (16条宏观新闻)
| 指标 | 现有 (规则) | 新方案 (预期) |
|------|-----------|-------------|
| 与基准平均偏差 | 0.37 | <0.15 |
| N7 关税识别 | 0.21 (NORMAL) | ~85 (正确) |
| N3 CPI 超预期 | 0.29 (NORMAL) | ~75 (正确) |
| 推理可解释性 | 无 | 5步推理链 |
| 自校准 | 无 | 自动偏差修正 |

### 测试脚本
`scripts/score_news_only.py` — 已存在，16条新闻评分对比，可直接复用验证新方案。

---

## 九、参考

- 可视化方案: `web/static/impact-proposal.html`
- 16条新闻评分: `scripts/score_news_only.py`
- 训练案例评分: `scripts/score_training_cases.py`
- PriorityScorer 当前实现: `engine/priority.py`
- AlertDispatcher 当前实现: `engine/alert_dispatcher.py`
