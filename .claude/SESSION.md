# 当前工作状态

> 最后更新: 2026-07-09 ~20:10 CST (V1 窗口 / v1-stable)

## ✅ 本次会话完成

- **孤儿代码合并** → rescue/ecs-prod-drift-20260708 merged into v1-stable
- **4 预存测试修复** → 338 passed, 0 failed
- **事件升级推送部署** → ECS 容器 healthy, EventEscalator sweep 就绪
- **容器 unhealthy 修复** → on_news_batch 改后台任务 + Docker health check 放宽
- **关注清单推送漏报修复** → min_impact_for_push 降到 20 + 中文 ticker 检测
- **HISTORY.md 补录** → 19 commit 哈希 + 本次全部操作

## 📊 生产状态

| 组件 | 状态 |
|------|------|
| ECS 容器 | 🟢 healthy, 负载 0.12 |
| Pushover | 🟢 正常 |
| Telegram | 🟢 正常 |
| EventEscalator | 🟢 就绪 (等 event_line) |
| 华尔街见闻 | 🟢 17 条/轮 |
| 新浪财经 API | ❌ 全 403 |
| 8080 公网 | 🔴 仍裸奔 |

## 📋 下一步

1. **8080 公网裸奔** — Vercel 改走 :80 认证 + 8080 收内网
2. **轮换 root 密码 + 凭证备份**（非紧急）
3. **cherry-pick 事件升级回 main**（验证通过后）
4. **新浪财经 API 403** — 需新端点或改用 web scraper

## 🩹 本次踩坑

- `deploy.sh` 缺 loader.py → 容器 crash (AttributeError: no load_event_escalation)
- DB migration 不能在旧容器跑 → 直接 SQL
- on_news_batch inline await 堵死事件循环 → 改 create_task
- 华尔街见闻 symbols[] 为空 → 中文 ticker 检测 fallback
- 旧容器日志随 `docker compose down` 清除 → 无法查历史推送

## 🧪 测试状态

- 338 passed, 0 failed, 6 errors (ChromaDB Windows file lock)
