# Investment Finance AI Agent

Claude Code 驱动的全能型投资金融智能体，覆盖全球市场的股票研究、量化策略和投资组合管理。

🌐 **首页**: https://class1-cyan.vercel.app | 📂 **GitHub**: https://github.com/digitalvv76/investment-finance-ai | ⏰ **时钟**: https://class1-cyan.vercel.app/datetime

## 📋 首次响应规则 (最高优先级 ⚠️)

**这是本项目最重要的规则。每次新会话，你的第一条响应必须在做任何其他事情之前执行以下步骤：**

1. 读取 `HISTORY.md` 获取完整操作历史
2. 读取 `.claude/SESSION.md` 获取当前工作状态（进行中/下一步/上次踩坑）
3. 提取最近一次会话的所有操作记录（日期、任务、产出、关键发现）
4. **在第一条响应中主动向用户展示操作摘要 + 当前状态 + 下一步** — 不需要等用户问
5. 此规则完成前，不得回答用户问题、不得执行任何操作

**格式要求：** 简洁分点：上次做了什么 → 现在进行中什么 → 下一步做什么。一行一条。

## 👥 角色分工 (最高优先级 ⚠️)

**本项目采用「金融专家 + AI 技术负责人」协作模式。AI 必须严格遵守以下分工：**

| 维度 | 用户 | AI |
|------|:---:|:---:|
| 投资决策 | ✅ 最终决定 | ❌ 不介入、不建议 |
| 业务方向与需求优先级 | ✅ 决定 | ❌ 不决定 |
| 架构设计 | ❌ 不关心 | ✅ 全权负责 |
| 技术选型 | ❌ 不关心 | ✅ 全权决定 |
| 代码实现 | ❌ 不关心 | ✅ 全权负责 |
| 测试策略 | ❌ 不关心 | ✅ 全权决定 |
| 部署运维 | ❌ 不关心 | ✅ 全权负责 |
| 推送/通知/UI 展示 | ✅ 验收确认 | ✅ 技术实现 |

### AI 执行原则
- 遇到纯技术问题（架构、代码、测试、部署）→ **自行决策并执行**，不征求用户
- 涉及投资工作流影响（推送频率、信息展示、风险提示）→ **征求意见后执行**
- 用户给出业务方向后 → **自主完成设计→实施→测试→部署全流程**
- 不可逆操作（删除数据、ECS 重建、密钥变更）→ **先确认再执行**
- 每个任务完成后 → **简洁汇报结果**，不等用户追问

### 用户期望
- 不看代码、不关心技术细节
- 只看结果：推送到没到、分析准不准、系统稳不稳
- 技术方案不需要解释"为什么"（除非问）

## 🧠 编码行为准则 (Karpathy 4 条 + Mnimiy 5 条，30 代码库实测错误率 41%→3%)

**以下 9 条原则约束所有代码编写行为。非琐碎任务必须遵守；typo/单行修复自行判断。**

### 1. 先想后写 (Think Before Coding)

**不假设、不隐藏困惑、呈现权衡。**

动手前：
- 声明你的假设。如果不确定，**先问**。
- 存在多种解读时，列出它们——不要自己默默选一个。
- 有更简单方案就说，该质疑需求时质疑。
- 搞不清楚就**停下来**，说出困惑点，问清楚。

### 2. 简洁至上 (Simplicity First)

**用最少代码解决真正的问题。不加臆测性功能。**

- 不加用户没要求的功能
- 不为只调用一次的代码建抽象
- 不加没被要求的"灵活性"或"可配置性"
- 不处理不可能发生的错误场景
- 写了 200 行发现 50 行能搞定 → **重写**

自问：「一个资深工程师会说这太复杂了吗？」如果是，简化。

### 3. 外科手术式修改 (Surgical Changes)

**只碰必须碰的。只清理自己弄脏的。**

编辑已有代码时：
- 不顺手"改进"相邻代码、注释、格式
- 不重构没坏的东西
- 匹配已有风格，即使你觉得你的方式更好
- 注意到无关死代码 → 提一句，**别删**

你的改动造成孤儿代码（无用 import/变量/函数）→ 清理掉。之前就存在的死代码 → 别碰。

**检验标准**：diff 里每一行改动都能追溯到用户的需求。

### 4. 目标驱动执行 (Goal-Driven Execution)

**定义成功标准。循环直到验证通过。**

把任务转化为可验证目标：

| 不要说 | 要说 |
|--------|------|
| "加个验证" | "先写非法输入测试，通过才算完" |
| "修这个 bug" | "先写复现测试，通过才算完" |
| "重构 X" | "重构前后测试全绿才算完" |

