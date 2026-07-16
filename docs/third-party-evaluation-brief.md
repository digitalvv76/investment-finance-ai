# Investment Finance AI — 第三方评估方案

> 本文档为外部 AI 开发专家评估准备。不含凭证和敏感数据。

---

## 一、系统概要

### 定位

个人投资者使用的全自动财经情报系统。从 46 个全球数据源采集新闻 → AI 评估 → Telegram/Pushover 推送。阿里云 ECS 单机部署，7×24 运行，服务 1 人。

### 核心价值

用户不看盘、不刷新闻。系统代替用户完成"信息采集→筛选→评估→推送"全链路，最终用户只在手机和 TG 上收结论。

### 规模

| 指标 | 数值 |
|------|------|
| 日处理新闻量 | 200-500 条 |
| 日推送量 | 20-80 条 TG + 1-5 条手机 |
| 代码量 | 25,000 行源码 + 8,300 行测试 (639 个测试函数) |
| 开发周期 | 16 天 (2026-07-01 至今)，300 次提交 |
| 开发人员 | 1 人（用户）+ AI（Claude Code） |

---

## 二、技术架构

### 2.1 物理拓扑

```
Vercel (class1-cyan.vercel.app)
  ├── 静态首页 + 仪表板
  └── /api/* → ECS:8080 (HTTPS 代理)

阿里云 ECS 4C8G (47.76.50.77)
  ├── Docker: news-monitor (主容器, 3GB)
  │   ├── main.py — 总调度 (asyncio 事件循环)
  │   ├── collector/ — 17 个采集器 (RSS/API/Playwright)
  │   ├── pipeline/ — 6 阶段管道 (采集→宏观→筛选→评估→分发→深析)
  │   ├── engine/ — 24 个核心模块 (评估/AI/聚类/预警)
  │   ├── bot/ — Telegram Bot (python-telegram-bot)
  │   ├── web/ — Quart Web 服务器 (:8080)
  │   └── storage/ — SQLite + ChromaDB
  └── Futu OpenD (:11111) — 富途行情网关 (systemd 自启)
```

### 2.2 管道流程

```
Ingest → Macro → Screen → Evaluate → Dispatch → Deep
(去重)   (宏观)   (筛选)   (评估)     (分发)     (深析)
```

| 阶段 | 功能 | 核心组件 | 耗时 |
|------|------|----------|:---:|
| **Ingest** | URL/语义去重、DB 写入、向量索引 | DedupManager + ChromaDB | <2s |
| **Macro** | 宏观新闻识别（白名单匹配+LLM评估） | MacroAgent | 5-15s |
| **Screen** | 实体提取、优先级打分、内容质量过滤 | FastLane 规则引擎 | <1s |
| **Evaluate** | 事件驱动评估(Path A) + LLM 影响评估(Path B) | EventDrivenEvaluator + ImpactEvaluator | 3-20s |
| **Dispatch** | 多渠道分发（Pushover/TG/Web）、手机去重 | DispatchStage | <1s |
| **Deep** | 异步 LLM 深度分析（含实时行情） | DeepLane (fire-and-forget) | 30-120s |

### 2.3 数据存储

| 存储 | 用途 | 规模 |
|------|------|------|
| SQLite (`news.db`) | 新闻、资金流、偏好、评估记录 | 11 张表 |
| ChromaDB | 语义去重向量索引 | 与新闻量同步增长 |

### 2.4 外部依赖

| 服务 | 用途 | 必要性 |
|------|------|:---:|
| **DeepSeek API** (deepseek-chat) | 主 LLM：评估+分析+翻译 | 核心 |
| **Anthropic API** (claude-fable-5) | 备用 LLM：深度分析 | 可选 |
| **Futu OpenD** | 美股行情、资金流、新闻搜索 | 重要 |
| **Pushover** | 手机推送 | 重要 |
| **Telegram Bot API** | TG 推送 + 交互 | 核心 |
| **yfinance** | 美股历史价格、基本面 | 辅助 |
| **spaCy** (en_core_web_sm) | 实体提取 | 辅助 |
| **sentence-transformers** (all-MiniLM-L6-v2) | 向量编码（去重） | 辅助 |
| **ChromaDB** | 向量存储 | 辅助 |
| **Playwright** (Chromium) | JS 渲染页面爬虫 | 辅助 |

