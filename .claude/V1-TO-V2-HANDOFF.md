# V1 → V2 交接

> 信道：提交进 main，V2 开工读 origin/main 即见（COLLAB-PROTOCOL §7）。
> V1 窗口 = v1-stable @ D:\class1\.claude\worktrees\v1-stable
> V2 窗口 = main @ D:\class1

---

## 2026-07-14 · 🔴 V1 工作树再次损坏 — 请 V2 修复

### 症状

V1 会话启动后自查健康状态，发现：

| 检查项 | 结果 |
|--------|------|
| `v1-stable/` 目录存在 | ✅ |
| `.git` 文件/worktree link | 🔴 **不存在** — 目录下没有 `.git` |
| `git worktree list` | 🔴 只列出 main，无 v1-stable |
| `git branch --show-current` | 🔴 = `main`（穿透到了 `D:\class1\.git`） |
| v1-stable 分支 | 🟢 存在，最新 `a17a70c` |

**结论：`v1-stable` 目录只是一个普通文件夹，不是 git worktree。** commit `b6a1245` 声称「v1-stable 工作树已重建（prunable→clean）」，但看起来只建了目录，没写 `.git` worktree link。等于 V1 现在披着 V1 的壳、实际站在 main 上。

### 需要 V2 做的

```bash
# 先确认当前状态
ls -la D:\class1\.claude\worktrees\v1-stable\.git

# 如果确实没有 .git，重建 worktree：
cd D:\class1
git worktree add .claude/worktrees/v1-stable v1-stable
# 或如果目录已存在但残留：
git worktree remove .claude/worktrees/v1-stable 2>/dev/null
git worktree add .claude/worktrees/v1-stable v1-stable
```

### 顺便

- V2→V1 交接文件（`V2-TO-V1-HANDOFF.md`）里关于 CLAUDE.md 评审的待回复项已过期（V1 已于 7/13 commit `dda84bd` 回复通过）
- Docker healthcheck 方案已确认，不用再等 V1 回复
- V2 工作区还有三个文件未提交（main.py / routes.py / HISTORY.md），应该是 healthcheck 缓存的实现

---

## 2026-07-14 · 今日违规：deep_lane prompt 改动直改 main

### 发生了什么
1. 用户反馈 NVDA 深度分析格式问题，要求检查
2. V2 直接诊断 → 直接改 `news-monitor/engine/deep_lane.py` on main → 提交 → 准备部署
3. 用户纠正：违反 V1/V2 分工，选方案 B（V1 先改 → 再交 V2）
4. 回退 main → 尝试在 v1-stable 改 → 发现 v1-stable 工作树损坏
5. 最终在 main 完成改动 + 部署

### 错在哪
- **COLLAB-PROTOCOL §2**：新改动落 main，但应先在 v1-stable 验证再 port
- **COLLAB-PROTOCOL §6**：收到"检查一下"的任务，应判断归属再动手，而非直接改 main
- **根本原因**：V2 开工时没有先确认改动归属窗口

---

## 重申：改动归属判断（每次动手前必读）

| 触发 | 正确做法 |
|------|----------|
| 用户反馈推送质量问题 | **V1 窗口观察 → V1 诊断 → V1 出方案 → 写交接给 V2** |
| 纯技术问题（架构/代码/测试/部署） | V2 自行决策 |
| 涉及投资工作流影响（推送格式/频率/内容） | 先经 V1 → 再交 V2 |
| 部署生产 | 仅 V2 执行（§1） |
| 不确定归属 | **先提醒用户**，不直接执行（§6） |

## 两个窗口各自做什么

| | V1 (v1-stable) | V2 (main) |
|---|:---:|:---:|
| 推送格式/内容调整 | ✅ 诊断 + 方案 | ✅ 实施 + 部署 |
| 采集/管道/基础设施 | ❌ | ✅ |
| 生产部署 | ❌ | ✅ |
| LLM prompt 调整 | ✅ 出语义契约 | ✅ 写代码 |
| 跨窗口交接 | ✅ 写交接文档 | ✅ 读交接文档 |

## V2 待做

- [x] 今日 deep_lane 改动已部署（特例，因 v1-stable 损坏）
- [ ] 下次 V1 先动手前，读本文 + `COLLAB-PROTOCOL.md`
- [ ] v1-stable 工作树修复后，回归正常 V1→V2 流程

---

**V1 签**：已告知，下次再犯 V2 自己负责。
**V2 签**：________________________________
