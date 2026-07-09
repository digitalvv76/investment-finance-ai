# 当前工作状态

> 最后更新: 2026-07-10 ~08:00 CST (V1 窗口 / v1-stable)

## ✅ 本次会话完成

- **诊断"哨兵上线后零推送"** → ECS healthy 无宕机。6h 内 66 条评估全部 `is_event=false → no_push`（连静音 TG 都没）。哨兵正确拦噪音，但也**误杀关注股真实异动**（TSLA UBS 上调目标价、MRVL 飙升）。根因：事件哨兵是很窄的**硬门禁**，非 5 类硬催化剂就整条丢 → 从"推太多"矫枉过正成"零推送"
- **关注股/持仓安全网 (`fb0d350`)** → `is_event=false 且 LLM 判 notable 实质动作 且 命中关注股/持仓` → 静音 Telegram。手机保持严格（intensity≥3 才响）。**匹配用 LLM 的 ticker_hint，不用坏掉的 tickers_found**
- **已部署 V1 生产** → 容器 healthy，部署容器内真实 LLM 端到端验收：TSLA PT hike→fire、El Nino→不 fire（旧 ARM 假阳性消失）

## 📊 生产状态

| 组件 | 状态 |
|------|------|
| ECS 容器 | 🟢 healthy (deploy fb0d350) |
| 事件驱动评估 | 🟢 PRIMARY |
| 关注股安全网 | 🟢 已上线 (⏳ 待组织性真实新闻现场确认一次静音 TG) |
| 8080 认证 | 🟢 Basic Auth |
| Pushover / Telegram | 🟢 正常 |
| 华尔街见闻 | 🟢 16 条/轮 |
| 新浪财经 API | ❌ 全 403 |

## 📋 下一步

1. **现场确认一次组织性安全网触发** — 等 fresh 关注股实质动作新闻穿过 dedup+fast_lane 时，查日志 `Watchlist safety net → silent TG` + 确认手机静默、TG 到达
2. **(可选) 修 `tickers_found` 子串误匹配** — entity_extractor "elarm"→ARM 等假阳性；当前安全网已绕过它，非紧急
3. **新浪财经 API 403** — 需新端点或改 web scraper
4. **无关小 bug** — `Retention/cleanup failed: name 'logger' is not defined`（清理任务，不影响推送）
5. **轮换 root 密码 + 凭证备份**（非紧急）

## 🩹 本次踩坑

- `tickers_found` 字段不可信：子串匹配把 "el**arm**"/Teva 误标为 ARM，又漏 Applied Materials → **禁止拿它做推送门禁**，改用 LLM ticker_hint
- `is_event=false` 时旧 prompt 不返回 ticker_hint → 必须扩展 prompt 才能拿到可靠选股
- 稳态 dedup 命中率极高 → 部署后短期抓不到组织性真实触发属正常，用部署容器内直跑真实 LLM 验收代替

## 🧪 测试状态

- registry-mapped: 70 passed（event_driven_evaluator + watchlist_safety_net + impact_push + fast_lane + deep_lane + alert_dispatcher）
- 真实 LLM 验收 `scripts/accept_watchlist_safety_net.py`: 5/5 PASS
- 全量套件 Windows 本地仍受 ChromaDB 文件锁 + GBK 子进程 flake 影响（非本次改动）