### 2.5 并发任务

单 `asyncio` 事件循环内运行 9 个并发任务：主调度、TG Bot、Web 服务器、影响收集、事件升级、资金流、行情快照、看门狗、统计刷新。

---

## 三、关键设计决策

### 3.1 双通道推送

| | Pushover（手机） | Telegram |
|------|:---:|:---:|
| 推送门槛 | 极高（关注股+宏观≥85） | 低（得分≥0.22） |
| 频率 | 几天一条 | 每天几十条 |
| 目的 | 紧急打断 | 信息流 |

### 3.2 双重评估器

- **FastLane（规则引擎）**：毫秒级处理 90% 新闻，不耗 LLM token
- **DeepLane（LLM）**：仅高分/高价值新闻进入 LLM 深析

### 3.3 宏观独立通道 (MacroAgent)

CPI/FOMC/NFP 等宏观数据不走常规管道。白名单匹配 → Tier(A/B/C) × 偏离度(轻微/显著/极端) 矩阵评估 → 独立分发。

### 3.4 资金流信号

富途 OpenD 拉取机构/散户资金流数据 → 5 法则量价背离检测 → LLM 深度分析 → 极端信号推手机。

### 3.5 单 asyncio 事件循环

所有任务共享一个事件循环。优势是数据流简单、无进程间通信。代价是任一组件阻塞会拖垮全局——已发生过两次生产事故（采集器挂起、LLM API 死锁），已通过三层超时防护缓解。

---

## 四、生产事故记录

16 天内 5 次生产级故障，均已修复：

| # | 事故 | 根因 | 类型 |
|---|------|------|------|
| 1 | 采集器静默停摆 1h | `asyncio.gather` 无超时，Playwright hang | 并发安全 |
| 2 | 调度器回调死锁 | LLM API TCP 挂起，SDK 超时无效 | 网络韧性 |
| 3 | ECS 磁盘 IOPS 过载 | Docker + Chromium + ML 模型超 ESSD 上限 | 资源规划 |
| 4 | ECS CPU 饱和 | Chrome 僵尸进程泄漏（295 进程） | 资源泄漏 |
| 5 | 误删生产容器 | Docker compose down 没加 service 过滤 | 部署脚本 |

---

## 五、代码债清单（未修复）

| 债项 | 影响 | 严重度 |
|------|------|:---:|
| `captured_at`/`created_at` 时区不一致（本地时间 vs UTC） | 时间窗口查询可能丢数据 | 🔴 |
| `ticker_hint` 不入库（仅内存） | 历史分析需重跑 LLM，阻塞训练管道 | 🟡 |
| Prompt 版本漂移 | 历史评估无法复现 | 🟡 |
| `__manifest__.json` 可能偏离实际 | 测试依赖追踪断裂 | 🟢 |
| Playwright 长时间运行资源泄漏风险 | >24h 可能耗尽 fd | 🟢 |

---

## 六、评估维度

请专家从以下维度评估系统：

### A. 架构 (Architecture)

1. 单 asyncio 事件循环 vs 多进程/微服务：当前选择是否合理？什么情况下需要演进？
2. 管道模式 (Pipeline Pattern) 的设计：6 阶段划分是否合理？阶段间耦合度如何？
3. SQLite 作为主存储：什么量级需要迁移到 PostgreSQL/MySQL？
4. Vercel 代理模式：HTTPS→HTTP 转发是否是最佳实践？

### B. 可靠性 (Reliability)

1. 5 次生产事故的根因是否被充分修复？还有哪些类似风险？
2. 超时防护策略（三层 asyncio.wait_for）是否充分？
3. 当前有哪些单点故障（SPOF）？
4. 健康检查 /health 仅验证进程存活——应增加哪些探活维度？

