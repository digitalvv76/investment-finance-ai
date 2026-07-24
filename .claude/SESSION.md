# 当前工作状态

> 最后更新: 2026-07-24。管道停摆修复 + PID 200→1024 + autoheal 就位。

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
- 管道停摆诊断+修复：PID 200→1024 + autoheal cron
- ECS 容器完整重建

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
