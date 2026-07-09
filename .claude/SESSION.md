# 当前工作状态

> 最后更新: 2026-07-09 (关机)

## ✅ 本次完成 (2026-07-09)

### 补债 + 修复
- HISTORY 补录 10 提交、manifest 注册 run_v2_local、未跟踪文件三分类 (提交/ignore/不动)
- **MarketWatch scraper 退役** (`6cf390a`): 首页受 DataDome 反爬 (headless 401+零链接)，走 RSS 覆盖
- **V2 影子测试首跑**: 全链路健康，266 items，16 fast_pushed，隔离到位不误推

### 影子测试三发现
- **#1 已修** (`fe9d481`): impact_assessments 从不持久化 → EvaluateStage 接 db，验证 15 行落库
- **#2 不改**: Deep lane on-demand 是设计正确
- **#3 已修**: explainability 步数校验 ==5 → 4-6 放宽

### 记忆持久化 (根治"重启丢记忆")
- **SessionEnd 自动补账 hook** (`b60c379`): 按 commit hash 自动补录 HISTORY，幂等有界
- 约定: HISTORY 条目引用 hash + commit body 写实

## 📋 下一步

1. **V2 灰度切换** (主线): Web SSE → Telegram → Pushover — 涉及推送手机，需用户验收
2. ⚠️ **预存测试债 (07-08 遗留，非本次引入)**: 4 failed + 6 errors
   - `test_impact_push.py` ×3: `6bcb018` 重写 alert_dispatcher reason 格式 (`composite=.. (impact=.. conf=..)`), 测试仍断言旧的 `low_impact` 子串 → 更新测试
   - `test_scheduler.py::test_load_watchlist_default` ×1: watchlist 默认值变了, 断言过时
   - `test_vector_store.py` ×6 errors: Windows ChromaDB teardown PermissionError (环境性, 文件锁)
3. Layer 2 (transcript 合成无 commit 决策) — 未做，可选
4. v1-stable MarketWatch 死方法清理 — 可选，需 V1 窗口手工 Edit (勿 cherry-pick)

## 🩹 上次踩坑

- backfill 脚本初版按 commit subject 匹配 → 误判 23 条全缺失。HISTORY 是叙事体，必须按 **hash** 去重
- `.claude/settings.json` 是 gitignored，SessionEnd hook 只在本机生效

## 📊 系统健康

| 组件 | 状态 |
|------|------|
| ECS 4C8G | ✅ 稳定 (07-08 CPU 修复后) |
| V1 生产 | ✅ healthy |
| V2 (main) | ✅ 影子测试通过，未上线 |
| 工作区 | ✅ 干净，已推送 4c3061e |
