# 当前工作状态

> 最后更新: 2026-07-17 关机同步。5 提交，推送门槛+运维+流程+文档合入全部完成。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。V1 写完 spec 后在此列出。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | — |

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `f2e87ae`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ⚠️ 单点 (备: OpenAI key 可 10min 内切换)
- **Futu OpenD**: systemd 自启，行情+资金流+新闻+快照+板块五合一 ✅
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动，四通道正常 ✅
- **资金流 DB**: 72 标的，1451 行。每日 03:00 CST 备份 ✅
- **数据库备份**: cron 每日 03:00 CST，保留 7 天，含恢复验证 ✅

## 📱 推送门槛 (2026-07-17 部署)
- **手机**: 战略规则(STRATEGIC_*) > 宏观≥92 > CRITICAL。关注股 IMPORTANT → TG only
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条
- **资金流**: 仅 STRONG 推送 (STANDARD→skip)
- **去重**: 手机 24h，快照 extreme ±7%

## 📋 任务追踪

**所有任务集中管理在 `TASKS.md`**（本文件不再重复列举）。新任务产生时立即登记到 TASKS.md 对应分区。

当前活跃: [T01 资金流信号评估] [T14 v1-stable 去留] — 详见 TASKS.md

## ⚠️ 踩坑记录
- K-line max_count=25 不足，Futu 截断最新日期而非最旧
- 东财 eastmoney_fetcher 是死代码但测试仍在引用
- Docker 容器内读不到 .claude/memory/watchlist-state.md → settings.yaml 直配
- price_change_3d 已废弃但 _format_tg_message 仍在用 → 改为 cum_price_3d
- MRAAY (OTC)/SATS (未知)/PXD (已退市) Futu 不支持
- classify() auto-CRITICAL 路径是死代码 (evaluate.py 传 strategic_matches=None)
- 部署后推送频率靠感觉判断，无数据对比 → 已修复: deploy TG 通知带 24h 计数

## 🔴 风险
- **DeepSeek 单点**: 宕机 = 管线全停。备: OpenAI key 在 .env (注释)，10min 内可切换
