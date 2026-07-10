# 当前工作状态

> 最后更新: 2026-07-10 ~11:10 CST (V1 窗口 / v1-stable)

## ✅ 本次会话完成

- **诊断"哨兵上线后零推送"** → 事件哨兵硬门禁误杀关注股异动。加**关注股安全网**(`fb0d350`)：is_event=false 但 LLM 判 notable + 命中关注股 → 静音 TG，手机严格。
- **关注列表 21→74 只**(`25059ba`) → 用户真实关注池整理成可追踪美股，容器实测 74 生效。
- **移植 V2 看门狗到 V1**(`78325e5`) → 独立任务测上游存活，判 HEALTHY/QUIET_OK/STALLED/DEGRADED；STALLED→手机警笛，DEGRADED→手机高优，每日 09:00(北京)静音心跳。`send_system_alert` + web `/health/watchdog(.json)`。
- **修看门狗误报 STALLED**(`2768e90`) → `get_recent_news` UTC vs 本地 captured_at + `T`/空格分隔符双 bug → `datetime(captured_at) > datetime('now','localtime',?)`。生产实测 ingest_1h 0→8，verdict healthy。

## 📊 生产状态

| 组件 | 状态 |
|------|------|
| ECS 容器 | 🟢 healthy (deploy 2768e90) |
| 事件驱动评估 + 关注股安全网 | 🟢 已上线 (74 关注股) |
| **看门狗** | 🟢 已上线，state=healthy，ingest_1h=8，无误报 |
| 8080 认证 | 🟢 Basic Auth |
| Pushover / Telegram | 🟢 正常 |
| 新浪财经 API | 🟢 已修复 (zhibo feed, 19 条/轮) |
| news-monitor-shadow (V2 金丝雀) | 🟠 unhealthy 但不推送，归 V2 窗口 |

## 📋 下一步

1. **cherry-pick 到 main** → V2 窗口把本会话 commit 同步（fb0d350/25059ba/78325e5/2768e90/99b588b）
2. **(可选)** retention DELETE(database.py:543) 仍 UTC，早删 4h，无害可后补
3. **轮换 root 密码 + 凭证备份**（非紧急）

## 🩹 本次踩坑

- `captured_at` 存本地时间但 `get_recent_news` 用 UTC 比较 → ET 容器 1h 窗口永远空 → 看门狗误报 STALLED。叠加 Py3.12 isoformat `T` 分隔符破坏字符串比较。修法：`datetime()` 包裹 + localtime。
- 看门狗必须现场验证真实 DB 信号，不能只看单测（单测用 FakeDB 不含时区/分隔符真相）。
- V2 send_system_alert 只走 Pushover，绕开新闻翻译器（直发 PUSHOVER_API）。

## 🧪 测试状态

- watchdog 17 + send_system_alert 4 + db(含 TZ 回归) + registry-mapped：全绿
- 部署容器端到端：healthy 路径 + STALLED 故障注入 均验证（假 dispatcher 不真发）
