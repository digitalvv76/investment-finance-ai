# 当前工作状态

> 最后更新: 2026-07-10 (续会话)。生产=clean main+过期降级已上、健康。双窗口保留(受 COLLAB-PROTOCOL 约束)。

## ✅ 本次续会话交付(2026-07-10)
- **Vercel /health/* 代理 404 修复**: 根因=未连GitHub自动部署(旧部署4天前无代理规则)→ 手动 `vercel --prod` + `vercel git connect` 接GitHub自动部署。决策/看门狗面板现可HTTPS访问
- **过期事件降级上线**(V1出规格29ac42b→V2/main实现`d2f067f`): 单源旧催化剂(美光$250B)IMPORTANT+事件线>60min→NOTABLE静音TG；CRITICAL/None/多源(≥3)豁免
  - 🛡️ 对抗核实抓到设计矛盾(first_seen误判持续发酵大事件)→用户定方案B多源豁免；真实SQLite验证时区补回归测试
  - 30新测试/456全绿；deploy-main.sh已上生产(回滚tag`rollback-20260710-191517`)，容器healthy+代码验证在跑

## 📋 下一步
- 📊 **观察生产 1-2 天**: 验证过期降级只命中单源旧闻(看日志 `stale_downgrade`)、多源大事件不误伤 + 安全网「少而精」+ 看门狗报平安
- 🟡 **待用户定**: sources.yaml request_delay(ECS 3.0/1.5 vs main 1.0/0.3,方向不明,未合并)
- ⚠️ **遗留时区隐患**: captured_at/created_at 本地存储 vs 查询 UTC 不一致([[db-captured-at-timezone]]),已修看门狗+过期降级路径,**digest/api 等其他查询待排查**
- 🟡 **降级精修(可选)**: 核实提到降级只改level,intensity/urgency/needs_deep未同步下调(卡片正文仍显ALERT+浪费深度LLM)。当前不影响静音正确性,低优

## ⚠️ 上次踩坑(关键教训)
- **同模型 agent 共享盲点**: `disable/silent` 语义错V1+V2双栽;本次对抗核实又证价值(抓到first_seen设计矛盾)→ 必须对着代码/真实DB证伪
- **--down 误删 V1 生产**:`docker compose down` 拆整个 project([[shadow-down-kills-v1]]);回滚镜像救命
- 时区连环坑(ingest/health_stats/get_recent_news/event_lines.first_seen);dedup O(N²) 静默卡死([[dedup-silent-stall-on2]])

---
<details><summary>历史下一步(已完成,存档)</summary>

## ✅ 上上次会话交付(2026-07-10,超长)
- **系统存活看门狗** 上线(解决沉默歧义);影子部署→抓到并修 **dedup O(N²) 采集卡死**(48min→5.4s)
- **生产事故**(--down 误删 V1)→ 恢复+修脚本;V1 换 clean main;修看门狗 **3个时区/自污染假象**
- 从 v1-stable 搬 3 修复(**Sina 403 恢复**、关注列表74、TZ);配置漂移对齐进 main
- **流水线版关注股安全网 + 决策面板** 上线(is_event=false 默认不推=修firehose;notable+关注股→静音TG NOTABLE档;真LLM+Playwright双验收)
- **COLLAB-PROTOCOL 定稿**(双窗口保留、受约束);**轻量质量把关** 采纳(CLAUDE.md+[[quality-gate-lightweight]]);**`deploy-main.sh`** 一键安全部署(内置回滚tag,已验证)

## 📋 下一步
- 🟡 **Vercel 面板链接还没通**(`/health/*` 代理规则已推但 Vercel 未自动部署,仍 404)→ 确认 Vercel 是否连 GitHub 自动部署,否则手动 Redeploy。链接: `https://class1-cyan.vercel.app/health/decisions`
- 📊 **观察 V1 真实推送 1-2 天**:验证安全网「少而精」效果 + 看门狗报平安/故障
- 🟡 **待用户定**: sources.yaml request_delay(ECS 3.0/1.5 vs main 1.0/0.3,方向不明,未合并)
- ⚠️ **遗留时区隐患**: captured_at/created_at 本地存储 vs 查询 UTC 不一致([[db-captured-at-timezone]]),已修看门狗路径,**digest/api 等其他查询待排查**

## ⚠️ 上次踩坑(关键教训)
- **`disable/silent` 语义错 V1+V2 双双栽**:同模型 agent 共享盲点,必须对着代码证伪(→ 质量把关铁律)
- **--down 误删 V1 生产**:`docker compose down` 拆整个 project([[shadow-down-kills-v1]]);回滚镜像救命
- 时区连环坑(ingest/health_stats/get_recent_news);dedup O(N²) 静默卡死([[dedup-silent-stall-on2]])

---
<details><summary>历史下一步(已完成,存档)</summary>


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
