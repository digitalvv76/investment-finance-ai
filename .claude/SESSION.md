# 当前工作状态

> 最后更新: 2026-07-13 凌晨。关机前：V2 完成 CLAUDE.md 合并 + 记忆修复，V1 评审通过。

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main)，健康 ✅
- **v1-stable 分支**: 已重置为干净 main + 军事冲突关键词原型 — 已偏离 main
- **看门狗**: healthy，8条/时采集正常，2.4h uptime

## ✅ 上次会话交付(2026-07-12 晚间)

- **🔧 WSJ Intel 误推诊断+修复** (`bd4246b`→`a691426`): 
  - 链路追踪：event_driven_v1.txt→催化剂1→few-shot对齐→★5→critical→Pushover
  - 根因：prompt 不区分「新事件」vs「旧闻新报」
  - 修复：timeliness 融入 intensity 评分（LLM 原生评估）+ 代码层 cap 兜底
- **📊 R0 event_decisions 落库表** (`9af94d7`): event_driven 评估不再凭空消失
  - EventDecision model + 表 + insert + _persist_event_decision()
  - should_push 推/不推两条路径都落库
- **🚀 已部署 ECS**: 三次提交均已上线生产

## ✅ 本次会话交付(2026-07-13 凌晨)

- **文件恢复验证**: 用户误删 D:\class1 文件 → V2 从 git + E:\class1 恢复 → V1 逐项核对（diff + 行数 + 内容），确认完整
- **全局记忆审计**: 33 条记忆中 2 条关键错误（pending-tasks 系统状态写"ECS跑V1"、v1-became-v2 "待决策"）+ 6 条过时 → V2 修复
- **CLAUDE.md 合并评审**: V2 合并 Karpathy 4 条 + Mnimiy 5 条行为准则 → V1 评审通过，1 个小调整（"用户期望"位置）
- **回执提交**: V1→V2 HANDOFF 已 push (`dda84bd`)

## 📋 下一步
- ⏳ **等用户 GLM 新 key**: 余额到账后继续 P0→P1
- 📊 **观察生产**: timeliness 字段分布 + 误推是否归零
- 🔧 **GLM 后续**: P1 Translator切GLM → P2 Curator切GLM → P3 对抗式核实
- 🟡 **V2 待提交**: main 工作区有 V2 的 6 个未提交文件（CLAUDE.md/HISTORY/SESSION/记忆等），下次 V2 开工需 commit

## ⚠️ 本次踩坑
- **文件恢复不能只看文件名**: 用户指出必须抽检内容，发现 .env + settings.json 不在 git 里需从 E 盘手动恢复
- **记忆时效性**: `v1-became-v2-pending-decision` 2 天前的内容"待决策"已过时，V2 读到会误判 ECS 状态 — 记忆需要定期审计

## ✅ 上午会话交付(2026-07-12 · 高产)

- **卫生**: HISTORY.md 补录10条缺失提交 + 工作区清干净 (`387edf9`)
- **合作方参考手册**: `docs/prompts-and-skills-reference.md` — CLAUDE.md + 7 Skill + 11 Prompt 全量梳理
- **竞品分析 + 实验驱动合并**: 评估 `news-monitor/docs/sentiment.md` → 提取3个可借鉴点 → 创建实验版 → 64条×2版本=128次LLM调用验证 → 修复tg-810退化 → 合并到 `impact_v1.txt` → 部署ECS (`297d1f2`, 回滚 `rollback-20260712-111737`)
  - A. greed_index 5档锚点(0-30恐慌~71-100极端贪婪)
  - B. confidence 混合信号降权(多空并存降20-40分)
  - C. 快速预判(纯事实低分通过 + 大佬拒评不升级)
- **ECS生产20条终验**: 旧版漏判伊朗复仇宣言(15/WATCH),新版正确85/FLASH
- **V2→V1回执**: 军事冲突关键词乘数方案评估 — 方向认同,建议关键词做触发不做乘数 (`34071c4`)
- **全量 Prompt 参考手册**: `docs/prompts-complete-reference.md` — 11个prompt完整正文+参数+设计理念
- **GLM API 接入(P0)**: key已配入.env+settings.json, `api.z.ai` 连通, 模型 `glm-5.1` 存在, 待余额到账

