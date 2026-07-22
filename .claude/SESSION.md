# 当前工作状态

> 最后更新: 2026-07-22 关机。Google/SK Hynix/Samsung 财报监控已部署，三个 durable cron 待触发。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | — |

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `4146d73`)，健康 ✅
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
- `4146d73` docs: HISTORY.md 补录 6 个缺失提交
- `.claude/scheduled_tasks.json` 三个 durable cron 财报监控：
  - Google Q2 → 7/23 4:37am 北京时
  - Samsung Q2 → 7/23 9:07am 北京时
  - SK Hynix Q2 → 7/29 8:47am 北京时

## 📋 任务追踪

**集中在 `TASKS.md`**。T01/T02/T04/T07/T10 已完成。

当前活跃: [T03 待 V1 spec] [T14 待用户决策 — 推荐 B: 取消 v1-stable]

## ⚠️ 踩坑记录
- SK 海力士财报日：Investing.com 显示 7/22 是错的，官方 DART 披露 + SEC 6-K 确认为 7/29
- CronCreate durable=true 参数似乎未生效，需手动写入 scheduled_tasks.json

## 🔴 风险
- **DeepSeek 单点**: 宕机 = 管线全停
- **财报周**: Google 今晚 + Samsung 明天 + SK Hynix 7/29，市场波动大
