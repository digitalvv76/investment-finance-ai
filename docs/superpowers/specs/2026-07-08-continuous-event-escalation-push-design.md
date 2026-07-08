# 持续演进事件 · 事件级升级推送设计

> 分支: `v1-stable` | 日期: 2026-07-08 | 状态: 设计已确认，待写实施计划
> 触发案例: 美伊冲突升级（wallstreetcn 3776459）— 24h 滚动演进的高影响地缘事件

## 1. 背景与问题

### 1.1 现象
生产观察报告（2026-07-08，近 24h）暴露两个问题：
- **高影响被静音**：霍尔木兹海峡 impact 95、伊朗主权控制 impact 85，LLM urgency 全判 INFO → Telegram 静音，不震手机。
- **系统性高估**：全类别 calibration bias 为正（macro_data +56、geopolitical +46），但这是另一个问题（校准），本设计不处理。

### 1.2 根因
当前推送分级 (`engine/alert_dispatcher.classify`) 是**逐条**按单条新闻的 urgency/impact 判定。美伊这类事件在 24h 内以**多条各自中等**的新闻滴漏式出现（军事打击 → 外交回应 → 制裁变动 → 市场反应），系统：
- 把每条当孤立时间点，**识别不到累积/升级的分量**；
- 逐条静音推送，既不升级也不聚合。

### 1.3 关键发现：事件聚类是死代码
`engine/cluster.py` 的 `NewsCluster` **仅在测试中被调用**，生产未接线。且 `find_or_create_event` 存在缺陷：匹配不到既有事件线时返回 `None`，从不调用 `_create_event` —— 即**第二条印证新闻不会真正建簇**。本设计的前提是**激活并修复聚类**。

## 2. 目标与非目标

### 目标
把**事件级动量**接入推送决策：对持续演进的高影响事件，给予事件级升级推送，而非逐条静音。每个事件**最多 3 次推送**（其中手机打断 ≤2 次：ALERT + FLASH；CLOSE 仅 Telegram）。

### 非目标
- 不改校准/高估问题（独立议题）。
- 不用 LLM 做升级**判断**（成本/延迟）；LLM 仅在升级发生时写一次推送**文案**。
- 不改现有逐条推送链路（两条链路独立并存）。

## 3. 需求（已与用户确认）

| 决策点 | 用户选择 |
|--------|---------|
| 推送模型 | 升级警报 + 重大变化更新 |
| 升级触发 | 混合：多源+高影响触发初次警报，市场确认再升级 |
| 重推边界 | 只推「市场确认」和「反转/结束」，其余全静音（最少打扰）|
| 市场确认阈值 | `\|ΔSPX\|≥0.2%` 或 `ΔVIX≥+5%` 或 `\|Δ油\|≥0.5%` |
| 市场确认闸门 | 时间对齐（警报后）+ 方向一致 |

## 4. 架构与数据流

```
采集器 → 逐条入库 + 逐条推送（现有链路，不改）
            └─(新) 激活聚类：每条新闻 → NewsCluster → EventLine（建/并簇）
调度器 _tick_5min ─(新)→ EventEscalator.sweep()
            ├ 遍历活跃 EventLine
            ├ 从成员新闻算事件动量（来源数/峰值impact/主导类别与情绪）
            ├ 跑状态机（NONE→ALERTED→CONFIRMED→CLOSED）
            └ 转换需推送 → LLM 写文案(仅此刻) → AlertDispatcher 事件级入口
```

逐条推送链路与事件级升级链路**完全独立**，互不阻塞。

## 5. 组件清单

| 组件 | 动作 | 职责 |
|------|------|------|
| `engine/cluster.py` | 改 | 修 `find_or_create_event`：匹配不到时以第二条印证新闻建 EventLine；接入采集路径 |
| `engine/event_escalator.py` | 新 | 核心：`sweep()` + 动量计算 + 状态机 + 触发推送 |
| `engine/market_snapshot.py` | 新（薄）| 抽出并复用 `impact_collector._fetch_index_changes`；加油价 `CL=F`/`BZ=F`；返回自指定时刻起的 ΔSPX/ΔVIX/Δ油 |
| `storage/models.py` + `storage/database.py` | 改 + 迁移 | EventLine 加 5 字段（§6）|
| `collector/scheduler.py` | 改 | `_tick_5min` 挂 `escalator.sweep()`，异常隔离 |
| `engine/alert_dispatcher.py` | 改（小）| 加 `dispatch_event()` 事件级入口，复用现有分级/多通道推送 |
| `config/event-escalation.json` | 新 | 所有阈值集中可调 |

### 单元职责边界
- **NewsCluster**：只管"哪些新闻属于同一事件"，输出 EventLine。不懂推送。
- **EventEscalator**：只管"事件是否该升级"，输入 EventLine，输出状态转换决策。不懂怎么取价、怎么发推。
- **MarketSnapshot**：只管"自某时刻起市场动了多少"，输入起始时刻，输出 Δ。无状态。
- **AlertDispatcher**：只管"把一条推送按级别发到各通道"，已有，复用。

## 6. 数据模型变更

`EventLine` 新增字段（SQLite `ALTER TABLE ADD COLUMN`，向后兼容）：

| 字段 | 类型 | 默认 | 用途 |
|------|------|------|------|
| `escalation_state` | TEXT | `'NONE'` | 状态机：NONE/ALERTED/CONFIRMED/CLOSED |
| `peak_impact` | REAL | `0.0` | 成员新闻中最高 impact_score |
| `dominant_category` | TEXT | `''` | 主导 event_category（geopolitical/monetary/...）|
| `dominant_sentiment` | TEXT | `''` | 主导情绪，用于市场确认的方向判定 |
| `alerted_at` | TEXT(datetime) | NULL | 首次 ALERT 时刻，用于冷却 + 市场确认时间对齐 |

