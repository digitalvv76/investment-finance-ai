# 当前工作状态

> 最后更新: 2026-07-09 ~23:30 CST (V1 窗口 / v1-stable)

## ✅ 本次会话完成

- **8080 公网裸奔修复** → 应用层 Basic Auth 已强制 (`e0439cd`+`63b1c4e`)。根因=compose `${VAR:-}` 把 WEB_USERNAME 覆盖为空；验证 401/200 全过，手机深度分析链接不受影响
- **又一处孤儿漂移修复** → compose 卷路径 `./config`→`../config`（部署时暴露，生产短暂 DOWN 后恢复）
- **deploy.sh** → FILES 加入 docker-compose.yml（此前从不部署）

## 📊 生产状态

| 组件 | 状态 |
|------|------|
| ECS 容器 | 🟢 healthy |
| 8080 认证 | 🟢 Basic Auth 已强制 (无认证→401) |
| Pushover | 🟢 正常 |
| Telegram | 🟢 正常 |
| EventEscalator | 🟢 就绪 (等 event_line) |
| 华尔街见闻 | 🟢 17 条/轮 |
| 新浪财经 API | ❌ 全 403 |

## 📋 下一步

1. **(可选) cherry-pick 事件升级回 main** — 较大的多 commit 移植，风险高，未做
2. **新浪财经 API 403** — 需新端点或改用 web scraper
3. **轮换 root 密码 + 凭证备份**（非紧急）
4. **(可选) 8080 收回 127.0.0.1** — 需 nginx + Vercel 改指向，非必需（已有认证）

## 🩹 本次踩坑

- compose `environment: ${WEB_USERNAME:-}` 覆盖 env_file → 容器凭证变空 → 认证静默失效
- git 版 compose 卷路径 `./config/sources.yaml` 错误（真实在 `../config`）→ 服务器跑的是未提交孤儿修正 → 部署 git 版直接 crash
- 部署未跟踪的配置文件前，先确认 git 版路径与服务器实际一致（孤儿漂移高发区）

## 🧪 测试状态

- 上次: 338 passed, 0 failed, 6 errors (ChromaDB Windows file lock)
