# 当前工作状态

> 最后更新: 2026-07-31。TG 去重部署完成。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | — |

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `79826da`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ⚠️ 单点
- **Futu OpenD**: host 监听 11111 但容器连不上 ⚠️ (Docker bridge 问题)
- **Futu 新闻**: 熔断器生效 — pre-flight 快速跳过，不影响其他源
- **TG 推送**: 已恢复（RKLB/SpaceX/Lam Research/Robinhood）
- **管线**: Ingest → Macro → Screen → Evaluate → Graham → Dispatch → Deep ✅
- **Autoheal**: cron 每 2 分钟检查 ⚠️ 只检测 docker ps unhealthy 字符串，不覆盖僵死进程
- **Docker HEALTHCHECK**: `curl localhost:8080/health` 每 60s, 3 次失败 → unhealthy
- **Docker 清理**: 每周日 04:00

## 📱 推送门槛
- **Geo-tier**: 非美宏观 ×0.25 基本不推
- **Graham 审查**: 5 问题清单降级/拦截噪音
- **手机**: 战略规则 > 宏观≥92 > CRITICAL
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条

## 🔧 本会话新增
- 管线第 5 次中断: 日志停在 7/29 21:32 EDT，10h 静默，容器 health endpoint 拒绝连接
- `7d94666` fix: FutuNewsFetcher 三层熔断器 — pre-flight TCP 探测 + circuit breaker + 全失败检测
- `79826da` fix: probe 改用 raw socket TCP (2s timeout) — 彻底避免 OpenQuoteContext 线程泄漏
- 效果：OpenD 挂时 1 次 2s TCP 探测 → skip 138 关键词，0 线程泄漏
- `41b4673` fix: FutuFundFlowFetcher 加熔断器 — 资金流采集器之前漏掉保护，71 票全部超时
- 效果：OpenD 挂时 1 次 3s TCP 探测 → 跳过整批 20 只票，0 线程泄漏
- `a7c8489` fix: TG 通道加话题去重 (5min窗口+headline similarity) — 修复 BOJ 被5源重复推送

## ⚠️ 踩坑记录
- Futu SDK `OpenQuoteContext()` 内部重连循环 ~6s/次，无法从外部停止
- `asyncio.wait_for(to_thread)` 取消的是 await，不杀线程 — 线程继续运行 SDK retry
- Docker HEALTHCHECK 用 `curl localhost:8080/health`（8080 不是 8000），新鲜度门禁修了但没起作用
- 健康检查返回 200 后进程仍可瞬间僵死（事件循环 hang ≠ 进程退出）
- Autoheal 只检查 `docker ps` unhealthy 字符串，进程僵死不触发
- ECS 上两个 Futu OpenD 实例在跑（Jul16 + Jul22），容器通过 172.18.0.1 连不上