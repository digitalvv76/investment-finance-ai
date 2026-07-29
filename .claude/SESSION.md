# 当前工作状态

> 最后更新: 2026-07-29 晚。EventDrivenEvaluator LLM 超时 — 第 4 次管线中断根因修复。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | — |

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `7c9803f`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ⚠️ 单点
- **Futu OpenD**: systemd 自启，五合一 ✅（容器重启后需重连）
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动 ✅
- **Pushover**: 已验证送达 ✅
- **资金流 DB**: 72 标的，每日 03:00 CST 备份 ✅
- **管线**: Ingest → Macro → Screen → Evaluate → Graham → Dispatch → Deep ✅
- **管线隔离**: `asyncio.create_task` + `_pipeline_running` 锁 ✅
- **Autoheal**: cron 每 2 分钟检查，连续 3 次 unhealthy 自动重启 ✅
- **健康检查**: 新鲜度门禁 + 磁盘监控 + **零评估 DEGRADED 检测(新增)** ✅
- **Docker 清理**: 每周日 04:00 清理 7 天前镜像 (ECS cron) ✅
- **PID 限制**: 1024
- **磁盘**: ~56% used, ~15 GB free

## 📱 推送门槛
- **Geo-tier**: 非美宏观 ×0.25 基本不推
- **Graham 审查**: 5 问题清单降级/拦截噪音
- **手机**: 战略规则 > 宏观≥92 > CRITICAL
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条
- **资金流**: 仅 STRONG 推送

## 🔧 本会话新增
- `6050da7` fix: EventDrivenEvaluator._call_llm 加 asyncio.wait_for 超时 (30s)
  根因：只有 SDK timeout(20s) 不可靠，LLM 挂死时协程永久阻塞 → 管线卡在 Evaluate → 600s 超时
- `b74ed68` fix: 看门狗 evaluate_health 新增 "零评估+活跃采集" DEGRADED 检测
  修复前完全不看 hours_since_last_push（注释写 "for heartbeat, not alerting"）
- 管线恢复首周期：117 采集 → 21 Screen → 3 TG + 2 Pushover

## ⚠️ 踩坑记录
- 四个 LLM 调用组件中，EventDrivenEvaluator 是唯一没有 asyncio 超时的
- SDK timeout(httpx) 不覆盖所有挂死场景，asyncio.wait_for 是必须的第二层兜底
- asyncio.wait_for 取消不了 to_thread 里的线程 — 只防协程永久阻塞
- 看门狗设计者把 hours_since_last_push 排除在健康判断之外，盲区是 "采集正常但评估挂死"