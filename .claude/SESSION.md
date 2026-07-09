# 当前工作状态

> 🔔 **[2026-07-09 来自 V1 窗口] ECS 灰度前必读交接 → [`.claude/V1-TO-V2-HANDOFF.md`](V1-TO-V2-HANDOFF.md)**
> 含：今天的安全修复(`cab7d4f` 已在 main，含生死攸关的 `../config` 卷路径)、V2≠V1 提醒、灰度架构坑、**需先与用户确认 A/B 方案**。开工先读它。

> 最后更新: 2026-07-10 (事件驱动评估引擎上线)

## ✅ 本次完成 (2026-07-10 · 凌晨)

### 事件驱动评估引擎 (替换 LLM 自由打分)
- **用户规则**: 三步判断 (相关性初筛 → 五类催化剂 → 强度1-5星)，temperature=0，结构化 JSON
- **prompt**: `config/prompts/event_driven_v1.txt` — 用户口述规则完整版
- **引擎**: `engine/event_driven_evaluator.py` — LLM 调用 + JSON 解析 + should_push 判断
- **管道集成**: `EvaluateStage` 优先走事件驱动，不触发催化剂时 fallback 旧 ImpactEvaluator
- **决策**: `is_event=true + intensity≥3` 才推，headline_signal/risk_snapshot 中文
- **测试**: 392 passed / 0 failed (+15 新测试)

### V1 交接已读
- `.claude/V1-TO-V2-HANDOFF.md` 4 点已消化
- 安全修复已在 main (`cab7d4f`)
- 灰度 A/B 待用户拍板

## 📋 下一步

- 🎯 **灰度方式 A/B**: 用户拍板影子并行还是直接切
- 🏭 搭影子环境 → V2 隔离跑 → 对比 V1

## ✅ 之前完成 (2026-07-09 · 晚)

### 孤儿代码移植 P1 + P3 (main, 9 文件, 377 tests 绿)

**用户选择方案 B：P1 + P3 一起，P2 单独定。**

- **P1-a 去重 bug** (`dedup.py`): deque+set FIFO 替换 destructive clear()，breaking 前缀归一化，批内 Jaccard+语义去重
- **P1-b 政府干预检测** (3 文件): `strategic_detector.py`(CFIUS/DOE/backstop 实体+评分) + `relevance.py`(12 新类别+DOE/DoD sector signals) + `keywords.yaml`(+47 触发词)
- **P3 性能/加固** (5 文件): RSS 并发化(`asyncio.gather`)、Twitter 2 组并发、Docker `pids:200`、`deep_lane.py` 三阶段实时行情(日线→info→intraday)、`vector_store.pair_similarity()`
- **Manifest 补注册**: event_escalator + market_snapshot + migrate_event_escalation
- 全量 **377 passed / 0 failed / 0 errors**

### 未移植 (P2，待用户定参数)

- P2-a 推送下限 `min_impact_for_push:30` — 改推送行为需先确认
- P2-b 全球市场压力路径 `content_filter.py`

## 📋 下一步

- 🏭 **V2 灰度上 ECS**: 部署 → Web SSE → Telegram → Pushover（建议先只开 Web SSE 观察 1-2 天）
  - ⚠️ 部署前必须先查"ECS 实际跑的代码 vs git"（孤儿漂移背景）
- 🟡 **P2 推送下限**: 用户有空时讨论参数

## ⚠️ 上次踩坑

- 大批文件审计: 单代理啃 47 文件会 600s 卡死 → 拆多个并行代理、限制用 --stat+定向 diff 不 dump 全量
- 移植纯搬运用 `git show v1-stable:<path> > 目标` 逐字节, 避免手抄错
- 隐藏依赖: dispatch_event 需 `_format_event_body`; loader 需补 `import json`; escalator 读 impact_assessments.sentiment(最高风险, 先补 DB)
- rescue 分支的 vector_store 删了 `close()`（旧版没这个方法）→ V2 必须保留 close()，只加 `pair_similarity()`
- rescue 分支 docker-compose 改了 WEB_DASHBOARD_URL/sources 路径 → ECS 特定漂移，不移植

## 📊 系统健康

| 组件 | 状态 |
|------|------|
| ECS 4C8G | ✅ 稳定 |
| V1 生产 | ✅ healthy（跑旧代码, 未动） |
| V2 (main) | ✅ P1+P3 已并入, 377 测试绿, 未上线 |
| 测试 | ✅ 377 passed / 0 failed / 0 errors |
| 工作区 | ⚠️ 未提交 (P1+P3 变更) |
