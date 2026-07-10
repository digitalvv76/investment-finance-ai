# v1-stable 退役通知（收敛完成）

> 来自 V2/main 窗口（2026-07-10）。依 COLLAB-PROTOCOL §8，用户已拍板：**收敛单主干、退役 v1-stable**。

## 收敛评估结论：main 已是完整主干，无需再 port
- Sina zhibo / 关注列表74 / get_recent_news时区 → 今天已 port 进 main。
- 安全网 → 今天已在 main 流水线重新实现（NOTABLE 档 + 决策面板）。
- 看门狗 / 事件驱动哨兵 → main 本就有。
- 唯一 main 缺的 `e02d3e6`（弱催化剂 intensity1-2 静音档）→ **有意不 port**：与用户新选的「少而精」冲突（会重新引入 firehose）。

## 退役后的规则
1. **main 是唯一主干**。所有新开发落 main（V2 窗口 / D:\class1）。
2. `v1-stable` 分支**保留为归档**（git 历史不删，安全兜底），但**不再在其上开发**。
3. 类生产验证 → 用**影子/金丝雀容器**，不再靠常驻分支。
4. 生产部署：只走 git（`git fetch + checkout origin/main -- <files>` + rebuild），部署前先 `docker tag` 回滚镜像。

## 待办（需 owner 协调，V2 不单方执行）
- **物理移除本 worktree**（`.claude/worktrees/v1-stable`）：因为这是 V1 窗口的活动工作区，**在 V1 会话仍活跃时移除会打断它**。→ **等 V1 窗口收工后**，由用户或 V2 执行 `git worktree remove`。
- origin/v1-stable 远程分支：保留归档，不删。

**V1 窗口若看到此通知**：确认已无未提交/未 port 的东西后，即可收工；worktree 可安全移除。
