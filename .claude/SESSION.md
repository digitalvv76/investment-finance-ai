# 当前工作状态

> 最后更新: 2026-07-10 ~01:05 CST (V1 窗口 / v1-stable)

## ✅ 本次会话完成

- **事件驱动催化剂哨兵上线 (V1 生产)** → 复用 V2 引擎搬到 V1，事件驱动为 PRIMARY 评估器，`is_event && intensity≥3` 推送。取消 prescreen + FastLane 阈值 0.3→0.15。零数据库迁移(适配进 ImpactAssessment)。旧 ImpactEvaluator 休眠。已部署 healthy，日志确认 PRIMARY 加载无报错
- **8080 公网裸奔修复** → Basic Auth 已强制 (`e0439cd`+`63b1c4e`)
- **又一处孤儿漂移修复** → compose 卷路径 `./config`→`../config`
- **deploy.sh** → FILES 加入 compose + event_driven 文件

## 📊 生产状态

| 组件 | 状态 |
|------|------|
| ECS 容器 | 🟢 healthy |
| 事件驱动评估 | 🟢 PRIMARY 已上线 (⏳ 待新鲜新闻现场确认一次真实评估) |
| 8080 认证 | 🟢 Basic Auth 已强制 (无认证→401) |
| Pushover / Telegram | 🟢 正常 |
| 华尔街见闻 | 🟢 17 条/轮 |
| 新浪财经 API | ❌ 全 403 |

## 📋 下一步

1. **现场确认一次真实事件评估** — 等有新鲜合格新闻通过 dedup+fast_lane 时，查日志确认 event eval + 推送决策正确
2. **新浪财经 API 403** — 需新端点或改用 web scraper
3. **(可选) 8080 收回 127.0.0.1** — 需 nginx + Vercel 改指向，非必需（已有认证）
4. **轮换 root 密码 + 凭证备份**（非紧急）

## 🩹 本次踩坑

- 事件哨兵在粗筛之后才跑 → 低分冷门催化剂被漏（V1/V2 通病，V1 已用 0.15 放宽缓解）
- 稳态下 dedup 命中率极高(142/143) → 部署后短期抓不到真实评估属正常，非 bug
- compose `environment: ${WEB_USERNAME:-}` 覆盖 env_file → 容器凭证变空 → 认证静默失效

## 🩹 本次踩坑

- compose `environment: ${WEB_USERNAME:-}` 覆盖 env_file → 容器凭证变空 → 认证静默失效
- git 版 compose 卷路径 `./config/sources.yaml` 错误（真实在 `../config`）→ 服务器跑的是未提交孤儿修正 → 部署 git 版直接 crash
- 部署未跟踪的配置文件前，先确认 git 版路径与服务器实际一致（孤儿漂移高发区）

## 🧪 测试状态

- 上次: 338 passed, 0 failed, 6 errors (ChromaDB Windows file lock)
