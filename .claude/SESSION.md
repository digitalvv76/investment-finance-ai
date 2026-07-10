# 当前工作状态

> 🔔 **[2026-07-09 来自 V1 窗口] ECS 灰度前必读交接 → [`.claude/V1-TO-V2-HANDOFF.md`](V1-TO-V2-HANDOFF.md)**
> 含：今天的安全修复(`cab7d4f` 已在 main，含生死攸关的 `../config` 卷路径)、V2≠V1 提醒、灰度架构坑、**需先与用户确认 A/B 方案**。开工先读它。

> 最后更新: 2026-07-10 (系统存活看门狗完成 — 解决沉默歧义)

## 📋 下一步 (需用户拍板部署方式)

- ⚠️ **影子暂已撤下** (2026-07-10 事故后)。V1 生产已恢复健康、跑旧代码、数据完好。
- ✅ **「影子采集卡死」已修** (systematic-debugging): 根因 dedup Tier 2.5 批内语义去重 O(N²) 重复encode(156条≈48min阻塞事件循环)。修法 embed_batch预编码+缓存cosine, O(N²)→O(N), 真容器156条 48min→5.4s。410 tests绿。见 [[dedup-silent-stall-on2]]
- ✅ **方案A 已执行**: V1 换成 clean main(git checkout源码, 保留ECS compose/.env), 重建。修看门狗3个时区/自污染假象(count_recent_news/get_health_stats localtime + 排除watchdog_)。V1实测 state=healthy/ingest15/success100%, 411 tests绿。回滚镜像 docker-news-monitor:rollback-20260710。
- 📊 **下一步: 用户观察 V1 真实推送 1-2 天**做验证(方案A的验证环节)。看门狗在线会报平安/故障。
- ⚠️ 遗留系统性隐患: captured_at/created_at 本地存储 vs 查询时区不一致([[db-captured-at-timezone]]), 已修看门狗路径, 其他查询(如digest/api)待排查。
- ✅ **配置对齐**: main settings.yaml 已纳入 ECS 调优(heartbeat 60→30, heartbeat_hour 8→21), 不再漂移。
- 🟡 **待用户定**: sources.yaml 的 request_delay(ECS 3.0/1.5 保守 vs main 1.0/0.3 并发优化)方向不明——是 ECS 撞403后的新调优, 还是并发改造前的旧值? 未合并。死配置 min_impact_for_push(仅ECS, 代码不读)+ 游离文件暂留(无害, 生产删文件有风险)。
- ✅ 已修的部署阻断(可复用): pids 150→512、watchdog.py入清单、relevance路径硬化、shadow挂memory:ro、--down只撤影子
- 看门狗代码本身完成且验证通过, 随修复后重部署即可

## ✅ 本次完成 (2026-07-10 · 看门狗)

### 系统存活看门狗 (Watchdog)
- `engine/watchdog.py` — 四态歧义消解: HEALTHY/QUIET_OK/STALLED/DEGRADED
- 独立异步任务(非寄生 scheduler)+ 防抖 + 冷却 + 每日心跳
- `alert_dispatcher.send_system_alert()` 警笛/高优/静默
- Web 健康页 `/health/watchdog`(免登录，Playwright 已验收两态)
- 全量 **406 passed / 0 failed**

## 📋 下一步 (需用户拍板部署方式)

- **看门狗部署**: 三选一 ⬇️
  - A. 随 V2 影子→切换一起上（干净，但 V1 问题多等 1-2 天）
  - B. 现在单独上 V1 生产（快，但 V1 是漂移代码，有集成风险）
  - C. 影子期让看门狗「真报警」而推送对比仍 DRY_RUN（兼顾：即时保护 + 对比）
- 原下一步仍在: `./deploy-shadow.sh` 影子对比 V1

## ⚠️ 上次踩坑

- 看门狗必须独立于 scheduler，否则 scheduler 卡死时看门狗一起死
- 测试用 FakeDispatcher，绝不构造真 AlertDispatcher（[[tests-never-send-real-pushes]]）
- 影子 DRY_RUN 会让看门狗只 log「WOULD-ALERT」不真报警 → 影子期若要保护需选方案 C

## 🔔 旧交接（仍有效）

## ✅ 本次完成 (2026-07-10)

### 事件驱动评估引擎
- 用户三步规则 (相关性初筛→五类催化剂→强度1-5星), temperature=0
- SCREEN_THRESHOLD: 0.40→0.15 (平衡覆盖率与LLM成本)
- 全中文输出: headline_signal / risk_snapshot

### 事件升级 + 多源确认
- 事件线 ≥3 源 → intensity +1 (cap 5)
- headline_signal 自动追加「多源确认: N家报道」
- 纯规则, 零 LLM 成本

### 影子部署基础设施
- DRY_RUN_PUSH 静音模式 + docker-compose.shadow.yml + deploy-shadow.sh

### 测试
- 392 passed / 0 failed

## 📋 下一步

- 🚀 `./deploy-shadow.sh` 部署影子到 ECS → 对比 V1 推送 1-2 天 → 切
- SCREEN_THRESHOLD: 0.40→0.15（平衡覆盖率与成本）
- 中文输出: headline_signal / risk_snapshot
- 392 tests 绿

### 影子部署基础设施
- `DRY_RUN_PUSH` 静音模式
- `docker-compose.shadow.yml` — 独立容器/端口/数据卷
- `deploy-shadow.sh` — 一键部署，不影响 V1

### 之前 (2026-07-09)
- 孤儿代码移植 P1+P3 (377 tests)
- V1→V2 交接简报已读

## 📋 下一步

- 🚀 **部署影子到 ECS**: `./deploy-shadow.sh`
- 📊 影子跑 1-2 天 → 对比 V1 推送 → 确认无误后切
- 🟡 P2 推送下限: 已被事件驱动引擎替代，不需要了

## ⚠️ 上次踩坑

- rescue 分支 vector_store 删了 close() → V2 必须保留
- rescue docker-compose ECS 特定路径 → 不移植
- EventAssessment.alert_level intensity=3 边界 bug → 已修

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