## 📋 下一步
- ⏳ **等 V1 吸收评审**: REQ-training-eval → R0 落库表
- ⏳ **等用户 GLM 新 key**: 余额到账后继续 P0→P1(GLM对抗核实+Translator/Curator轻量任务)
- ⏳ **等 V1 吸收军事冲突方案回执**: V2-TO-V1-HANDOFF.md 已提交
- 📊 **观察生产 1-2 天**: impact_v1 3项改进的推送质量变化
- 🔧 **GLM 后续**: P1 Translator切GLM → P2 Curator切GLM → P3 对抗式核实用GLM打破同模型盲点

## ⚠️ 上次踩坑(关键教训)
- **tg-810 Fed拒评被升级**: 实验版把"declines to hint"过度解读→加"prominent figure zero new info"例外修好
- **GLM API国内URL vs 国际版**: `open.bigmodel.cn` ≠ `api.z.ai`; 国际版key国内URL返回"模型不存在"而非明确报错,浪费5次调用排查
- **清卫生项**(commit `66046b6`): ①补注册 `eval_framework_holdout.py` 进 __manifest__.json(消未注册警告) ②提交积压 HISTORY(SessionEnd 补账)，工作区干净。
- **V1交办: deep_lane 登记表误挂修复**(commit `bfbd26a`): `acceptance_test.py` 不 import deep_lane(已核实)却被挂 related_scripts→常报「过时」。**两张表一并清**(旧 module_registry.json 供 session_startup + 新 engine/__manifest__.json 供 pre_commit，只删旧的会从提交路径复发)→ [[two-manifest-tables-sync]]。回执 `.claude/V2-TO-V1-HANDOFF.md`。
- **V1评审: REQ-training-eval**(commit `fb36f7d` → `REVIEW-REQ-training-eval.md`): 对着 main 真实代码核实(非文档假设)。**头号发现=event_driven 决策完全不落库**(evaluate.py:96-99 命中即 return 不写表;ticker_hint 内存态从不入 news 表)→ R1/R3/G4 自动标注塌方 + R4 噪音负例捞不出 + A2 precision/recall 量不出。建议**新增 R0 落库表(V2 0.5天)排②设计前 + 别回填历史 + 路线 C 先于 A**。方法学(相关≠因果)明确让第三方。**球已发回 origin/main，等 V1 自己读吸收进②产品设计。**

<details><summary>上午会话交付(已存档)</summary>

## ✅ 本次会话交付(2026-07-11)
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

</details>

## 📋 下一步
- ⏳ **等 V1 吸收评审**: `REVIEW-REQ-training-eval.md` 已发回 origin/main。若 V1 采纳 R0 落库表→**V2 认领实现**(新增 event_decisions 表, evaluate.py 事件路径 return 前落库, ~0.5天)。这是训练评估项目的地基。
- 📊 **观察生产 1-2 天(三改一起看)**: ①深度分析是否变精简(~250-300字)且③映射到你的持仓/关注股 ②认方向过滤不误删不漏反向 ③利空事件不再误拉手机警笛(看日志 direction/confirmed/渠道)
- ⚠️ **intensity残留(对抗核实报,已报用户)**: #3 ticker_hint=损失方靠prompt约定无代码强制(LLM若把tracked受益股误放ticker_hint→利空误判); 靠confirmed主动化+prompt缓解,生产出问题再加schema
- ⚠️ **认方向残留(中低危)**: 复合句双票反向/多票主标的抓取失败裸方向句; 人工审核兜底
- 🟢 **V1通知②已处理(2/3落地)**: ①门禁漏洞已修(dev_checklist.check_tests改为逐条核实每个ERROR行都是test_vector_store,真error与已知error同现时不再被吞) ②LESSONS.md已从origin/v1-stable拉进main根目录 ③v1-stable漂移决策=**选A**(已确认main scheduler 17绿→v1-stable旧scheduler是漂移,应丢弃回归短命应急;**实际重置在V1窗口做,V2不跨窗口碰v1-stable**)
- 🟡 **待用户定**: sources.yaml request_delay(ECS 3.0/1.5 vs main 1.0/0.3)
- ⚠️ **遗留时区隐患**: captured_at/created_at 本地 vs 查询UTC不一致([[db-captured-at-timezone]]), digest/api待排查

## ⚠️ 上次踩坑(关键教训)
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
