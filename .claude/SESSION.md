# 当前工作状态

> 最后更新: 2026-07-17 关机同步。部署 geo-tier 权重 + Graham 审查，关闭 T01/T10。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | — |

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `6f8c032`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ⚠️ 单点
- **Futu OpenD**: systemd 自启，五合一 ✅
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动 ✅
- **资金流 DB**: 72 标的，每日 03:00 CST 备份 ✅
- **管线**: Ingest → Macro → Screen → Evaluate → Graham → Dispatch → Deep

## 📱 推送门槛
- **Geo-tier**: 非美宏观 ×0.25 基本不推（`446bf71`）
- **Graham 审查**: 5 问题清单降级/拦截噪音（`6f8c032`）
- **手机**: 战略规则 > 宏观≥92 > CRITICAL
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条
- **资金流**: 仅 STRONG 推送

## 📋 任务追踪

**集中在 `TASKS.md`**。本次会话：T01 关闭、T02 完成部署、T10 关闭。

当前活跃: [T02 已完成] [T03 待 V1 spec] [T14 待用户决策]

## ⚠️ 踩坑记录
- Geo-tier 对抗核实发现中文"中国"缺口 + U.S.功能词阻断，已修 (`091f7a0`)
- Graham 降级阈值：0-1 FAIL 维持 / 2 FAIL 静音 / 3+ FAIL 不推
- Graham fail open — 超时/API 错误透传
- K-line max_count=25 不足、Futu 截断最新日期
- 东财 eastmoney_fetcher 死代码
- MRAAY/SATS/PXD Futu 不支持

## 🔴 风险
- **DeepSeek 单点**: 宕机 = 管线全停
- **Graham 审查新增 ~30-50 LLM 调用/天**，增加 DeepSeek 依赖
