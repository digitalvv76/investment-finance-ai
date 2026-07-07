# V2 Phase 2: 管道架构重构

> **设计日期**: 2026-07-07
> **状态**: 已确认，待执行
> **目标**: 将单体 main.py 拆分为独立管道层，每层可独立测试、独立替换

---

## 1. 背景

### 当前架构问题

Phase 1 建立了开发流程安全网（manifest、提交规范、pre-push hook），但代码架构本身仍是 V1 的单体模式：

| 问题 | 根因 | 影响 |
|------|------|------|
| `main.py` 上帝类 | 构造所有子系统 + 150 行管道逻辑混在一起 | 改推送流程必须动 main，无法单独测试 |
| 反向依赖 | `engine/alert_dispatcher` → `bot/telegram_bot` | 引擎层依赖推送层，方向错误 |
| 管道分裂 | `scheduler._insert_and_notify` + `main.on_news_batch` 各做一半 | 采集→清洗→分析→推送的完整链路被割裂 |
| 不可测试 | 管道逻辑嵌在回调函数里 | 无法 mock 输入验证输出 |

### 角色分工

本项目采用**金融专家 + 技术负责人**协作模式：

| 维度 | 用户（金融专家） | AI（技术负责人） |
|------|:---:|:---:|
| 投资决策 | ✅ 最终决定 | ❌ 不介入 |
| 业务方向 | ✅ 需求和优先级 | ❌ 不决定 |
| 架构设计 | ❌ 不关心 | ✅ 全权负责 |
| 技术选型 | ❌ 不关心 | ✅ 全权决定 |
| 代码实现 | ❌ 不关心 | ✅ 全权负责 |
| 测试策略 | ❌ 不关心 | ✅ 全权决定 |
| 部署运维 | ❌ 不关心 | ✅ 全权负责 |
| 推送/通知格式 | ✅ 验收确认 | ✅ 技术实现 |

**执行原则**:
- AI 遇到纯技术问题自行决策，不询问用户
- AI 在涉及投资工作流（推送频率、信息展示、风险提示）时才征求用户意见
- 用户给出业务方向后，AI 自主完成设计→实施→测试→部署全流程
- 不可逆操作（删除数据、ECS 重建、密钥变更）AI 先确认再执行

---

## 2. 设计目标

1. **每阶段可独立测试** — mock 输入 → 验证输出，不依赖完整系统启动
2. **层间显式契约** — 通过 typed dataclass 通信，接口清晰
3. **依赖方向正确** — engine 层不依赖 bot 层
4. **容错隔离** — 单条新闻异常不阻塞整批，单 channel 故障不影响其他
5. **main.py 瘦身** — 从 ~300 行缩减到 ~80 行，只做 DI + 启停

---

## 3. 管道架构

### 3.1 管道拓扑

```
INGEST → SCREEN → EVALUATE → DISPATCH
                ↘ DEEP (异步，不阻塞主链)
```

### 3.2 数据载体

```python
@dataclass
class PipelineItem:
    """贯穿管道的新闻条目，每阶段追加字段"""
    # INGEST 产出
    id: int
    title: str
    source: str
    url: str
    snippet: str
    raw_tickers: list[str]

    # SCREEN 追加
    priority_score: float = 0.0
    tickers_found: str = ""
    macro_tags: str = ""
    strategic_matches: list = field(default_factory=list)
    is_breaking: bool = False

    # EVALUATE 追加
    alert_level: AlertLevel = AlertLevel.NORMAL
    alert_reason: str = ""
    impact_score: int = 0
    signal_score: float = 0.0
    analyst_note: str = ""
    needs_deep: bool = False
```

### 3.3 阶段定义

| 阶段 | 类名 | 输入 | 核心逻辑 | 输出 |
|------|------|------|----------|------|
| INGEST | `IngestStage` | raw items (dict) | dedup → insert DB → vector index | `list[PipelineItem]` with IDs |
| SCREEN | `ScreenStage` | `list[PipelineItem]` | FastLane.process → filter ≥0.3 | `list[PipelineItem]` enriched |
| EVALUATE | `EvaluateStage` | screened items | ImpactLLM + SignalScore + Classify + Actionability | `list[PipelineItem]` with alert decisions |
| DISPATCH | `DispatchStage` | evaluated items | 遍历 channels (Pushover/Telegram/Web) | `DispatchResult` per item |
| DEEP | `DeepStage` | items with needs_deep=True | DeepLane LLM → DB persist → push | 无返回值 (fire-and-forget) |

