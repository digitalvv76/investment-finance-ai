# 当前工作状态

> 最后更新: 2026-08-03。Evaluate 并行化 + 模型迁移完成。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | — |

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `c8cff06`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一，v4-pro (核心评估) + v4-flash (噪音过滤)
- **Futu OpenD**: host 监听 11111 但容器连不上 ⚠️ (Docker bridge 问题)
- **Futu 新闻**: 熔断器生效 — pre-flight 快速跳过，不影响其他源
- **管线**: Ingest → Macro → Screen → Evaluate(5并发) → Graham → Dispatch → Deep ✅
- **Autoheal**: cron 每 2 分钟检查 ⚠️ 只检测 docker ps unhealthy 字符串
- **Docker HEALTHCHECK**: `curl localhost:8080/health` 每 60s

## 📱 推送门槛
- **Geo-tier**: 非美宏观 ×0.25 基本不推
- **Graham 审查**: 5 问题清单降级/拦截噪音
- **手机**: 战略规则 > 宏观≥92 > CRITICAL
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条

## 🔧 本会话完成
- `d5ead37` perf: EvaluateStage 并行化 — Semaphore(5) 并发 LLM，延迟 10-15min→~2min
- `c8cff06` feat: DeepSeek 模型迁移 deepseek-chat→v4-pro/flash — 旧 ID 7/24 已废弃
- 对抗式核实通过：`_clients` 无害竞态、SQLite WAL 安全、异常隔离正确
- 两次部署均 healthy

## ⚠️ 踩坑记录
- Futu SDK `OpenQuoteContext()` 内部重连循环 ~6s/次，无法从外部停止
- `asyncio.wait_for(to_thread)` 取消的是 await，不杀线程
- Docker HEALTHCHECK 用 8080（不是 8000）
- Autoheal 只检查 `docker ps` unhealthy 字符串，进程僵死不触发
- `deepseek-chat` 已于 2026-07-24 被 DeepSeek 废弃，迁移完成