### C. 代码质量 (Code Quality)

1. 25,000 行/147 文件 — 模块划分是否合理？最大的文件 (deep_lane.py 1,158 行) 是否需要拆分？
2. 639 个测试 — 覆盖率是否充分？关键路径（推送/资金流信号/去重）是否有测试覆盖？
3. 编码规范：模块间 import 是否存在循环依赖？TYPE_CHECKING 的使用是否合理？
4. 配置管理：6 个 YAML/JSON 配置文件 + .env + settings.json — 是否过于分散？

### D. LLM 使用 (LLM Usage)

1. DeepSeek 作为唯一 LLM 供应商：是否存在单点风险？是否需要备选方案？
2. Prompt 工程：6 个 prompt 模板的质量如何？（可提供脱敏版本）
3. LLM 评估的一致性：同一新闻多次评估结果是否稳定？
4. Token 消耗：日均 token 量是否可控？

### E. 运维 (Operations)

1. 部署流程 (deploy-main.sh)：回滚机制是否可靠？
2. 监控覆盖：UptimeRobot + 看门狗 + Docker healthcheck — 是否有盲区？
3. 日志策略：json-file 10MB×3 是否足够排查问题？
4. 单机部署的风险：是否需要备份/灾备方案？

### F. 功能完备性 (Feature Completeness)

1. 资金流信号 V2.1（5 法则 + LLM 分析）：算法是否合理？
2. MacroAgent 宏观评估：Tier × Deviation 矩阵是否科学？
3. 去重策略（URL + hash + Jaccard + 语义 4 层）：是否过度？是否误杀？
4. 手机推送门槛（仅关注股+宏观≥85）：规则是否合理？

---

## 七、评估产出要求

请专家输出：

1. **总体评分**（1-10，附理由）
2. **Top 3 最高风险**：如果不修，最可能出问题的地方
3. **Top 3 改进建议**：投入产出比最高的优化
4. **架构演进建议**：如果系统要服务 10 人/100 人，需要改什么
5. **一句话总结**

---

## 附录

### A. 目录结构

```
class1/
├── news-monitor/          # 主项目
│   ├── collector/         # 17 采集器 (4,300 行)
│   ├── engine/            # 24 核心模块 (9,800 行)
│   ├── pipeline/          # 6 管道阶段 (2,100 行)
│   ├── bot/               # TG Bot (1,700 行)
│   ├── storage/           # SQLite + ChromaDB (1,600 行)
│   ├── web/               # Web 面板 (1,500 行)
│   ├── scripts/           # 25 工具脚本
│   ├── config/prompts/    # 6 个 LLM Prompt (746 行)
│   └── tests/             # 54 测试文件, 639 测试函数 (8,300 行)
├── config/                # 全局配置
├── data/                  # 持久化数据
├── docs/                  # 文档 + Spec
├── deploy-main.sh         # 生产部署脚本
├── .env                   # 凭证 (23 个 Key)
└── CLAUDE.md              # AI Agent 行为准则
```

### B. 依赖清单 (requirements.txt)

```
anthropic, openai, spacy, sentence-transformers, chromadb,
playwright, aiohttp, yfinance, futu-api, python-telegram-bot,
feedparser, schedule, pyyaml, python-dotenv, vaderSentiment,
pytest, pytest-asyncio, pytest-mock
```

### C. 关键参考文件

| 文件 | 内容 |
|------|------|
| `CLAUDE.md` | AI Agent 行为准则 + 角色分工 |
| `.claude/SESSION.md` | 当前状态 + 待办 + 踩坑 |
| `HISTORY.md` | 逐会话操作历史 |
| `.claude/TROUBLESHOOTING.md` | 22 个踩坑记录 |
| `LESSONS.md` | 经验教训汇总 |
| `COLLAB-PROTOCOL.md` | V1/V2 协作协议 |
| `docs/superpowers/specs/` | 所有功能 Spec |
