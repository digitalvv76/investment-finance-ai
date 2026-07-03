# Investment Finance AI Agent

Claude Code 驱动的全能型投资金融智能体，覆盖全球市场的股票研究、量化策略和投资组合管理。

🌐 **首页**: https://class1-cyan.vercel.app | 📂 **GitHub**: https://github.com/digitalvv76/investment-finance-ai | ⏰ **时钟**: https://class1-cyan.vercel.app/datetime

## 📋 首次响应规则 (最高优先级 ⚠️)

**这是本项目最重要的规则。每次新会话，你的第一条响应必须在做任何其他事情之前执行以下步骤：**

1. 读取 `HISTORY.md` 获取完整操作历史
2. 提取最近一次会话的所有操作记录（日期、任务、产出、关键发现）
3. **在第一条响应中主动向用户展示操作摘要** — 不需要等用户问
4. 此规则完成前，不得回答用户问题、不得执行任何操作

**格式要求：** 用简洁的分点列表展示上次会话做了什么、产出了什么、有什么关键发现。一行一条。

## 🔄 会话持久化

**每次会话必须遵循以下规则：**

1. ~~会话启动时~~ **→ 已由上方「首次响应规则」替代**，会话启动自动展示历史摘要
2. 会话进行中，将关键操作实时追加到 `HISTORY.md`（使用 Edit append 方式）
3. 会话结束前，确保本会话所有操作已写入 `HISTORY.md`
4. `HISTORY.md` 是跨会话的唯一真相来源 — 操作日志、部署信息、重要决策全部在此

**History.md 仅追加，不覆盖历史内容。**

## 项目结构

```
calss1/
├── .mcp.json              # MCP 服务器配置 (8个金融数据服务器)
├── .claude/
│   ├── settings.json      # 项目级配置 (env/permissions/hooks)
│   ├── memory/            # 跨技能状态共享
│   │   ├── portfolio-state.md
│   │   ├── watchlist-state.md
│   │   └── active-signals.md
│   └── skills/
│       ├── stock-research.md       # 个股深度研究
│       ├── quant-strategy.md       # 量化策略开发与回测
│       ├── portfolio-management.md # 投资组合管理
│       └── daily-briefing.md       # 每日市场简报
├── data/                   # 持久化数据
│   ├── watchlists/         # 关注列表
│   ├── portfolios/         # 持仓快照
│   ├── signals/            # 交易信号
│   ├── briefings/          # 简报归档
│   ├── reports/            # 研究报告
│   └── cache/              # API 缓存
├── config/                 # 可复用配置
│   ├── benchmarks.json     # 基准指数映射
│   ├── indicators.json     # 技术指标参数库
│   ├── cache-policy.json   # 缓存 TTL 策略
│   └── economic-calendar.json  # 经济事件日历
├── scripts/                # Python 工具脚本
│   ├── init_project.py     # 一键初始化
│   └── verify_mcp.py       # MCP 连通性检查
├── .env.example            # API Key 模板
├── .gitignore
└── CLAUDE.md              # 本文件
```

## 技能说明

| 技能 | 触发词 | 功能 |
|------|--------|------|
| stock-research | `/stock-research`, "分析", "research" | 多源个股深度分析 + 评级报告 |
| quant-strategy | `/quant-strategy`, "策略", "backtest", "signal" | 量化策略开发/回测/信号生成 |
| portfolio-management | `/portfolio-management`, "组合", "调仓", "risk" | 组合分析/风险评估/调仓建议 |
| daily-briefing | `/daily-briefing`, "早报", "日报", "briefing" | 每日市场概览 + 持仓更新 |
| db-migration | `/db-migration`, "schema", "migration", "改表" | 数据库安全变更 — 影响评估 + 迁移脚本 + 回滚 |
| deployment-checklist | `/deployment-checklist`, "deploy", "上线", "发布" | 上线前 5 道门禁检查 (凭证/测试/质量/安全/回滚) |
| visual-design | `/visual-design`, "UI", "页面", "前端", "样式" | 视觉规范一致性 — 先读 DESIGN.md 再写代码 |

## MCP 数据源

### MCP 服务器状态

| 服务器 | 状态 | 工具数 | 说明 |
|--------|------|--------|------|
| `yfinance` | ✅ 正常 | ~30+ | Yahoo Finance 美股数据 (2026-06-30 验证通过) |
| `finance` | ✅ 正常 | 11 | 多源聚合 + 组合追踪 (需 ALPHA_VANTAGE_API_KEY) |
| `stock-scanner` | ✅ 正常 | 45+ | **最全面** — 含 TradingView/CoinGecko/SEC EDGAR/Options/Reddit |
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

## 快速开始

1. 安装 Python 3.10+
2. 安装 Node.js 18+
3. 安装 uv: `pip install uv` 或 `winget install --id=astral-sh.uv`
4. 申请免费 API Keys (可选):
   - FRED: https://fred.stlouisfed.org/docs/api/api_key.html
   - Alpha Vantage: https://www.alphavantage.co/support/#api-key
5. 复制 `.env.example` 为 `.env` 并填入你的 API Keys
6. 运行 `python scripts/init_project.py` 初始化数据目录
7. 重启 Claude Code 或在会话中运行 `/hooks` 加载配置

## 环境配置

### API Keys

| 服务 | 环境变量 | 注册地址 | 必需 |
|------|----------|----------|------|
| FRED | `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | 推荐 |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | https://www.alphavantage.co/support/#api-key | 推荐 |
| Binance | `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` | Binance API 管理 | 可选 |

设置方式：
- **Windows**: `setx FRED_API_KEY "your_key_here"`
- **或在项目 `.env` 文件中直接填写**（.env 已 git-ignored）

## 🔐 凭证架构 (Credential Architecture)

**`.env` 是唯一真相来源。** 所有 Python 入口点通过 `python-dotenv` 自动加载。

### 凭证清单

| 环境变量 | 用途 | 必需 |
|----------|------|------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot 推送 | ✅ 是 |
| `DEEPSEEK_API_KEY` | LLM 深度分析 (主) | ✅ 是* |
| `ANTHROPIC_API_KEY` | LLM 深度分析 (备) | ✅ 是* |
| `PUSHOVER_APP_TOKEN` | 手机紧急推送 (警笛) | 推荐 |
| `PUSHOVER_USER_KEY` | Pushover 用户标识 | 推荐 |
| `FRED_API_KEY` | 美联储宏观数据 | 可选 |
| `ALPHA_VANTAGE_API_KEY` | 股票基本面 | 可选 |

*至少需要一个 LLM key

### 启动自动检查

每次会话启动自动运行（SessionStart hook）：

1. **`backup_state.py`** — 备份所有关键文件到 `.claude/backups/state/`
2. **`verify_env.py`** — 检查凭证完整性、.env ↔ settings.json 同步、API 连通性

### 手动同步 (.env → settings.json)

编辑 `.env` 后运行：
```bash
python news-monitor/scripts/sync_env_to_settings.py
```

### 恢复凭证

从备份恢复：
```bash
ls .claude/backups/state/           # 查看备份列表
cp .claude/backups/state/<latest>/.env .env
```

详见 `.claude/memory/credential-architecture.md`

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

## 脚本工具

| 脚本 | 用途 |
|------|------|
| `python scripts/init_project.py` | 一键初始化所有数据目录和模板文件 |
| `python scripts/verify_mcp.py` | MCP 服务器连通性烟雾测试 + API Key 检查 |

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
