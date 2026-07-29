# 当前工作状态

> 最后更新: 2026-07-29。管线反复中断根因修复 — 三重防线部署完成。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | — |

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `1291105`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ⚠️ 单点
- **Futu OpenD**: systemd 自启，五合一 ✅（容器重启后需重连）
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动 ✅
- **Pushover**: 系统日报已确认送达 ✅
- **资金流 DB**: 72 标的，每日 03:00 CST 备份 ✅
- **管线**: Ingest → Macro → Screen → Evaluate → Graham → Dispatch → Deep
- **管线隔离**: `asyncio.create_task` + `_pipeline_running` 锁，回调不阻塞调度器
- **Autoheal**: cron 每 2 分钟检查，连续 3 次 unhealthy 自动重启 ✅
- **健康检查**: 新鲜度门禁（>60min stale → degraded）+ 磁盘监控（>95% → degraded）
- **Docker 清理**: 每周日 04:00 清理 7 天前镜像 (ECS cron)
- **PID 限制**: 1024（从 200 上调）
- **磁盘**: 56.2% used, 15.3 GB free

## 📱 推送门槛
- **Geo-tier**: 非美宏观 ×0.25 基本不推
- **Graham 审查**: 5 问题清单降级/拦截噪音
- **手机**: 战略规则 > 宏观≥92 > CRITICAL
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条
- **资金流**: 仅 STRONG 推送

## 🔧 本会话新增
- `1291105` fix: 管线反复中断根因修复 — 三重防线
- 清理 ECS 磁盘 17.8GB（旧 rollback 镜像 50+ 个）
- 健康检查新鲜度门禁 + 磁盘监控 + 管线 task 隔离 + Docker 清理 cron
- 根因: 健康检查使用 stale 缓存 → Docker/autoheal 永远检测不到故障

## ⚠️ 踩坑记录
- 三次事故（PID/LLM超时/磁盘满）同一结果：事件循环阻塞 → 健康检查返回 stale "ok" → 无人知晓
- 磁盘满来自 Docker 镜像堆积（22.5GB），旧 rollback 镜像从未清理
- Docker `image prune` (不加 -a) 只清 dangling 镜像，回收很少；必须用 `-a` 清所有未使用镜像
- 健康检查必须校验数据新鲜度，不能只看 HTTP 200