迁移经 `/db-migration` 技能：影响评估 + 迁移脚本 + 回滚脚本。`ADD COLUMN` 对既有行安全填默认值。

## 7. 升级状态机 + 阈值

状态：`NONE → ALERTED → CONFIRMED → CLOSED`。每事件**最多 3 次推送**（手机打断 ≤2 次：ALERT + FLASH；CLOSE 仅 Telegram，不打电话）。

| 转换 | 条件 | 推送级别 |
|------|------|---------|
| NONE→ALERTED | `source_count ≥ 3` **且** `peak_impact ≥ 70`，且事件 12h 内活跃 | 📳 ALERT（响铃：Pushover high + Telegram alert）|
| ALERTED→CONFIRMED | 市场确认（§8）| 🚨 FLASH（警笛：Pushover emergency + Telegram triple）|
| ALERTED/CONFIRMED→CLOSED | 反转：市场回吐已确认波动的 >50%；**或** 静默：≥6h 无新成员新闻 | 📄 最后更新（Telegram alert；不打电话）|
| 冷却 | ALERTED 后 3h 内，只允许转 CONFIRMED 或 CLOSED，不重复同级 ALERT | — |

- 状态持久化在 `EventLine.escalation_state`，**重启不丢**。
- **幂等**：每次转换只推一次；sweep 只在状态实际改变时发推。
- 未达 ALERTED 的事件：不产生任何事件级推送（成员新闻仍走现有逐条链路）。

### 动量计算（每次 sweep，从成员新闻聚合）
- `source_count`：成员新闻的去重来源数。
- `peak_impact`：成员 ImpactAssessment 的最高 impact_score。
- `dominant_category` / `dominant_sentiment`：成员众数。
- `velocity`（近 60min 新增成员数）：本期仅记录，供未来用，不参与触发。

## 8. 市场确认（ALERTED→CONFIRMED）详细

复用 `impact_collector` 的 yfinance 取价机制，抽成无状态 `MarketSnapshot.since(alerted_at)`，返回 `ΔSPX%, ΔVIX%, Δ布伦特%`。

确认成立需**同时**满足三闸：
1. **时间对齐**：波动自 `alerted_at` 起算（不是全天累计）。
2. **方向一致**（由 `dominant_sentiment` 推出风险方向）：
   - 利空/避险事件（BEARISH / CAUTIOUSLY_BEARISH）：SPX 跌、VIX 涨、油涨（地缘/能源类供给风险）才算数。
   - 利多事件：镜像（升级场景罕见，但定义完整）。
   - 中性：仅认 VIX 涨（避险）。
3. **幅度**（任一资产在正确方向达标即确认）：
   - `ΔSPX ≤ -0.2%`（利空向下）
   - `ΔVIX ≥ +5%`
   - `Δ布伦特 ≥ +0.5%`（仅当 `dominant_category ∈ {geopolitical, macro_data}` 且事件涉能源）

油价方向映射（供给冲击→涨）放 config，便于后续细化。

## 9. 错误处理

- **yfinance 失败**（周末/盘前/超时）：跳过市场确认级，**不阻塞** ALERT；事件停在 ALERTED，下次 sweep 重试（沿用 `impact_collector` 现有 try/except graceful fallback）。
- **LLM 写文案失败**：模板兜底（标题 + 来源数 + 峰值 impact + Δ市场），照常推送。
- **sweep 异常**：整个 sweep 包在 try/except，单事件异常不影响其他事件与调度器其他 tick（沿用 Phase 4a `asyncio.gather` 隔离风格）。
- **重复推送防护**：状态转换写库与发推在同一逻辑内，先判状态再发；幂等键为 `(event_id, escalation_state)`。

## 10. 测试策略

- **单元测试**（`tests/test_event_escalator.py` 新增）：
  - 状态机每个转换（NONE→ALERTED→CONFIRMED→CLOSED）与非法转换被拒。
  - 动量计算：source_count 去重、peak_impact 取最大。
  - 阈值边界：source_count=2/3、peak_impact=69/70。
  - 市场确认三闸：时间对齐、方向不一致被拒、幅度边界。
  - 冷却窗内不重复 ALERT；幂等（同状态二次 sweep 不重推）。
- **集成测试**：喂一串美伊式新闻（impact 85-95 逐条到达 + mock 市场向下）→ 断言恰好产生 `1×ALERT + 1×FLASH + 1×CLOSE`，不刷屏。
- **聚类测试**：修复后第二条印证新闻确实建/并 EventLine（补 `test_cluster.py`）。
- mock yfinance；复用现有 `mock_db` 模式；本地隔离环境跑（参照 `run_v2_local` 思路），**不碰生产**。

## 11. 配置（`config/event-escalation.json`）

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
  "sweep_interval": "5min"
}
```

## 12. 部署（V1 铁律）

1. 本地隔离环境验证（不碰生产 DB）。
2. DB 迁移经 `/db-migration`（回滚脚本备好）。
3. `v1-stable` 分支 commit → 测试通过。
4. `deploy.sh` 部署 ECS → 观察（新增 sweep 对 IOPS 影响可忽略：每 5min 几条小 SELECT）。
5. 验证生效 → `cherry-pick` 回 `main`。

## 13. 未来增强（本期不做）

- LLM 事件卡片：升级文案可扩展为带时间线的富文本卡片。
- velocity/加速度纳入触发。
- 与校准系统联动，用 `peak_impact` 的类别 bias 修正后再判 ALERT 阈值。
