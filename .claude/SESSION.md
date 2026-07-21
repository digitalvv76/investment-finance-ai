# 当前工作状态

> 最后更新: 2026-07-21 关机。Futu v2.1 全量并发+ticker兜底上线，KTOS 漏报根因修复。对抗式核实铁律重申。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | — |

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `c46af29`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ⚠️ 单点
- **Futu OpenD**: systemd 自启，五合一 ✅
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动 ✅
- **资金流 DB**: 72 标的，每日 03:00 CST 备份 ✅
- **管线**: Ingest → Macro → Screen → Evaluate → Graham → Dispatch → Deep

## 📱 推送门槛
- **Geo-tier**: 非美宏观 ×0.25 基本不推
- **Graham 审查**: 5 问题清单降级/拦截噪音
- **手机**: 战略规则 > 宏观≥92 > CRITICAL
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条
- **资金流**: 仅 STRONG 推送

## 🔧 本会话新增
- **心率层收集器**: Chinese + RSS + Playwright + API + WebScraper + Futu + Finnhub（7 路并发）
- **Futu 关键词**: 75 只全量覆盖，16 关键词/轮 → 5.5min 全量
- **源权重**: 新浪财经 0.04→0.06，华尔街见闻·全球 0.06→0.08
- **延迟追踪**: dispatch 日志 `source=X latency=Ys`
- **实体提取**: TSMC/Nebius 英文→TSM+NBIS，台积电→TSM 中英文全链路
- **business_impact 因子**: 涨价(0.5-0.9) + 营收(0.6-0.9) + 利润(0.7-0.9) + 指引(0.6-0.8) + 合同(0.7-0.9) + 成本(0.5-0.7)，权重 0.15

## 📋 任务追踪

**集中在 `TASKS.md`**。T01/T02/T04/T07 已完成，T10 关闭。

当前活跃: [T03 待 V1 spec] [T14 待用户决策]

## ⚠️ 踩坑记录
- TSMC 涨价由 Nikkei Asia 英文独家首发，快过中文源 + Futu 轮询 → 多源管线优势已验证
- "raise chipmaking prices" 中间有词，子串匹配失败 → 加 regex 邻近词检测

## 🔴 风险
- **DeepSeek 单点**: 宕机 = 管线全停
- business_impact 新增约 20+ 关键词匹配，对评分影响轻微（max 不叠加）
