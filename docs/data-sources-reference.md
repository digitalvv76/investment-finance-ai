# 数据源全量清单

> 最后更新: 2026-07-12 · 共 48 个数据源

---

## 一、RSS/Atom 新闻源（5 个 · 免费 · 实时）

| # | 名称 | 链接 | 内容 |
|---|------|------|------|
| 1 | CNBC Top News | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114` | 美股市场头条 |
| 2 | MarketWatch | `https://feeds.content.dowjones.io/public/rss/mw_topstories` | 市场综合新闻 |
| 3 | WSJ Markets | `https://feeds.a.dj.com/rss/RSSMarketsMain.xml` | 华尔街日报市场版 |
| 4 | Seeking Alpha | `https://seekingalpha.com/feed.xml` | 投资分析/观点 |
| 5 | CNBC Economy | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258` | 宏观经济新闻 |

**无需 API Key**

---

## 二、网页抓取源（4 个 · 免费 · 实时）

通过 Playwright 无头浏览器抓取，CSS 提取失败时自动切 VLM（Claude Haiku）视觉识别兜底。

| # | 名称 | 网址 | 说明 |
|---|------|------|------|
| 6 | ZeroHedge | `https://www.zerohedge.com/` | 突发金融新闻/爆料 |
| 7 | CNBC 首页 | `https://www.cnbc.com/` | 美股头条 |
| 8 | 新浪财经 7×24 | `https://finance.sina.com.cn/7x24/` | A股/中概股实时快讯 |
| 9 | 华尔街见闻·全球 | `https://wallstreetcn.com/live/global` | 中文全球市场直播 |

**无需 API Key**（VLM 兜底需 `ANTHROPIC_API_KEY`，但日常走 CSS 提取不消耗）

---

## 三、中文财经 JSON API（6 个 · 免费）

| # | 名称 | 端点 | 内容 |
|---|------|------|------|
| 10 | 新浪财经 7×24 快讯 | `https://zhibo.sina.com.cn/api/zhibo/feed` | 综合实时快讯 |
| 11 | 华尔街见闻·全球 | `https://api.wallstreetcn.com/apiv1/content/lives?channel=global` | 全球宏观 |
| 12 | 华尔街见闻·美股 | `https://api.wallstreetcn.com/apiv1/content/lives?channel=us-stock` | 美股 |
| 13 | 华尔街见闻·外汇 | `https://api.wallstreetcn.com/apiv1/content/lives?channel=forex` | 外汇 |
| 14 | 华尔街见闻·加密货币 | `https://api.wallstreetcn.com/apiv1/content/lives?channel=crypto` | 加密货币 |
| 15 | 华尔街见闻·大宗商品 | `https://api.wallstreetcn.com/apiv1/content/lives?channel=commodities` | 大宗商品 |

**无需 API Key**

---

## 四、Twitter/X 账号（6 个 · 免费 · 需 Cookie）

通过已登录 X 账号的 `auth_token` Cookie 访问。

