# 当前工作状态

> 最后更新: 2026-07-10 傍晚 CST (V1 窗口 / v1-stable)

## 🧭 本窗口定位（2026-07-10 决定）
- **生产 = main（V2 主干）**。今天所有修复已收敛/重实现进 main（安全网=NOTABLE 档、74 关注股、Sina zhibo、时区、看门狗、事件哨兵）。唯 `e02d3e6` 弱催化剂档**有意不搬**（与"少而精"冲突）。
- **v1-stable 保留为短命应急/调参通道**（受 COLLAB-PROTOCOL §2 约束：用完即合回 main、不常驻积累）。退役决定已撤销、worktree 不移除。
- 新开发默认在 main；本窗口应急/并行时用，守 §1–§7。

## ✅ 本会话完成（已全部收敛进 main）
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
1. **V2 待办**：把两份活文档拷进 main —— `COLLAB-PROTOCOL.md` + 多 agent 瘦身版 spec（见 `HANDOFF-copy-living-docs-to-main.md`）
2. 多 agent 质量把关：已定**瘦身版**（高风险改动 + 一道对抗式核实 + 测试/看门狗/回滚）；全套 4-agent 降级为"用证据换的未来升级"
3. 本窗口待命；有应急/调参需求再启用

## 🩹 关键记忆（本会话沉淀）
- `disable/silent/skip` 语义必须对着代码核实（V1+V2 双双栽过一次）
- 跨窗口/跨分支任务先提醒确认再执行（见记忆 v1-v2-confirm-before-crossing）
