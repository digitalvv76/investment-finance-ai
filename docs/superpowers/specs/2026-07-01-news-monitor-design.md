# 财经新闻 24/7 监控系统 — 设计规格书

> 状态: 设计完成 · 待用户审阅 · 2026-07-01

---

## 一、架构总览

```
┌─────────────────────────────────────────────────┐
│                  推送层                          │
│    Telegram Bot (推送 + 反馈 + 指令)              │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│              智能分析引擎                         │
│   ⚡ 快速通道 (规则, <5s)                         │
│   🧠 深度通道 (LLM, 1-5min)                      │
│   📚 学习引擎 (反馈→调权→自适应)                   │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│              数据采集层                           │
│   RSS聚合 · API接入 · Playwright定向抓取          │
└─────────────────────────────────────────────────┘
```

三层解耦。采集层只管拿数据，分析层做智能加工，推送层负责精准投递。学习引擎横跨分析和推送层。

---

## 二、数据源与采集策略

### 2.1 源分类

| 层级 | 方式 | 来源 |
|------|------|------|
| Tier 1 | RSS/API | Yahoo Finance, CNBC, MarketWatch, Reuters, Seeking Alpha, Investing.com, FRED, SEC EDGAR |
| Tier 2 | Playwright | Bloomberg, CNBC Pro, ZeroHedge, 指定 Twitter/X 账号 |
| Tier 3 | LLM 摘要 | 反爬极强的少数页面，Playwright 截图 → 多模态提取 |

### 2.2 采集频率

```
工作日 (周一 00:00 ET → 周五 20:00 ET — 覆盖盘前/盘中/盘后/夜盘):
  1分钟层: CNBC Breaking News, Bloomberg Markets 头条, ForexFactory, SEC 8-K,
           Twitter/X 核心账号, Federal Reserve 新闻发布
  5分钟层: 其余 Tier 2 源, Reuters RSS
  15分钟层: 其余 Tier 1 RSS 源
  30分钟层: 深度分析源

周末 + 交易所节假日:
  1分钟层 → 降为 15分钟
  5分钟层 → 降为 30分钟
  15/30分钟层 → 降为 1小时
  加密/宏观源 → 维持原频 (24/7市场)
```

### 2.3 1分钟层优化
- 增量检测：先 HEAD 请求判断是否有新内容，无更新则跳过
- Adaptive 降频：连续 N 次无新内容自动拉长间隔
- 交易所日历自动同步（NYSE/NASDAQ 年度交易日历）

---

## 三、双通道分析引擎

### 3.1 ⚡ 快速通道 — "发生了什么"

规则引擎，纯检测不解读，捕获到推送 < 5 秒。

**触发规则（满足任一即推送）：**

| 规则 | 说明 |
|------|------|
| 🔴 持仓命中 | 标题含持仓/关注列表 ticker |
| 🟠 宏观警报 | 标题命中核心宏观关键词 (CPI, Fed, rate, inflation...) |
| 🟡 高权源突发 | Bloomberg/Reuters/CNBC Breaking 标签 |
| 🔵 多源共振 | 3+ 源 5 分钟内报道同一事件 |

**推送格式：**
```
🔔 NVDA · Bloomberg
Nvidia cuts Q3 revenue guidance amid export restrictions
🔗 https://bloomberg.com/...
```

### 3.2 🧠 深度通道 — "意味着什么"

快速推送后自动进入。LLM 按需调用。

| 新闻等级 | LLM 调用策略 |
|----------|-------------|
| 紧急 (≥0.7) | ✅ 自动调用 |
| 重要 (0.4-0.69) | ⚡ 你在 Telegram 点「展开分析」才调用 |
| 一般 (<0.4) | ❌ 不调用，仅存档 |

**推送格式：**
```
📊 分析 · NVDA

市场冲击: 高 | 方向: 🔴 Bearish
关联持仓: NVDA (权重 8%) · SMH (板块 ETF)
情感分: -0.72 (强烈负面)

影响分析:
• NVDA 盘后可能下跌 5-8%
• 半导体板块或受联动拖累

AI 短评:
[LLM 生成的 3 句话解读，结合宏观和基本面]
```

### 3.3 分析管道工序

