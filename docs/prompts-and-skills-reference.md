# Prompts & Skills 参考手册

> 面向合作方的借鉴文档 — 涵盖本项目的 CLAUDE.md 架构、7 个 Skill 工作流、11 个 LLM Prompt 设计，以及关键工程模式和踩坑经验。
> 最后更新: 2026-07-12

---

## 目录

1. [系统架构总览](#系统架构总览)
2. [CLAUDE.md — AI 操作系统的「大脑」](#claudemd--ai-操作系统的「大脑」)
3. [Skills — 可复用的领域工作流](#skills--可复用的领域工作流)
4. [Prompt Engineering — 11 个 LLM Prompt 详解](#prompt-engineering--11-个-llm-prompt-详解)
5. [关键工程模式](#关键工程模式)
6. [核心踩坑经验](#核心踩坑经验)

---

## 系统架构总览

```
CLAUDE.md (顶层指令集 — AI 的行为准则)
    │
    ├─→ Skills (7个工作流 — 每个是一个可复用的领域专家)
    │   ├── stock-research      个股深度研究
    │   ├── quant-strategy      量化策略开发回测
    │   ├── portfolio-management  投资组合管理
    │   ├── daily-briefing      每日市场简报
    │   ├── db-migration       数据库安全变更
    │   ├── deployment-checklist  上线前5道门禁
    │   └── visual-design      视觉规范一致性
    │
    ├─→ Prompts (11个LLM Prompt — 驱动后端新闻处理流水线)
    │   ├── event_driven_v1.txt  事件驱动评估 (核心)
    │   ├── impact_v1.txt        市场影响评估
    │   ├── ANALYSIS_PROMPT      深度分析 Flash Note
    │   ├── Actionability Review  推送二次审核
    │   ├── CURATOR_PROMPT       新闻策展评分
    │   ├── EXTRACT_PROMPT       知识提取
    │   └── TRANSLATE_PROMPT     标题翻译
    │
    └─→ 工程基础设施
        ├── SessionStart/End Hooks  (会话持久化)
        ├── PreToolUse Hooks        (提交前检查)
        ├── 质量把关 (对抗式核实)
        └── Cron 定时任务
```

**核心思想**: CLAUDE.md 定义「AI 怎么工作」，Skills 定义「做什么事」，Prompts 定义「LLM 怎么判断」。三层各司其职，互相解耦。

---

## CLAUDE.md — AI 操作系统的「大脑」

### 角色分工 (最高优先级)

这是本项目最重要的设计决策：**把人类和 AI 的职责边界写死在配置文件里**。

| 维度 | 用户 (人类) | AI |
|------|:---:|:---:|
| 投资决策 | ✅ 最终决定 | ❌ 不介入、不建议 |
| 业务方向与需求优先级 | ✅ 决定 | ❌ 不决定 |
| 架构设计 | ❌ 不关心 | ✅ 全权负责 |
| 技术选型 | ❌ 不关心 | ✅ 全权决定 |
| 代码实现 | ❌ 不关心 | ✅ 全权负责 |
| 测试策略 | ❌ 不关心 | ✅ 全权决定 |
| 部署运维 | ❌ 不关心 | ✅ 全权负责 |

**设计理念**: 用户是金融专家不是程序员，不看代码、不关心技术细节，只看结果。AI 在纯技术领域自行决策不征求，涉及投资行为（推送频率、信息展示、风险提示）才征求意见。

### AI 执行原则

```
纯技术问题 → 自行决策并执行，不征求用户
涉及投资工作流影响 → 征求意见后执行
用户给业务方向 → 自主完成 设计→实施→测试→部署 全流程
不可逆操作 (删数据/改密钥) → 先确认再执行
每个任务完成 → 简洁汇报结果
```

### 首次响应规则

每次新会话，AI 第一条响应**必须**先读 HISTORY.md + SESSION.md，主动展示操作摘要 + 当前状态 + 下一步。不允许直接回答用户问题。

### 会话持久化

```
HISTORY.md   ← 跨会话唯一真相来源 (仅追加不覆盖)
SESSION.md   ← 当前工作状态 (进行中/下一步/踩坑)
TROUBLESHOOTING.md ← 踩坑记录 (问题→根因→修复)
```

### 质量把关 (轻量风险闸门)

高风险改动（碰推送逻辑/数据库 schema/部署上线/安全凭证/跨模块）部署前必须过：

1. **对抗式核实**: 派独立子 agent，指令必须点名具体核实，对着代码证伪，不从名字臆断
2. **地面真值优先**: 必须有覆盖该行为的测试
3. **自动修复上限 2 轮**, 模糊直接报人

> 铁律: 同模型 agent 共享盲点 — 真杠杆是**对着代码/测试证伪**，不是堆角色 agent。

---

## Skills — 可复用的领域工作流

每个 Skill 是一个独立的 Markdown 文件，包含触发词、MCP 数据源可用性检查、分步工作流、输出格式、状态持久化指令。

### 1. stock-research (个股深度研究)

**触发词**: `分析`, `研究`, `研报`, ticker 符号 (NVDA/AAPL/600519)

**工作流** (8步):
```
Step 0: 检查 MCP 健康 (哪个数据源可用)
Step 1: 识别市场 (US/A股/港股/Crypto)
Step 2: 并行采集 10 类数据 (行情/历史/基本面/技术面/新闻/内部交易/宏观/情绪)
Step 3: 技术分析 (趋势/动量/波动率/成交量/支撑阻力)
Step 4: 基本面分析 (估值/增长/质量/财务健康/DCF估算)
Step 5: 情绪与催化剂 (新闻情绪/即将发生事件/宏观背景)
Step 6: 风险评估 (公司特有/市场/尾部风险)
Step 7: 生成研报 (BUY/HOLD/SELL + 目标价 + 7段结构)
Step 8: 持久化状态 (保存报告 + 更新 ARCHIVE.md + 更新 watchlist-state.md)
```

**输出格式**: 7 段机构级研报 (执行摘要→公司概览→技术分析→基本面→估值→风险→催化剂)

### 2. daily-briefing (每日市场简报)

**触发词**: `早报`, `日报`, `briefing`, `morning`

**工作流** (8步):
```
Step 0: 加载跨技能状态 (portfolio/watchlist/signals/macro)
Step 1: 全球市场快照 (美股/A股港股/加密/大宗商品 并行采集)
Step 2: 关注列表更新 (每个 ticker 的价格/技术触发/支撑阻力)
Step 3: 持仓状态 (总市值/P&L/盈亏排行/止损预警)
Step 4: 活跃信号 (到期/触发/已平仓表现)
Step 5: 经济日历 (财报/数据发布/假日)
Step 6: 要闻速览 (前5条)
Step 7: 按模板输出简报
Step 8: 归档 + 刷新跨技能状态文件
```

### 3. quant-strategy (量化策略)

**触发词**: `策略`, `回测`, `量化`, `signal`

**工作流** (7步):
```
Step 1: 理解策略需求 (类型/标的池/时间框架/约束)
Step 2: 拉历史数据 (至少2年 OHLCV)
Step 3: 实现策略逻辑 (动量/均值回归/均线交叉/突破)
Step 4: 跑回测 (收益/风险/风险调整/交易统计/基准对比)
Step 5: 生成当前信号 (BUY/SELL/WAIT + 入场/止损/止盈/仓位)
Step 6: 按模板输出
Step 7: 持久化信号 (active.json + history.jsonl + memory)
```

**铁律**: 绝不自动执行交易，始终等待人工审核。每信号必带止损。单笔不超过组合 5%。

### 4. portfolio-management (投资组合管理)

**触发词**: `组合`, `持仓`, `调仓`, `risk`, `allocation`

**工作流** (8步):
```
Step 1: 采集持仓数据 (代码+权重/股数→市值)
Step 2: 当前状态分析 (各周期收益/配置偏离/P&L/集中度)
Step 3: 风险评估 (Beta/相关性矩阵/波动率/VaR/CVaR/最大回撤/压力测试)
Step 4: 宏观叠加 (收益率曲线/CPI/利率/VIX)
Step 5: 优化 (均值方差/风险平价/最小方差/Black-Litterman)
Step 6: 调仓计划 (买卖/数量/优先级/税务/限价)
Step 7: 按模板输出
Step 8: 持久化组合状态
```

### 5. db-migration (数据库安全变更)

**触发词**: `schema`, `migration`, `改表`, `alter table`

**核心规则**: 绝不直接动数据库 schema。必须走 4 步流程：影响评估 → 备份 → 写迁移脚本 (含回滚) → 应用+验证。

### 6. deployment-checklist (上线前检查)

**触发词**: `deploy`, `上线`, `发布`, `ship`

**5 道门禁**: 凭证完整性 → 测试全绿 → 代码质量 → 安全扫描 → 回滚方案。任一道失败即停。

### 7. visual-design (视觉规范)

**触发词**: `UI`, `页面`, `前端`, `样式`

**核心规则**: 写任何 HTML/CSS 前必须先读 DESIGN.md。Bloomberg 暗色主题统一 5+ 页面，禁止硬编码颜色。

---

## Prompt Engineering — 11 个 LLM Prompt 详解

### 核心设计原则

1. **结构化输出**: 所有判断型 prompt 返回 JSON，不做自由文本（可解析、可统计、可校准）
2. **Few-shot 校准**: 嵌入人工标注的真实案例，不是教模型"怎么做"而是教它"什么是对的"
3. **失败朝安全侧**: 默认值朝向静音/不推送（confirmed 默认 false），宁可漏推也不错推
4. **逐层过滤**: 相关性初筛 → 催化剂分类 → 强度研判，每层独立可测试
5. **人味判断**: 中文 headline_signal/risk_snapshot 用人话写交易逻辑，不是模板填词

---

### Prompt 1: event_driven_v1.txt — 事件驱动评估器 (最核心)

**文件**: `news-monitor/config/prompts/event_driven_v1.txt`
**用途**: 实时扫描新闻标题+摘要，三步判定是否推送及强度
**Temperature**: 0 (严格确定性)
**Provider**: DeepSeek (`deepseek-chat`)

**三步流水线**:

#### 第一步: 相关性初筛
判断新闻是否与美股投资有关。定义了 5 种无关类型（纯政治/非美市场/娱乐/旧闻/孤立非权益类），但**加了反过滤例外**——政府行业级补贴即使无单一纯玩家也必须深挖受益面。

#### 第二步: 五大催化剂识别
```
1. 政府/国家资本入股或资助 (CHIPS/DOE/DARPA → ★★★★起)
2. AI 超级巨头绑定 (NVIDIA/MSFT/OpenAI 参股/合作)
3. 领袖级终局预言 (黄仁勋/马斯克/Altman 的万亿级表述)
4. 硬核里程碑批准/突破 (FDA/FAA/量子优越性)
5. 极端空头挤压/模因引爆 (已发生的真挤压, 纯预测不推)
```

**关键设计**: 第5类加了「已发生 vs 预测」门槛——"或再现模因行情"不推，"今日暴涨45%熔断轧空"推。

#### 第三步: 强度研判 (与方向解耦)
```
intensity (1-5): 只量波动剧烈程度, 不分涨跌
direction (up/down/neutral): 独立判定方向
confirmed (bool): 信源确定性 — 默认 false (失败朝安全侧)
```

**核心创新: direction/confirmed 双字段**。利空暴跌同样是 intensity=5，但 `confirmed=false` 的利空传闻只上 Telegram 静音不上手机警笛。这解决了「传闻误拉警笛」的长期痛点。

#### Few-shot 校准样例 (9 例)
嵌入人工校准的真实案例贯彻核心原则：
- 政府资本一律大利好，看短期不看长期
- 广度不降级（行业级补贴反而要深挖受益面）
- 小市值弹性加分
- 信源置信度打折（reportedly → 压强度 + confirmed=false）
- 纯A股不推

---

### Prompt 2: impact_v1.txt — 市场影响评估

**文件**: `news-monitor/config/prompts/impact_v1.txt`
**用途**: 后端影响评分 (0-100)，返回结构化 JSON
**Temperature**: 0.3
**Provider**: DeepSeek / Anthropic

**关键设计**:

#### 事件 vs 观点区分 (第0步)
```
CONCRETE EVENT (实际发生的)   → 正常评分
ANALYST OPINION (某人观点)    → max impact_score: 25
```

这解决了「分析师研报被当成市场事件误推」的问题——市场不会因为某人说"X 可能翻倍"而动，除非报告了已经发生的事。

#### 五维评估框架
1. 事件类型与固有显著性
2. 意外幅度 (偏离预期多远)
3. 市场广度 (个股→板块→指数→跨资产)
4. 历史先例 (few-shot 注入)
5. 当前市场环境 (VIX/Fear & Greed)

#### 动态注入
- `{historical_examples}` — EventMatcher 从历史库检索 top 3 相似事件
- `{calibration_hint}` — ImpactLearner 自学习偏差纠正 (如 "倾向高估货币政策 ~5分")
- `{market_context}` — 实时 VIX/情绪指数

---

### Prompt 3: ANALYSIS_PROMPT — 深度分析 Flash Note

**文件**: `news-monitor/engine/deep_lane.py`
**用途**: 以买方分析师口吻写 250-300 字中文 Flash Note
**Temperature**: 0.3
**Provider**: DeepSeek / Anthropic

**四段结构**:
```
① 事件定性 (1-2句, 什么发生了)
② 传导路径 (只留直接链, 去间接/加密)
③ 组合映射 (强制映射到用户持仓∪关注股, 带方向词偏多/偏空, 禁价位买卖)
④ 置信度 (1行)
```

**关键约束**:
- 全文 ~250-300 字写死 (实测从 1484 字压缩)
- ③ 主受益股不在仓 → 改指同链条跟踪票
- 无行情数据时：只给利好/利空方向，不给偏多/偏空交易词，全程无数字 (anti-fabrication 硬门禁)
- 用户可通过 Telegram `/analyze set` 自定义完全替换

---

### Prompt 4: Actionability Review — 推送二次审核

**文件**: `news-monitor/engine/actionability_review.py`
**用途**: 对灰色地带 (综合评分 0.30-0.70) 的推送做最终把关
**Temperature**: 0.0 | **Max Tokens**: 10 (只输出一个词!)

```
输出: ACTIONABLE 或 NOT_ACTIONABLE

ACTIONABLE = 新事件 + 具体动作 + 可据此交易
NOT_ACTIONABLE = 回顾/威胁/假设/纯人事/历史事件/无全球影响
```

**设计亮点**: 极简输出 (10 tokens) + 明确的正反条件列表。这其实是一个「规则引擎的 LLM 实现」——规则写进 prompt 比写进代码更灵活可调。

---

### Prompt 5: CURATOR_PROMPT — 新闻策展评分

**文件**: `news-monitor/engine/curator.py`
**用途**: 批量评分新闻标题与用户兴趣的匹配度 (0-10)
**Temperature**: 0.1

**创新**: 注入用户上传文档提取的知识 (`{learned_knowledge}`)，使策展从关键词匹配升级为语义理解。

---

### Prompt 6-11: 辅助 Prompt

| # | 名称 | 用途 | 关键参数 |
|---|------|------|----------|
| 6 | EXTRACT_PROMPT | 用户文档→投资洞察摘要 | T=0.3, max 400 tokens |
| 7 | TRANSLATE_PROMPT | 英→中金融标题翻译 | T=0.1, max 200 tokens |
| 8 | DEFAULT_PROFILE | 默认投资者人设画像 | 注入 CURATOR_PROMPT |
| 9 | Calibration Hint | 自学习偏差提示 | 程序化生成 |
| 10 | Few-Shot Examples | 历史事件检索注入 | Top 3 语义匹配 |
| 11 | 用户自定义框架 | Telegram 命令替换 ANALYSIS_PROMPT | 存 DB, 完全替换 |

---

### LLM 调用参数速查

| 组件 | 模型 | Temperature | Max Tokens | 重试 |
|------|------|-------------|------------|------|
| event_driven 评估 | `deepseek-chat` | 0 | — | — |
| impact 影响评估 | `deepseek-chat` | 0.3 | 1200 | 2次 |
| deep_lane 深度分析 | `deepseek-chat` | 0.3 | 900 | — |
| actionability 审核 | `deepseek-chat` | 0.0 | 10 | — |
| curator 策展 | `deepseek-chat` | 0.1 | 500 | — |
| trainer 知识提取 | `deepseek-chat` | 0.3 | 400 | — |
| translator 翻译 | `deepseek-chat` | 0.1 | 200 | — |

**Temperature 选择逻辑**: 结构化判断 → 0 (确定性)，分析性输出 → 0.3 (有框架但不发散)，极简二分类 → 0.0

---

## 关键工程模式

### 1. 对抗式核实 (Adversarial Verification)

```
不是「找人审查」→ 是指定具体核实点让独立 agent 证伪
指令模板: "追踪变量 X 在代码里到底干什么, 别从名字臆断, 找出让它出错的场景"
```

**为什么需要**: 同模型 agent 共享盲点（本项目 4 轮对抗核实每轮都抓到前一轮的漏/误删/高危）。

### 2. 失败朝安全侧 (Fail-Safe Defaults)

```
confirmed 默认 false → 未确认事件不上手机
方向默认 neutral → 不臆测涨跌
无行情时默认全严 → 不编造价位
```

### 3. 盲测检验 (Holdout Blind Eval)

```
脚本: scripts/eval_framework_holdout.py
方法: 把样本去掉股价/标签, 只留事件陈述喂评估器
对比: 人工 ground truth vs LLM 输出
指标: 强度命中/±1容差/推送决策一致/受益股召回
关键: 自动排除已嵌入 prompt 的 few-shot 样本 (防数据泄露)
```

### 4. 双评估器并存 + 版本管理

```
event_driven 评估器 (v1) → 事件驱动路径 (快, 实时)
impact 评估器 (v1)      → 传统评分路径 (深, 有历史先例)
```

各有适用场景，不互相替代。Prompt 通过 `PromptVersionManager` 做版本切换。

### 5. 会话持久化三件套

```
HISTORY.md        ← 仅追加, 按日期分段, 每条引用 commit hash
SESSION.md        ← 覆盖更新, 记录「进行中/下一步/踩坑」
TROUBLESHOOTING.md ← 追加, 问题→根因→修复 三段式
```

SessionStart hook 自动展示摘要 + 脏工作区检测。SessionEnd hook 按 commit hash 自动补录缺失条目。

### 6. 两张登记表同步

```
config/module_registry.json     ← 旧表, session_startup 读
engine/__manifest__.json        ← 新表, pre_commit hook 读
```

改模块依赖必须两张表同步更新，否则警告复发。

---

## 核心踩坑经验

### 1. 交易动作豁免 = 高危洞
用「句含交易词就豁免方向检查」让反向事实+交易建议同句逃逸。真计划句本身无涨跌方向词，压根不需豁免 → 只对真条件/触发句豁免。

### 2. 同模型 agent 共享盲点
对抗核实 4 轮，每轮都抓到前一轮的漏。必须对着真实代码+真实 LLM 输出证伪，别信单轮共识。

### 3. 正则近似治标不治本
涨跌幅「量级+动词相邻」正则既漏（跌超 8%）又误删（触发条件）。语义问题要结构判别不是堆正则。

### 4. confirmed 默认 True = 失败朝手机开
漏写 confirmed 字段时，默认 True 会让未确认传闻误升警笛。改为默认 False——失败朝静音。

### 5. tickers_found 子串误匹配
ARM 匹配 Krispy Kreme 等。禁止用于推送门禁，改用 LLM ticker_hint。

### 6. 影子部署 --down 误删 V1 生产
`docker compose down` 拆整个 project。必须用 `rm -sf` 单服务。

### 7. dedup O(N²) 静默卡死
异步管道藏同步 O(N²) 编码阻塞事件循环，采集静默停摆 48 分钟才发现。

---

## 给合作方的建议

### 从哪里开始

1. **先读 CLAUDE.md** — 理解角色分工和执行原则，这是整个系统的基础
2. **再看 event_driven_v1.txt** — 这是最核心的 prompt，三步流水线+few-shot 校准是通用模式
3. **然后看一个 Skill** (推荐 stock-research) — 理解工作流骨架
4. **最后看质量把关** — 对抗式核实+盲测是保证 prompt 质量的核心机制

### 可以直接复用的模式

- **角色分工表**: 适用于任何「领域专家+AI 助手」场景
- **三步评估 prompt**: 初筛→分类→研判，适用于任何需要分级判断的场景
- **失败朝安全侧**: 所有 `confirmed`/`direction` 类字段默认值的设计哲学
- **盲测检验框架**: 任何 prompt 迭代都可以用这套方法验证改进效果
- **会话持久化三件套**: HISTORY + SESSION + TROUBLESHOOTING 适合任何长期 AI 项目
- **对抗式核实**: 适用于任何高风险代码变更的验证

### 需要根据自身场景调整的部分

- 五大催化剂类型（换成你自己的领域分类）
- Few-shot 样例（必须用你自己的真实案例校准）
- MCP 数据源配置（取决于你有什么数据）
- 推送渠道映射（取决于你的通知基础设施）