### 3.4 每阶段接口

所有阶段实现同一 Protocol：

```python
class PipelineStage(Protocol):
    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]: ...
```

Pipeline 本身是顺序链：

```python
class Pipeline:
    def __init__(self, stages: list[PipelineStage]):
        self._stages = stages

    async def run(self, items: list[PipelineItem]) -> list[PipelineItem]:
        for stage in self._stages:
            items = await stage.process(items)
            if not items:
                break
        return items
```

---

## 4. 容错与重试

| 层 | 异常处理 | 重试策略 |
|------|----------|----------|
| SCREEN | 纯计算，单条异常 → 记录 + 跳过 | 无重试 |
| EVALUATE | LLM 调用异常 → 3 次重试（1s/2s/4s）→ 仍失败 → 降级 legacy 评分 | 指数退避 |
| DISPATCH | 逐 channel 独立，单 channel 失败不影响其他 | channel 内部自行重试 |
| DEEP | LLM 调用异常 → 1 次重试 → 静默放弃 | 不阻塞主链 |

关键保障：
- **EVALUATE 降级路径**: LLM 不可用时自动回退到 `priority_score + strategic_matches` 传统分类，推送不中断
- **DEEP 隔离**: `asyncio.Task` 独立运行，主链继续前进

---

## 5. 依赖方向修正

### 修正前

```
engine/alert_dispatcher → bot/telegram_bot  (❌ 底层依赖上层)
```

### 修正后

```
engine 层（分析与决策）
  AlertDispatcher.classify() → AlertDecision (纯数据)

pipeline/dispatch.py（推送编排）
  遍历 Channel[] 发送

pipeline/channel.py（通道实现）
  PushoverChannel / TelegramChannel / WebSSEChannel
  每个实现 Channel Protocol
```

### Channel Protocol

```python
class Channel(Protocol):
    async def send(self, item: PipelineItem, decision: AlertDecision) -> bool: ...
```

---

## 6. 目录结构

```
news-monitor/
├── pipeline/              # 🆕 管道层
│   ├── __init__.py
│   ├── __manifest__.json
│   ├── item.py            # PipelineItem dataclass
│   ├── ingest.py          # IngestStage
│   ├── screen.py          # ScreenStage  (包装 FastLane)
│   ├── evaluate.py        # EvaluateStage (ImpactEvaluator + Signal + Classify)
│   ├── dispatch.py        # DispatchStage
│   ├── deep.py            # DeepStage    (包装 DeepLane)
│   └── channel.py         # Channel Protocol + PushoverChannel + TelegramChannel + WebSSEChannel
├── engine/                # 保持不变
├── collector/             # 保持不变
├── bot/                   # 保持不变
├── storage/               # 保持不变
├── main.py                # 瘦身: DI + 组装 Pipeline + 启动/停止
```

---

## 7. 测试策略

每阶段至少 3 个测试用例：

| 测试类型 | 内容 |
|------|------|
| 正常路径 | mock 输入 → 验证输出字段正确 |
| 单条异常 | 15 条中 1 条抛异常 → 其余 14 条正常产出 |
| 边界条件 | 空输入、空 tickers、极长标题 |

额外覆盖：
- **EVALUATE**: LLM 超时 → 降级 legacy 评分
- **DISPATCH**: 单 channel 失败 → 其他 channel 仍发送

---

## 8. 不在范围内

- ❌ 不新增数据源
- ❌ 不改推送业务规则
- ❌ 不改 LLM prompt
- ❌ 不拆分独立进程（Phase 3 考虑）
- ❌ 不引入外部消息队列

---

## 9. 验收标准

- [ ] `main.py` 从 ~300 行缩减到 ~80 行
- [ ] 每阶段可独立实例化并测试（不启动完整系统）
- [ ] `engine/alert_dispatcher` 不再 import `bot/*`
- [ ] 314 existing tests 零回归
- [ ] 新增 ≥15 个管道测试
- [ ] 单条新闻 SCREEN 异常不影响同批其他新闻
- [ ] ECS 部署后推送行为与 V1 完全一致