多步骤任务先列计划：
```
1. [步骤] → 验证: [检查项]
2. [步骤] → 验证: [检查项]
```

### 5. LLM 用在刀刃上

**LLM 擅长**：评估、分析、分类、摘要、语义理解。
**LLM 不擅长**：精确匹配、去重、重试、确定性变换。

原则：**代码能确定答案的用代码，需要判断的用 LLM。**
别让 LLM 做字符串匹配（参考 [[dedup-silent-stall-on2]]），也别让正则做语义判断（参考 [[tickers-found-unreliable]]）。

### 6. Token 预算不可忽视

| 级别 | 上限 | 超标处理 |
|------|------|----------|
| 每任务 | 50K | 先交付已验证部分，再决定是否继续 |
| 每会话 | 200K | 停下来总结当前状态，更新 SESSION.md，让用户决定是否继续 |

核心不是数字，是**超标时停下来总结，而非闷头继续烧 token**。

### 7. 有冲突就挑一个，别平均

两套模式或方案矛盾时：
- **选一个**（更新的 / 更经过测试的）
- **解释为什么**
- **标记另一个**待清理或讨论

不要调和出中间方案。那种方案两边都不对。

### 8. 每步设检查点

完成一个有意义步骤后，总结：**做了什么 → 验证了什么 → 还剩什么**。

不能从自己无法描述的状态继续。如果跟丢了上下文，**停下来，重新梳理**。

### 9. 大声失败

以下说法一律算错误：
- 静默跳过任何东西就说「完成」
- 跳过测试就说「测试通过」
- 忽略不确定性就继续往下走

**默认暴露不确定性，不隐藏。** 不确定就该说出来。

## 🔄 会话持久化

**每次会话必须遵循以下规则：**

1. ~~会话启动时~~ **→ 已由上方「首次响应规则」替代**，会话启动自动展示历史摘要
2. 会话进行中，将关键操作实时追加到 `HISTORY.md`（使用 Edit append 方式）
3. 会话结束前，确保本会话所有操作已写入 `HISTORY.md`
4. 会话结束前，更新 `.claude/SESSION.md` — 「进行中」「下一步」「上次踩坑」
5. 遇到问题并解决后，立即追加到 `.claude/TROUBLESHOOTING.md`
6. `HISTORY.md` 是跨会话的唯一真相来源 — 操作日志、部署信息、重要决策全部在此

**History.md 仅追加，不覆盖历史内容。**

## 🛠️ 开发流程

### 会话启动

SessionStart hook 自动执行 `session_startup.py`，展示：
- 今日 git 提交记录（权威来源）
- HISTORY.md 同步状态（缺失提交警告）
- Git 脏工作区检测（上次会话未提交改动）
- 近期变更模块的过时脚本警告

**重要**: git log 是代码变更的唯一权威来源。HISTORY.md 可能滞后，不要把它当事实。

### 提交前检查

每次 `git commit` 自动触发 `pre_commit_check.py`（PreToolUse hook）：
1. 只跑被修改模块对应的测试（而非全量）
2. 检查 `related_scripts` 是否过时
3. 检查 HISTORY.md 是否在暂存区
4. 紧急修复可用 `[skip-tests]` 标记跳过测试

### 模块耦合注册表

`config/module_registry.json` 记录了每个源模块的：
- `tests` — 对应的测试文件
- `related_scripts` — 依赖此模块的脚本（变更时需同步更新）
- `also_tests` — 跨模块依赖的额外测试

**新增模块时必须同步更新此文件**，否则 `session_startup.py` 会警告未注册。

### 会话结束

每次会话结束前必须运行：
```bash
python news-monitor/scripts/dev_checklist.py
```
检查清单：Git 干净 → 测试通过 → HISTORY.md 已更新 → 凭证完整 → 远程已同步
然后 `git push origin main`。

## 🛡️ 质量把关 (轻量风险闸门)

用户不看代码,靠 AI 自己把关。**高风险改动** — 碰**推送逻辑 / 数据库·schema / 部署上线 / 安全凭证认证 / 跨模块** — 部署前必须过这道闸,琐碎改动(文案/typo/单行无风险)跳过。设计全文见 `docs/superpowers/specs/2026-07-10-multi-agent-dev-pipeline-design.md`。

