# 🔀 V1 → V2 交接简报：ECS 灰度运行前必读

> 来源: V1 窗口 (v1-stable, `ef7a354`)　发出: 2026-07-09　接收: V2/main 窗口
> 目的: V2(main) 准备在 ECS 灰度运行前，必须先消化以下 4 点。**动手前请与用户确认第 4 点的 A/B 决定。**

---

## 1. 今天的安全修复已经在 main 里了（`cab7d4f`）— 但有一条生死攸关

V1 今天修了 8080 公网裸奔，并已把等价修复移植进 main 的 `docker-compose.yml`：

- ✅ `WEB_USERNAME/WEB_PASSWORD` 不再用 `${VAR:-}` 覆盖（那会解析成空串、关掉认证），改由 `env_file` 注入
- ✅ `WEB_DASHBOARD_URL` 裸 IP → `https://class1-cyan.vercel.app`
- 🔴 **`sources.yaml` 卷路径 `./config` → `../config`** — **这条最要命**

> ⚠️ 今天 V1 就是踩了 `./config` 这个错路径，部署时容器起不来、**生产短暂宕机**。根因是服务器上跑的是"未提交的孤儿修正版 compose"，git 版路径一直是错的。现在 main 已修好。
>
> **对 V2 的要求：灰度只能从 main 最新代码部署，绝不从旧分支/旧快照/服务器孤儿版部署。** 参考 memory: `ecs-prod-drift`、`no-direct-server-edits`。

## 2. V2 ≠ "V1 + 新功能"，是重构过的另一套代码

`main.py`(差 336 行)、`pipeline/` 结构、`content_filter.py` 逻辑都和 V1 不同。

→ **不能假设 V2 在生产的表现 = 调教好的 V1。** V1 花了多个会话血泪调出来的行为（中文内容分层过滤、推送门槛 `min_impact_for_push`、去重、容器稳定性），在 V2 里是另一套实现，**从没在真实新闻流里验证过**。灰度的核心目标就是验证这个。

## 3. 灰度架构坑：当前配置根本做不了"并行灰度"

main 的 `deploy.sh` 目标 `/opt/news-monitor`、`container_name: news-monitor`、端口 `8080` —— **和 V1 生产完全一样**，且共用同一个 `.env`。后果：

- 跑 `./deploy.sh` 是**顶替 V1**，不是并排跑
- 共用 `.env` → V2 会**往用户真手机推真推送**，数据/DB/向量库和 V1 混在一起

**所以现状下要么整体切换、要么先做隔离，没有中间态。**

## 4. 推荐方案 + 需要用户拍板的决定

**V1 窗口给用户的推荐：影子模式灰度（隔离 + 静音推送）。**

- V2 在 ECS 跑起来，但**静音推送**（或只推到单独的 Telegram 测试频道），照常处理新闻、记录"本来会推什么"，与 V1 实际推送**对比 2–3 天**，确认不乱推/不漏推/不崩，再正式切
- 隔离要点：独立 `container_name`、独立端口(如 8081)、独立数据卷、静音/独立推送通道 —— 需要一份"影子 compose"
- 参考 memory: `tests-never-send-real-pushes`（构造真实 dispatcher 会真发 Pushover 到手机）、`push-phone-rules`

**⏳ 用户尚未在 A/B 之间拍板，V2 动手前务必先问：**
- **(A) 影子并行对比**（V1 推荐）— 更稳，先搭 V2 隔离环境 + 静音推送，跑几天对比
- **(B) 直接切 V2 + 人盯 + 随时回滚** — 快，但第一次上就赌 V2 没回归，风险高

**回滚预案**（无论选哪个都先备好）：V1 镜像仍在，`docker compose down` → 切回 v1-stable 代码 → `up -d --build` 即可回滚。

---

_交接完成。V2 请在开工响应里向用户复述这 4 点并确认 A/B，再开始搭建。_
