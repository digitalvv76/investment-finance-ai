# 当前工作状态

> 最后更新: 2026-07-10 深夜 CST (V1 窗口 / v1-stable) — 关机存档

## 🆕 本会话完成（2026-07-10 晚 · 全在 v1-stable，交接 V2）
1. **诊断美光$250B误响手机**(id=3340) → 根因=事件驱动路径只升级不因过期降级 → 出 `SPEC-stale-event-downgrade.md`(1h阈值/降静音TG/时区排雷)。**待 V2 实现。**
2. **诊断深度分析编造行情**(id=3340,META卡片-7.64%实际+4.70%双源确认) → 根因=抓行情8s超时静默丢弃+LLM软约束无视硬编 → 出 `SPEC-deep-analysis-stale-data.md`(硬门禁/输出校验/Finnhub主源)。**待 V2 实现,高优先。**
3. **评级训练资料.docx** → 生成 `data/training/catalyst-cases.jsonl`(正面18)+`catalyst-cases-negative.jsonl`(负面8,N1-N5)。用户校准:大额政府计划广度不降级→深挖受益股(记忆 govt-program-rating-deepdig)。
4. **自动标注原型** `news-monitor/scripts/autolabel_training.py`(TDD 6绿):历史新闻+真实涨跌→带真值强度JSONL。命门=ticker清洗(用ticker_hint)。
5. **训练评估系统上正规流程**:`REQ-training-eval.md`(系列1/4,需求+验收前置)。决策已定:A少样本+C校准/验收80-90-75-70/V1初稿+用户抽核80条金标/噪音取生产库"评过没推"/防泄露few-shot与测试集零重叠。外部第三方评估版在用户桌面。请 V2 评估 handoff 已提交。

## 📋 训练评估项目 — 下一步
- ⬜ **用户**:发外部版给独立第三方评估(桌面 `REQ-training-eval-外部评估版.docx`);待定正式 owner+排期。
- ⬜ **V2**:读 `HANDOFF-review-REQ-training-eval.md` 评可落地性/工作量/实现坑 → 写 `REVIEW-*.md` 回仓库。
- ⬜ **V1(我)**:收齐第三方+V2 反馈 → 写 ②产品/设计文档(数据源/ticker清洗/标注流水线/A+C落地/去重/反馈闭环)。

## 🧭 本窗口定位（2026-07-10 决定）
- **生产 = main（V2 主干）**。今天所有修复已收敛/重实现进 main（安全网=NOTABLE 档、74 关注股、Sina zhibo、时区、看门狗、事件哨兵）。唯 `e02d3e6` 弱催化剂档**有意不搬**（与"少而精"冲突）。
- **v1-stable 保留为短命应急/调参通道**（受 COLLAB-PROTOCOL §2 约束：用完即合回 main、不常驻积累）。退役决定已撤销、worktree 不移除。
- 新开发默认在 main；本窗口应急/并行时用，守 §1–§7。

## ✅ 上一会话完成（已全部收敛进 main）
- 诊断"哨兵零推送" → 关注股安全网（`fb0d350`；V2 已在 main 流水线重实现为 NOTABLE 档）
- 关注列表 21→74（`25059ba`）、新浪 zhibo 修复（`99b588b`）、看门狗移植+时区修复（`78325e5`/`2768e90`）
- 与 V2 全套协作：`COLLAB-PROTOCOL.md`（双方共签）、安全网 SPEC 交接、多 agent 方案（瘦身版 spec）

## 📊 生产状态（main）
| 组件 | 状态 |
|------|------|
| 关注股安全网（NOTABLE→静音TG） | 🟢 已上线 |
| 看门狗 | 🟢 healthy |
| 新浪 zhibo / 华尔街见闻 | 🟢 正常 |
| 决策面板 `/health/decisions` | 🟢 V2 已加 |

## 📋 下一步 / 待办
0c. **🆕 V2 待办（2026-07-11 交接，决策已锁）**：`SPEC-intensity-scale-bear-bias.md` —— intensity 强度标尺**利好偏置** + **推送门槛调整**（同一段 `alert_level` 映射，一并改）。①标尺改方向中性"波动剧烈程度"+显式利空档；②**渠道决策 B**：利空手机上限 important，仅「命中持仓/关注股 **且** 已确认(非传闻)」才升警笛；③**手机门槛 ≥3 抬到 ≥4，强度3只上TG不上手机**（TG响铃还是静音待用户最终定，V1 荐响铃）。⚠️坑：GOOGL 在关注股内，cal-01(强度3二手)靠"传闻不升级"挡住不回 critical。验收锚点：cal-01 改后不得判 critical、不得上手机（只上TG）。校准素材 `catalyst-cases-negative.jsonl` 已备。归属 main/V2。已 push origin/v1-stable。
0. **🆕 V2 待办（新·高优先）**：深度分析卡片**在编造行情数据**（`engine/deep_lane.py`）。**见 `SPEC-deep-analysis-stale-data.md`**（实测证据/7.3s-8s时序/6只股对照/硬门禁契约/测试）。样本 id=3340：卡片称 META 盘前 -7.64% 建议做空，实际 META +4.70%（双源确认）。根因=抓行情 8s 超时（实测 7.3s 卡门槛）→ 575-576 行静默丢弃 → LLM 零数据仍硬编（56 行软约束被无视）。**已出 SPEC + 口头交接 V2**：①硬门禁-无行情禁止输出价格/建议；②输出校验-$/%须匹配行情串；③Finnhub 设主源；④超时改 WARNING+标时间戳。测试：空行情串→断言无$/%无建议。⚠️修好前深度分析数字/建议不可信。
0b. **🆕 V2 待办**：实现 `SPEC-stale-event-downgrade.md` —— 事件驱动推送加"过期降级"闸（事件线 first_seen>1h 且 IMPORTANT → 降 NOTABLE 静音TG；CRITICAL 豁免）。诊断+设计+时区排雷 V1 已做完。触发：美光 $250B 旧催化剂误响手机（id=3340）。
1. **V2 待办**：把两份活文档拷进 main —— `COLLAB-PROTOCOL.md` + 多 agent 瘦身版 spec（见 `HANDOFF-copy-living-docs-to-main.md`）
2. 多 agent 质量把关：已定**瘦身版**（高风险改动 + 一道对抗式核实 + 测试/看门狗/回滚）；全套 4-agent 降级为"用证据换的未来升级"
3. **推送偏少 — 待调参（归 V2/main，用户待定方向）**：诊断确认生产健康、非故障。原因=少而精+隔夜淡+屏门槛严。现规则：手机=硬催化剂(强度≥3)、关注股notable=静音TG、其余不推、前置屏门槛0.3。近12h手机0推(无硬催化剂,正常)，关注股notable有在推(如RKLB,但**静音**用户没注意到)。用户觉偏少，待定方向：A手机多响(降强度门槛)/B关注股别静音改成能提醒/C降屏门槛0.3→0.2多抓。**改在 main，可先影子容器试跑再上。**
4. 本窗口待命；有应急/调参需求再启用

## 🩹 关键记忆（本会话沉淀）
- `disable/silent/skip` 语义必须对着代码核实（V1+V2 双双栽过一次）
- 跨窗口/跨分支任务先提醒确认再执行（见记忆 v1-v2-confirm-before-crossing）