```
工序1: 实体提取 → 股票代码 (正则+词库) + 公司名 (spacy NER) + 人物 (词库) + 指标 (词库)
工序2: 市场关联 → 持仓/关注列表命中映射
工序3: 情感评分 → 5档 (🟢Bullish / 🟡Cautiously Bullish / ⚪Neutral / 🟠Cautiously Bearish / 🔴Bearish)
工序4: 优先级 = 源权威×0.3 + 市场冲击×0.3 + 持仓关联×0.2 + 时效衰减×0.1 + 情感极端度×0.1
工序5: 去重聚类 → URL指纹 + 标题相似度 + 事件线串联
```

---

## 四、持续学习引擎

### 4.1 四个维度

| 维度 | 学习内容 | 方法 |
|------|----------|------|
| 源偏好 | 哪些源打开率高 | 统计各源推送打开率，调高打开率高的权重 |
| 主题偏好 | 关心半导体还是宏观利率 | 分析 👍 新闻的实体/板块分布 |
| 阈值自适应 | 推送太多→收紧，错过→放宽 | 监控频率+反馈，PID 动态调整 |
| 个人词典 | 哪些词重要/噪音 | 👍 新闻高频词加入个人关键词库 |

### 4.2 反馈采集

| 环节 | 方式 | 信号 |
|------|------|------|
| 快速推送 | 👍 / 👎 / 已读时间 | 源偏好、主题偏好 |
| 深度分析 | 展开/忽略/分享 | 分析深度需求 |
| Telegram 指令 | `/mute` `/boost` | 显式偏好（权重最高） |
| 日报反馈 | 满意度 | 推送阈值调整 |

### 4.3 学习节奏
- 即时：`/mute` `/boost` 立即生效
- 小时级：单次 👍👎 微调 (+0.01~+0.05)
- 日级：前日打开率统计批量调优
- 周级：完整偏好画像重建

### 4.4 透明度
- `/prefs` 查看当前偏好权重
- `/prefs reset` 重置某个维度
- `/prefs export` 导出配置
- 全部本地存储，不上传

---

## 五、技术栈

| 层 | 组件 | 用途 |
|----|------|------|
| 采集 | `feedparser` | RSS 解析 |
| 采集 | `playwright` | Tier 2 浏览器抓取 |
| 采集 | `aiohttp` | 异步 HTTP |
| 采集 | `schedule` | 时间调度 |
| 分析 | `spacy (en_core_web_sm)` | 实体提取 |
| 分析 | `vaderSentiment` | 规则情感评分 |
| 分析 | `Anthropic API / OpenAI` | 深度通道 LLM |
| 分析 | `sentence-transformers` | 文本相似度去重 |
| 存储 | `SQLite` | 主存储 |
| 存储 | `ChromaDB` | 向量存储 |
| 推送 | `python-telegram-bot` | Telegram Bot |
| 已有 | FRED API, SEC EDGAR, Alpha Vantage | 宏观/申报触发 |

---

## 六、部署方案

### Phase 1：本地 Windows
- `nssm` 注册为 Windows 服务，开机自启 + 崩溃重启
- Telegram Bot polling 模式（无需公网 IP）
- 数据本地 SQLite + ChromaDB

### Phase 2：云 VPS
- Docker Compose 一键部署
- Hetzner €4.5/mo 或 RackNerd $2.5/mo
- 迁移：复制 data/ + .env → docker compose up -d

---

## 七、带验收门的开发路线图

```
Sprint 1           Sprint 2           Sprint 3           Sprint 4
[采集+Bot]    →   [分析引擎]     →   [学习引擎]     →   [加固+迁移]
  Day 1-3           Day 4-6            Day 7-8            Day 9-10
     │                  │                  │                  │
     ▼                  ▼                  ▼                  ▼
  Gate 1              Gate 2              Gate 3              Gate 4
```

### Gate 1 · 采集层 + Bot 骨架 (Day 3)
- [ ] `python main.py` 启动，Telegram `/status` 返回正常
- [ ] RSS 采集器返回 ≥5 个源，无报错
- [ ] Playwright 抓取 Bloomberg/CNBC 头条成功
- [ ] 1分钟心跳层运行，日志显示增量检测正常
- [ ] 交易所日历正确区分工作日/周末/节假日
- [ ] 手工触发测试新闻，Telegram 收到极简推送

