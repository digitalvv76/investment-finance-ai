# REVIEW：REQ-training-eval（V2/main 窗口评审）

> 评审人：V2（评估器 + main 流水线实现 owner）｜ 2026-07-11
> 范围：**可落地性 / 工作量 / 实现坑**。方法学（RK1 相关≠因果、RK2 日级近似、指标松紧）→ **明确让给外部第三方，不重复**。
> ⚠️ 同模型共享盲点 → 本评审全部**对着 main 真实代码/DB schema 核实**，不凭文档假设。核实点标 `[已验]`。

---

## 🔴 头号发现（BLOCKER，先于 ② 设计）：event_driven 决策**完全不落库**

`[已验 pipeline/evaluate.py:96-99]`：事件路径命中即 `_apply_event_assessment(item, ea); return`——**return 前不写任何表**。
`[已验 evaluate.py:103-111]`：`insert_assessment` 只在 **legacy Path B 回退**跑。
`[已验 storage/database.py:108-134]`：连 legacy 的 `impact_assessments` 表也**没有** intensity / ticker_hint / direction / confirmed / is_event / is_push 任一字段。

**后果（直接决定 REQ 多条能不能做）：**
- **R1/R3/G4 塌方**：`ticker_hint` 是内存态 `[已验 event_driven_evaluator.py:47 → pipeline/item.py:38，只在运行时传递，从不落 news 表]`。`news` 表只有 `tickers_found`（D3 已弃）。→ **翻历史库拿 ticker_hint 自动标注 = 现有存储做不到**，只能重跑 LLM（贵 + prompt 已漂移，见坑#2）。
- **R4 噪音真负例"评过没推"= 捞不出**：no-push 直接 return，DB 无 is_event/notable/决策档标记。R4 说这批"当前最缺"——恰恰因为从未记录。
- **A2 precision/recall = 现成数据量不出**：`[已验 impact_outcomes]` 绑 legacy 表，只存 spx/vix/sector 宏观变化 + actual_score，**无 per-ticker 实现涨跌、无 is_push 对照**。

**建议（新增 R0，硬前置）**：加一张 `event_decisions` 表，事件路径 return 前写入
`news_id, is_event, intensity, direction, confirmed, ticker_hint, alert_level(=is_push 依据), prompt_version, created_at`。
V2 活，~0.5 天。**这是整个项目的地基——不补，②③④全建在沙上。**
配套结论：**别指望回填历史**。从落库日起「每天出题→市场给答案」自增长（这本就是 G4 原意）；历史冷启动靠 26 条人工锚点种子 + 自动标新增。

---

## 逐条对应 REQ

### R1/R3/R4 数据来源（评审点2）
- ticker 源：D3 选 ticker_hint **方向对**，但**未落库**（见头号发现）→ R2 命门在"落库 + 清洗"两道，不止清洗。
- `tickers_found` 确在库 `[已验 database.py:50 + idx]`，D3 弃它（子串误标 [[tickers-found-unreliable]]）正确。
- 噪音真负例：依赖 R0 落库表，否则无来源。

### A2 验收指标可量性（评审点3）
- 数值松紧（80/90/75/70）→ **让第三方评**，不表态。
- **能不能量**：现状**不能**（无决策×实现涨跌对照数据）。需 R0 落库 + 一个 outcome collector 按 ticker_hint 回补 T+1 涨跌——原型 `fetch_reaction()` 可复用，但要把 `_first_ticker(tickers_found)` 换成 `ticker_hint`。

### R5 / RK4 防泄露（评审点4）
- `[已验 config/prompts/event_driven_v1.txt：89 行 / 0 条 few-shot]`。→ 现在 prompt **根本没有 few-shot**，"排除已嵌入 4 样本(gov-01/07/jensen-07/gov-10)"目前是**前瞻空操作**（D1 路线 A 尚未落地）。
- 最稳落点：few-shot 样本 ID 与排除清单**单一真相源**（如 `config/prompts/fewshot_ids.json`），标注流水线生成留出集时 `WHERE news_id NOT IN (fewshot_ids)` 硬过滤 + **一条测试断言零交集**。
- 最易漏点：日后新增/替换 few-shot 忘同步清单 → 两处维护必漏，务必同源。