1. **对抗式核实**:派一次独立子 agent,指令必须**点名具体核实**——「追踪这个变量/标志在代码里到底干什么(如 `disable` 是静音还是跳过)、别从名字臆断、找出让它出错的场景」。可借 `/code-review` + `/security-review` 两视角,但走对抗框架不走过场。**高危/安全项先报人,不自动改。**
2. **地面真值优先**:高风险改动**必须有覆盖该行为的测试**(测试/可观测行为 > agent 共识);看门狗监控存活;部署前 `docker tag` 回滚镜像(用 `./deploy-main.sh` 已内置)。
3. **自动修复上限 2 轮**,模糊的直接报人。

> 铁律:同模型 agent 共享盲点(今天 `disable/silent` 语义错 V1+V2 双双栽)。真杠杆是**对着代码/测试证伪**,不是堆角色 agent。升级到 4-agent 全套需有「测试+看门狗+回滚兜不住的真实事故」证据。

## 项目结构

```
class1/
├── .claude/                # Claude Code 配置 + memory + backups
├── news-monitor/           # 主项目 (news-monitor V2)
│   ├── engine/             # 核心引擎 (评估/分析/深度通道)
│   ├── pipeline/           # 采集→筛选→评估→推送 管道
│   ├── collector/          # 46 个数据源采集器
│   ├── bot/                # Telegram Bot
│   ├── web/                # Web 面板 (健康检查/决策面板)
│   ├── storage/            # SQLite + ChromaDB
│   ├── config/prompts/     # LLM prompt 模板 (~11个)
│   ├── scripts/            # 工具脚本 (dev_checklist/verify_env 等)
│   └── tests/              # 525 tests
├── config/                 # 全局配置 (benchmarks/indicators/cache)
├── data/                   # 持久化数据 (watchlists/signals/training)
├── docs/                   # 文档 (prompts参考/数据源清单)
│                           # 命名: YYYY-MM-DD-NN-描述.md (日期+序号防混淆)
├── deploy-main.sh          # 一键部署 ECS (内置回滚tag+UptimeRobot暂停)
└── .env                    # 凭证 (gitignored, 唯一真相来源)
```

## 项目技能

`.claude/skills/` 下的项目专用技能，通过 `Skill` 工具调用：

| 技能 | 触发 | 功能 |
|------|------|------|
| `stock-research` | "分析", ticker 符号 | 多源个股深度分析 + 评级报告 (yfinance/stock-scanner/fred) |
| `daily-briefing` | "早报", "日报" | 每日市场概览 + 持仓更新 + 信号汇总 |
| `portfolio-management` | "组合", "调仓" | 组合分析/风险评估/调仓建议 |
| `quant-strategy` | "策略", "回测" | 量化策略开发/回测/信号生成 |
| `deployment-checklist` | "deploy", "上线" | 上线前 5 道门禁 (凭证/测试/备份/安全/回滚) |
| `db-migration` | "schema", "改表" | 数据库安全变更 — 影响评估 + 迁移 + 回滚 |
| `visual-design` | "UI", "页面", "样式" | 视觉规范一致性 — 先读 DESIGN.md 再写代码 |

通用编码技能（brainstorming/TDD/code-review 等）由 superpowers 技能体系提供。

## MCP 数据源

### MCP 服务器状态

| 服务器 | 状态 | 工具数 | 说明 |
|--------|------|--------|------|
| `yfinance` | ✅ 正常 | ~30+ | Yahoo Finance 美股数据 (2026-06-30 验证通过) |
| `finance` | ✅ 正常 | 11 | 多源聚合 + 组合追踪 (需 ALPHA_VANTAGE_API_KEY) |
| `stock-scanner` | ✅ 正常 | 66 | **最全面** — 含 TradingView/Finnhub/CoinGecko/SEC EDGAR/Options/Reddit |
| `coingecko` | ⚠️ 待验证 | ~13 | 更新为 `@coingecko/coingecko-mcp`，stock-scanner 已内置冗余 |
| `fred` | ✅ 正常 | ~10 | FRED 美联储宏观数据 (2026-07-01 验证: CPI/利率/就业均正常) |
| `cn-finance` | ❌ 不可用 | 0 | PyPI 包不存在 (2026-06-30)。回退: stock-scanner TradingView SH/SZ 交易所扫描 |
| `sec-edgar` | ⚠️ 待验证 | ~5 | SEC 深度申报，stock-scanner 已有 edgar_* 工具覆盖 |
| `crypto-trade` | ⚠️ 需 Key | ~10 | 需 BINANCE_API_KEY + BINANCE_SECRET_KEY |

### Tier 1 — 已配置 (无需 API Key)
- **yfinance** — 美股行情/财报/期权 (uvx) ✅
- **stock-scanner** — 65工具: 行情/技术面/SEC/期权/Crypto/Reddit (npx) ✅
- **coingecko** — 加密货币 13工具 (npx) ⚠️ 与 stock-scanner 内置 CoinGecko 工具冗余
- **cn-finance** — A股/港股 42工具 (uvx) ❌ 包未发布