### Gate 2 · 分析引擎 (Day 6)
- [ ] NER 正确提取 NVDA/AAPL 等代码
- [ ] 情感评分 10 条已知样本准确率 ≥ 80%
- [ ] 持仓命中新闻自动标注关联 ticker
- [ ] 紧急级新闻自动调 LLM，深度解读返回格式正确
- [ ] 重要级新闻 Telegram 点「分析」→ 2 分钟内返回
- [ ] 同一事件多源报道正确聚类为一条事件线
- [ ] 端到端：Bloomberg 突发 → <5s 快讯 → 深度解读

### Gate 3 · 学习引擎 + 交互 (Day 8)
- [ ] 👍👎 按钮正确回传且写入数据库
- [ ] 连续给 NVDA 新闻 3 👍，NVDA 权重可观测上升
- [ ] `/filter add TSLA` 后 TSLA 新闻开始推送
- [ ] `/mute AAPL 2h` 后 AAPL 新闻 2h 内不推送
- [ ] `/prefs` 正确展示当前偏好权重
- [ ] 日报生成并推送，内容覆盖当天关键新闻

### Gate 4 · 生产加固 (Day 10)
- [ ] Windows 重启后 nssm 服务自动拉起
- [ ] 日志轮转正常
- [ ] 连续运行 2 小时无内存泄漏
- [ ] docker-compose.yml 一键启动成功
- [ ] 回归测试：Gate 1-3 全部验收项再次通过
- [ ] VPS 迁移文档按步骤可复现

**规则：当前 Gate 未通过，不得进入下一 Sprint。**

---

## 八、Telegram Bot 指令集

| 指令 | 功能 |
|------|------|
| `/status` | 系统运行状态 |
| `/filter add <ticker>` | 添加关注股票 |
| `/filter remove <ticker>` | 移除关注股票 |
| `/alert-level <high\|normal\|low>` | 调整推送敏感度 |
| `/mute <ticker> <duration>` | 静默某股票一段时间 |
| `/boost <keyword>` | 提升某关键词权重 |
| `/prefs` | 查看当前偏好 |
| `/prefs reset <dimension>` | 重置某维度 |
| `/prefs export` | 导出偏好配置 |
| `/daily` | 即时生成日报 |
| `/analyze <url>` | 手动提交一篇新闻做深度分析 |

---

---

## 九、项目目录结构

```
news-monitor/
├── main.py                    # 入口，启动所有服务
├── config/
│   ├── settings.yaml          # 全局配置（频率、阈值、API keys）
│   ├── sources.yaml           # 数据源定义（RSS URL / Playwright selector）
│   └── keywords.yaml          # 宏观关键词库 + 持仓映射
├── collector/
│   ├── scheduler.py           # 主调度器（四层频率 + 交易日历）
│   ├── rss_fetcher.py         # RSS/Atom 抓取
│   ├── playwright_fetcher.py  # 浏览器定向抓取
│   ├── api_fetcher.py         # FRED/SEC/Alpha Vantage 触发器
│   └── exchange_calendar.py   # NYSE/NASDAQ 交易日历
├── engine/
│   ├── fast_lane.py           # 快速通道：规则引擎
│   ├── deep_lane.py           # 深度通道：NER + 情感 + LLM
│   ├── entity_extractor.py    # 实体提取 (spacy + regex)
│   ├── sentiment.py           # 情感评分 (VADER + 金融词典)
│   ├── priority.py            # 优先级计算
│   ├── dedup.py               # 去重聚类
│   └── learner.py             # 学习引擎
├── storage/
│   ├── database.py            # SQLite CRUD
│   ├── vector_store.py        # ChromaDB 管理
│   └── migrations.py          # Schema 迁移
├── bot/
│   ├── telegram_bot.py        # Bot 主逻辑
│   ├── handlers.py            # 指令处理
│   └── formatters.py          # 推送格式化
├── data/                      # 运行时数据
│   ├── news.db                # SQLite
│   └── chroma/                # ChromaDB 向量
├── logs/                      # 日志
├── tests/                     # 测试
└── docker/                    # Docker 部署文件
    ├── Dockerfile
    └── docker-compose.yml
```

### 与现有项目集成
- 持仓/关注列表从 `.claude/memory/portfolio-state.md` 和 `.claude/memory/watchlist-state.md` 读取
- 已有 API Keys: `FRED_API_KEY`, `ALPHA_VANTAGE_API_KEY` 复用
- 宏观状态参考 `.claude/memory/macro-state.md`

---

*本设计共 9 部分，经用户逐部分审阅确认。待用户批准后进入实现计划阶段。*
