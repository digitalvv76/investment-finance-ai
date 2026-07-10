# 交接：把两份"活文档"复制进 main（v1-stable 退役前最后一步）

> 来自 V1 窗口（2026-07-10 收尾）。v1-stable 即将归档，下面两份是"活的"、需在主干 main 上留存，别随归档埋掉：

1. **`COLLAB-PROTOCOL.md`**（含你的共签）→ 复制到 main 仓库根
2. **`docs/superpowers/specs/2026-07-10-multi-agent-dev-pipeline-design.md`**（多 agent 瘦身版设计）→ 复制到 main 同路径

取法：`git show v1-stable:<路径>` 或直接从 `.claude/worktrees/v1-stable/` 拷。
其余 HANDOFF-/ARCH-/DONE-/RETIRE- 等历史往来记录，留 v1-stable 归档即可，**不必搬**。
