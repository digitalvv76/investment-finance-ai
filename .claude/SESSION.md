# 当前工作状态

> 最后更新: 2026-07-12 20:55。周末例行检查，事件升级模型运行正常。训练评估项目待用户拍板。

## ✅ 本次会话交付(2026-07-12 晚上)
- 多LLM分工方案说明(Agent/Workflow, 四模型可用)
- GLM Key排查: 系统中不存在
- DeepSeek Key溯源: commit `8b29469` @ 2026-07-02
- 事件升级模型健康检查: ECS healthy, 5级管道正常, 昨日推送活跃, 周日低流正常

## 🔴 开机第一件事(本次遗留,需用户拍板)
**训练评估项目卡在两个决策上,V2评审+我核实已就绪,等你定:**
1. **优先级**: 现在就推进训练评估项目,还是等生产三改观察完(1-2天)再动?
2. **接受「数据从落库日往前攒、不回填历史」吗?** — 意味着金标集之外的训练数据要等时间积累,不是马上就有。
> 定了这两条 → 我采纳R0(决策台账表,V2 0.5天)+升REQ v0.2(C先于A)+写②产品设计文档。

## ✅ 本次会话交付(2026-07-11 下午)
- **4个启动卫生项排查**: 3项(HISTORY补hash/eval_holdout注册)V2已在main主干做过(66046b6)→**v1-stable撤销避免冲突**(单主干原则,不重演漂移); autolabel注册=v1-stable本地(main无此文件)。
- **deep_lane假依赖**: 我标出→V2已修(bfbd26a@main,含**我漏的第二张表**engine/__manifest__.json)→记忆[[two-manifest-tables-sync]]。**v1-stable未重做**,下次对账继承。
- **训练评估REQ经V2评审(REVIEW-REQ-training-eval.md,fb36f7d@main)+我独立核实头号BLOCKER属实**:
  - `[已验代码]` event_driven路径`_apply_event_assessment`只写内存`item.decision`、return前不落库; ticker_hint/intensity/direction从不入表; impact_assessments schema缺全部这些字段; 无event_decisions表。
  - 后果: R1/R3/G4自动标注塌方 + R4噪音负例捞不出 + A2 precision/recall量不出 → **REQ默认的"从历史库挖训练数据"存储层做不到**。
  - V2建议(我认同): 加R0决策台账表(硬前置②设计前) + 不回填历史从落库日自增长 + 路线C先于A + 6实现坑。
- **V2→V1固定信道**: `.claude/V2-TO-V1-HANDOFF.md` @ origin/main(`git show origin/main:...`即见)。

## ✅ 上次会话交付(2026-07-11 上午)
- **深度分析恢复老版4步 + 防幻觉升级「认方向」**(deep_lane.py, commit `873d4c9` 已部署): 用户不满→诊断 `afff8b9` 砍成快讯→用户选B回老版
  - ANALYSIS_PROMPT还原4步 + 防幻觉过滤器重构「认方向」(读真实涨跌只拦说反方向,价格选项B宽松)
  - 🛡️ 4轮对抗核实抓到并修我引入的高危洞(交易动作豁免让反向事实+建议同句逃逸)→去豁免改数字紧跟时即则
- **V1交接①: intensity标尺利好偏置修正**(event_driven_evaluator/evaluate/item/prompt, SPEC-intensity-scale-bear-bias): 利空事件不再误拉手机警笛
  - intensity改方向中性 + direction/confirmed字段 + event_channel_level渠道映射 + 利空升级(confirmed AND losers∩tracked); ★3→NOTABLE静音TG(手机门槛≥4)
  - 🛡️ 对抗核实抓高危洞: confirmed默认True=失败朝手机开→改**失败朝静音**(默认False/neutral封important/未确认利空→notable绝不上手机)
  - 验收: cal-01传闻→notable不上手机✅ 确认利空砸持仓→critical警笛✅
- **V1交接③: 深度分析精简250-300字+修组合映射**(deep_lane.py, SPEC-deep-analysis-trim): 用户嫌太长(实测1484字)
  - ANALYSIS_PROMPT重写~250-300字深度在②③; ③强制映射到用户持仓∪关注股(主受益股不在仓→改指同链条跟踪票); NO_DATA_PROMPT对齐结构+无方向词无数字; max_tokens 1500→900
  - 验收(news3787防务): 276字③正确从LMT五大改指HII/KTOS等关注股✅ 无价位无买卖✅
- 525测试全绿; intensity+trim一并 commit+部署(见本次末尾)

## 📋 下一步
- 📊 **观察生产 1-2 天(三改一起看)**: ①深度分析是否变精简(~250-300字)且③映射到你的持仓/关注股 ②认方向过滤不误删不漏反向 ③利空事件不再误拉手机警笛(看日志 direction/confirmed/渠道)
- ⚠️ **intensity残留(对抗核实报,已报用户)**: #3 ticker_hint=损失方靠prompt约定无代码强制(LLM若把tracked受益股误放ticker_hint→利空误判); 靠confirmed主动化+prompt缓解,生产出问题再加schema
- ⚠️ **认方向残留(中低危)**: 复合句双票反向/多票主标的抓取失败裸方向句; 人工审核兜底
- 🟢 **V1通知②已处理(2/3落地)**: ①门禁漏洞已修(dev_checklist.check_tests改为逐条核实每个ERROR行都是test_vector_store,真error与已知error同现时不再被吞) ②LESSONS.md已从origin/v1-stable拉进main根目录 ③v1-stable漂移决策=**选A·已执行(2026-07-11 V1窗口)**: 归档→`archive/v1-stable-20260711`(d209aee,113提交可恢复,已推origin) + v1-stable `reset`到clean main(a009eac) + 保留在建训练评估项目5文件(REQ×2/HANDOFF-review/autolabel原型+测试, commit `91e695a`)。origin/v1-stable已强推同步。main全程未碰。未提交HISTORY.md WIP存stash。
- 🟡 **待用户定**: sources.yaml request_delay(ECS 3.0/1.5 vs main 1.0/0.3)
- ⚠️ **遗留时区隐患**: captured_at/created_at 本地 vs 查询UTC不一致([[db-captured-at-timezone]]), digest/api待排查

## ⚠️ 上次踩坑(关键教训)
- **两张登记表必须同步**: 依赖登记有旧`module_registry.json`(session_startup读)+新`__manifest__.json`(pre_commit读)两张,修deep_lane只改旧表漏新表→警告从提交路径复发,V2抓到([[two-manifest-tables-sync]])。
- **同模型盲点铁律再验**: V2评审虽标`[已验代码]`仍属同模型;我没直接采信,自己在v1-stable逐点证伪BLOCKER才确认。跨窗口评审也要落地核实。
- **卫生项先看V2/main在不在做**: v1-stable启动报的卫生警告多是trunk级,V2会在main处理;直接在v1-stable做=和main重复+冲突。先查再动。
- **交易动作豁免=高危洞**: 用"句含交易词就豁免方向检查"让反向事实+交易建议同句逃逸(=原事故形态);对抗核实第4轮才抓到。真计划句本身无涨跌方向词,压根不需豁免→只对真条件/触发句豁免
- **同模型 agent 共享盲点**: 本次深度分析改造对抗核实4轮,每轮都抓到前一轮的漏/误删/高危;必须对着真实代码+真实DeepSeek输出证伪,别信单轮共识
- **正则近似治标不治本**: 涨跌幅"量级+动词相邻"正则既漏(跌超8%/量级撞库)又误删(触发条件);语义问题(实际涨跌 vs 触发阈值)要「认方向」结构判别不是堆正则

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