### D1 技术路线可落地性（评审点1）
- `[已验：temperature=0, max_tokens=600(输出), prompt ~13.6KB≈4-6K tokens/次]`。
- **few-shot(A) 是 per-call 常态成本**：+4~8 条示例 ≈ +600~1200 tokens/次，**每条评过的新闻都付**，生产量下是持续开销，非一次性。
- **阈值校准(C) 落点**：`[已验 evaluate.py:258-270 intensity→alert_level 方向感知映射层已存在]`——C 改这层，**零 token 成本、完全可逆**。
- **建议：C 先行**（改映射层，最省最可逆），**A 只补易错类**（旧催化/宽补贴/噪音各 1-2 条，封顶 8）。REQ 说"A+C 起步"方向对，但**排序应 C→A**，且 A 要吝啬。

### 工作量 / 排期（评审点5）
| 阶段 | 归属 | 估时 | 卡点 |
|---|---|---|---|
| **R0 落库表** | V2 | 0.5天 | 前置一切 |
| autolabel 扩展（换 ticker 源 + 复用 fetch_reaction） | V2 | 0.5天 | — |
| outcome collector（T+1 按 ticker 回补） | V2 | 1天 | yfinance 限流 |
| 盲测 harness（`eval_framework_holdout.py` 已有骨架 14 条 `[已验]`→扩留出集） | V2 | 0.5天 | — |
| C 阈值校准落映射层 | V2 | 0.5天 | — |
| **80 条金标集人工锚点** | V1+用户 | — | **关键路径** |
- **真卡点不是代码，是金标集人工锚点**（V1+用户）。代码可与标注并行；但验收 A2 必须等金标集。

### V1 可能漏的实现坑（评审点6）
1. **决策不落库**（头号发现）——最大坑。
2. **prompt 已漂移**：`event_driven_v1.txt` 近期改过（intensity 方向感知/精简 250-300 字）。重跑历史标注得到的是"**现 prompt 的判断**"，≠ 当时真推给用户的判断 → A4"不劣化基线"要讲清对谁比。
3. **两套评估器并存**：event_driven(主) + legacy impact(回退 Path B，且是唯一落库者)。校准/验收**只认 event_driven**，别被 legacy 落库数据污染。
4. **时区坑** [[db-captured-at-timezone]]：autolabel 用 `published_at` 定反应日，时区不一致 T+1 会错窗口 → 回补前统一 UTC。
5. **yfinance 限流**：原型 `threads=False` 逐个 download，300+ 条会慢/被限 → 跑量要缓存 + 批 + 重试。
6. **prompt_version 分层**：落库表必存 `prompt_version`（legacy 表已有此字段可借鉴 `[已验 database.py:172-ish]`），否则跨版本样本混一起无法分层验收。

---

## 结论（工程判断，不含方法学）

**REQ 整体可落地，方向正确**（轻/可逆/自增长的思路对）。但有**一个硬前提被整份文档默认成立、实则不成立**：

> 「从历史生产库自动捞 ticker_hint + 捞'评过没推'来标注」——**当前存储层做不到，因为 event_driven 的决策从不落库。**

**行动建议（排序）**：
1. **先加 R0 落库表**（V2, 0.5天），排在 ② 设计之前。
2. 数据集**从落库日自增长**，不回填历史（回填=重跑漂移 prompt，得非真值）。
3. 路线**C 先于 A**，A 吝啬补易错类。
4. 排期真卡点=**金标集人工锚点**，代码并行推进。

方法学（相关≠因果 / 日级近似 / 指标松紧）— 见外部第三方评估版，本评审不重复。

— V2/main