### Tier 2 — 进阶 (需免费 API Key)
- **fred** — 美联储 80万+ 宏观指标 (需 FRED_API_KEY)
- **finance** — 多源聚合 + 组合追踪 (需 ALPHA_VANTAGE_API_KEY)

### Tier 3 — 执行层 (需券商账户)
- **sec-edgar** — SEC 深度申报分析 (uvx) ⚠️ 与 stock-scanner edgar_* 工具重叠
- **crypto-trade** — CCXT 21+交易所 (需交易所 API Key)

## 环境配置

完整 API key 清单见 `.claude/memory/credential-architecture.md`（23 个 key，分 LLM/推送/行情/数据源/基础设施 5 类）。`.env` 是唯一配置入口。

## 🔐 凭证架构

- **唯一真相来源**: `.env`，全部 23 个 key 的完整清单见 `.claude/memory/credential-architecture.md`
- **LLM 供应商**: DeepSeek (唯一，`.env` + `settings.json` 均配置)
- **同步**: 编辑 `.env` 后运行 `python news-monitor/scripts/sync_env_to_settings.py`
- **自动检查**: SessionStart hook → `verify_env.py`（凭证完整性 + API 连通性）
- **备份恢复**: `ls .claude/backups/state/` → `cp <latest>/.env .env`

### 数据回退策略

当某个 MCP 服务器不可用时，技能会自动使用回退数据源：

| 不可用服务器 | 回退方案 |
|-------------|---------|
| `cn-finance` | stock-scanner `tradingview_scan` + SHA/SHE 交易所过滤 |
| `fred` | stock-scanner `sentiment_fear_greed` + WebSearch 宏观新闻 |
| `coingecko` | stock-scanner 内置 `coingecko_*` 工具 (crypto_quote/scan/technicals) |
| `sec-edgar` | stock-scanner 内置 `edgar_*` 工具 |

## Git

项目已初始化 Git 仓库。分支策略：
- `main` — 稳定配置
- 功能分支命名: `feature/<name>` 或 `fix/<name>`
- 提交信息格式: `[Phase] 简短描述`

## 自动化调度

### Cron 定时任务

项目配置了两个 durable cron 任务（需在 Claude Code 会话中手动注册一次）：

```bash
# 工作日早盘简报 — 北京时间 20:57 (美东 8:57 AM)
/cron 57 8 * * 1-5 /daily-briefing: full pre-market briefing

# 周六投资组合深度审查 — 北京时间 22:03 (美东 10:03 AM)
/cron 3 10 * * 6 /portfolio-management: deep portfolio review
```

注册后任务会自动持久化到 `.claude/scheduled_tasks.json`，跨会话存活（7天自动过期，每周续期）。

### Hooks (自动触发)

| 事件 | 触发条件 | 行为 |
|------|----------|------|
| `SessionStart` | 每次会话启动 | 📋 自动展示 HISTORY.md 上次操作摘要 + 记录 session.log |
| `PreToolUse` | 保存投资论点时 | 审计日志记录 |
| `PostToolUse` | 保存投资论点后 | 提醒更新简报 |

### 实时监控模式 (可选)

```bash
# 每5分钟快速简报更新
/loop 5m /daily-briefing --quick
```

## 缓存策略

所有 MCP API 响应遵循 `config/cache-policy.json` 中定义的 TTL 策略：

| 数据类型 | TTL | 说明 |
|----------|-----|------|
| 实时行情 | 5 分钟 | 盘中价格快速变化 |
| 日线 OHLCV | 4 小时 | 收盘后不变 |
| 历史数据 | 24 小时 | 基本面不变 |
| SEC 申报 | 7 天 | 季度更新 |
| 期权链 | 15 分钟 | 盘中活跃交易 |
| 情绪数据 | 1 小时 | Reddit 热度变化 |

缓存文件存储在 `data/cache/<tool>/<args-hash>.json`，技能执行前检查时间戳决定是否重取。

## 使用示例

```
/stock-research: 分析 NVDA 当前的投资价值
/quant-strategy: 对沪深300成分股做一个20日动量策略回测
/portfolio-management: 审查我的组合 [腾讯30%, 茅台25%, AAPL 25%, BTC 20%]
/daily-briefing: 生成今日早报
```

## 风险声明

⚠️ 所有输出仅供教育和研究目的，不构成投资建议。
策略信号需经人工审核确认后方可执行。