| # | 账号 | 说明 |
|---|------|------|
| 16 | [@Reuters](https://x.com/Reuters) | 路透社头条 |
| 17 | [@ReutersBusiness](https://x.com/ReutersBusiness) | 路透社金融 |
| 18 | [@ReutersWorld](https://x.com/ReutersWorld) | 路透社地缘/冲突/贸易 |
| 19 | [@Newsquawk](https://x.com/Newsquawk) | 实时财经事件解析 |
| 20 | [@SemiAnalysis](https://x.com/SemiAnalysis) | 半导体/AI 供应链深度研究 |
| 21 | [@bespokeinvest](https://x.com/bespokeinvest) | 宏观研究/图表 |

**需要**: `TWITTER_AUTH_TOKEN`（浏览器 F12 → Application → Cookies → x.com → auth_token）

---

## 五、REST API 数据源（4 个 · 部分需 Key）

| # | 名称 | 端点 | 频率 | 内容 | API Key |
|---|------|------|------|------|---------|
| 22 | SEC EDGAR 8-K | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom&count=20` | 30s | 上市公司重大事件申报 | **免费** |
| 23 | FRED 经济数据 | `https://api.stlouisfed.org/fred/` | 15min | GDP/CPI/PPI/非农/FOMC 等宏观指标 | `FRED_API_KEY`（免费申请） |
| 24 | Alpha Vantage | `https://www.alphavantage.co/query?function=NEWS_SENTIMENT` | 15min | 新闻+情绪评分（关注股 Top 2） | `ALPHA_VANTAGE_API_KEY`（免费申请） |
| 25 | Finnhub | `https://finnhub.io/api/v1/company-news` | 5min | 关注股逐条新闻（21 只全覆盖） | `FINNHUB_API_KEY`（免费申请） |

### API Key 免费申请地址
- FRED: https://fred.stlouisfed.org/docs/api/api_key.html
- Alpha Vantage: https://www.alphavantage.co/support/#api-key
- Finnhub: https://finnhub.io/register

---

## 六、MCP 服务器（Claude Code 插件 · 11 个）

### 6.1 核心在用（6 个）

| # | 服务器 | 工具数 | 提供内容 | API Key |
|---|--------|--------|----------|---------|
| 26 | **yfinance** | ~30 | 美股行情、OHLCV 历史、财报（利润表/资产负债表/现金流）、期权链、分析师评级、股东信息 | **免费** |
| 27 | **stock-scanner** | 66 | **最全面** — TradingView 行情/扫描/技术面 + Finnhub 实时报价 + CoinGecko 加密货币 + SEC EDGAR 申报/内幕交易/机构持仓 + 期权链/Greeks/做市商 + Reddit 情绪/热度 + FRED 宏观 + Frankfurter 汇率 + Fear & Greed 情绪指数 | **免费**（部分子工具复用环境变量中的 Finnhub/FRED Key） |
| 28 | **coingecko** | ~13 | 加密货币实时价/历史/搜索/热搜 | **免费** |
| 29 | **finance** | 11 | 公司基本面、多源聚合行情、市场概览、板块表现、技术指标、投资组合追踪 | `ALPHA_VANTAGE_API_KEY` |
| 30 | **fred** | ~10 | 美联储 80 万+ 宏观经济指标（CPI/利率/就业/PMI 等） | `FRED_API_KEY`（免费申请） |
| 31 | **anysearch** | - | 通用网页搜索 + URL 内容提取 | **免费** |

### 6.2 部分可用/冗余（2 个）

| # | 服务器 | 状态 |
|---|--------|------|
| 32 | **sec-edgar** | 与 stock-scanner 内置 edgar_* 工具功能重叠，按需使用 |
| 33 | **crypto-trade** | 需 `BINANCE_API_KEY` + `BINANCE_SECRET_KEY`（交易所实盘，未启用） |

### 6.3 不可用（1 个）

| # | 服务器 | 原因 | 替代方案 |
|---|--------|------|----------|
| 34 | **cn-finance** | PyPI 包未发布 | 用 stock-scanner TradingView SH/SZ 交易所扫描替代 |

### 6.4 工具类（2 个）

| # | 服务器 | 用途 |
|---|--------|------|
| 35 | **plugin:github:github** | GitHub 平台交互（Issues/PR/代码搜索） |
| 36 | **plugin:context7:context7** | 编程文档实时查询 |

---

## 七、LLM 服务（3 个）

| # | 提供商 | 模型 | 用途 | 注册地址 |
|---|--------|------|------|----------|
| 37 | DeepSeek | deepseek-chat | **主力**：深度分析、标题翻译、事件评估 | https://platform.deepseek.com/api_keys |
| 38 | Anthropic | Claude Haiku 4.5（VLM）+ Claude Opus 4.8（备用） | 网页视觉提取兜底 + 复杂推理备用 | https://console.anthropic.com/ |
| 39 | 智谱 AI (GLM) | GLM-5.1 | 对抗式核实（打破同模型盲点）+ 翻译/策展轻量任务 | https://open.bigmodel.cn/（国内）或 https://api.z.ai/（国际） |

---

## 八、推送通道（3 个）

| # | 服务 | 用途 | 注册地址 |
|---|------|------|----------|
| 40 | Telegram Bot API | 主力推送（分级：FLASH 警笛/CRITICAL/IMPORTANT/NOTABLE） | https://t.me/BotFather |
| 41 | Pushover | 手机紧急推送（仅 CRITICAL 及以上 → 警笛音效） | https://pushover.net/ |
| 42 | UptimeRobot | 外部存活监控 | https://uptimerobot.com/ |

---

## 九、本地数据（4 个）

| # | 名称 | 类型 | 说明 |
|---|------|------|------|
| 43 | SQLite | 嵌入式数据库 | 所有采集新闻、事件、状态持久化 |
| 44 | Chroma | 向量数据库 | 新闻语义去重 + 相似聚类 |
| 45 | Exchange Calendar | 离线日历 | NYSE/NASDAQ 2026 节假日 + 交易时段判断 |
| 46 | 训练案例集 | Markdown | 21 个历史案例（政府干预 + Jensen Huang 事件）用于 LLM 评估校准 |

---

## 汇总

| 类别 | 数量 | 需要 API Key |
|------|:---:|:---:|
| RSS/Atom 新闻源 | 5 | 0 |
| 网页抓取（Playwright） | 4 | 0 |
| 中文财经 JSON API | 6 | 0 |
| Twitter/X 账号 | 6 | 1（auth_token） |
| REST API | 4 | 3（均免费申请） |
| MCP 服务器 | 11 | 0（子工具复用 Key） |
| LLM 服务 | 3 | 3 |
| 推送通道 | 3 | 3 |
| 本地数据 | 4 | 0 |
| **合计** | **46** | **10 项 Key**（其中 5 项可免费申请） |
