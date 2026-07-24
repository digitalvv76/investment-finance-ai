# 当前工作状态

> 最后更新: 2026-07-25。Dispatch 超时修复 (120→480s) + 管线全周期恢复。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | — |

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `8cdb675`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ⚠️ 单点
- **Futu OpenD**: systemd 自启，五合一 ✅（容器重启后需重连）
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动 ✅
- **Pushover**: 系统日报已确认送达 ✅
- **资金流 DB**: 72 标的，每日 03:00 CST 备份 ✅
- **管线**: Ingest → Macro → Screen → Evaluate → Graham → Dispatch → Deep
- **Autoheal**: cron 每 2 分钟检查，连续 3 次 unhealthy 自动重启 ✅
- **PID 限制**: 1024（从 200 上调）

## 📱 推送门槛
- **Geo-tier**: 非美宏观 ×0.25 基本不推
- **Graham 审查**: 5 问题清单降级/拦截噪音
- **手机**: 战略规则 > 宏观≥92 > CRITICAL
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条
- **资金流**: 仅 STRONG 推送

## 🔧 本会话新增
- Dispatch 超时诊断：根因是调度器 120s 回调超时，LLM 评价慢时掐断管线
- `178c2e9` fix: CALLBACK_TIMEOUT 120→480s，docker cp 热更新部署
- 管线异步化方案评审：结论是不值，过度工程
- 后续计划：插计时代码摸底 LLM 各阶段耗时，数据驱动设阶段超时

## ⚠️ 踩坑记录
- 调度器 `_notify_callbacks` 是单跑道阻塞式，采集和管线共享同一条跑道
- 管线不是每分钟都慢，是偶尔慢（~20% 周期），LLM 评价耗时波动是主因
- `SCREEN 日志有但 EVALUATE 无` = 管线在 Evaluate 前被超时掐断
- Docker build 在阿里云 ECS 上玩不了：Playwright CDN 被墙，只能 docker cp 热更新
- 管线异步化不做：SQLite 并发不安全 + 锁跳过=静默漏评, 比超时更难排查

## 📋 任务追踪

**集中在 `TASKS.md`**。当前活跃: [T14 待用户决策]

## ⚠️ 踩坑记录
- PID 200 不够：Playwright 浏览器 + Python async 轻松超 200 进程
- Docker `unless-stopped` 不响应 health check 失败，需外部 autoheal
- ECS Playwright CDN 不通：`docker build` 会卡在 `playwright install chromium`，需用 `--no-build` 或预装镜像
- 容器 `procReady not received` 时无法 exec，只能 restart

## 🔴 风险
- **DeepSeek 单点**: 宕机 = 管线全停
- **Futu OpenD 重连**: 容器重启后 5 通道需重建连接，当前超时中
