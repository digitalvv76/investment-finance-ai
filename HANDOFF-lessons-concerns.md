# HANDOFF — LESSONS 隐忧核查结果（交 V2）

> V1 → V2 · 2026-07-11 · 信道 origin/v1-stable
> 起因：用户要求"看到隐忧告诉 V2 去改"。V1 查清后**如实**交接——**不是让你去修 main 的 bug**，两条要点如下。

## 隐忧 1：v1-stable 测试红，已查清 = 分叉漂移，非 main 问题

`dev_checklist`（在 v1-stable worktree 跑）报 **3 failed / 6 errors / 390 passed**。逐条核查：

| 项 | 真相 | 结论 |
|----|------|------|
| 6 errors | 全是 `test_vector_store.py` 的 **ChromaDB-on-Windows 文件锁 PermissionError** | **已知容忍项**（TROUBLESHOOTING 有记），Linux/ECS 不出，忽略 |
| 3 failed | 全在 `test_scheduler.py`：`test_scraper_tick`/`test_heartbeat_tick`/`test_heartbeat_fetches_rss_and_chinese`，均 AssertionError | **v1-stable 分叉漂移** |

漂移证据（`git show origin/main:… vs v1-stable:…`）：
- `collector/scheduler.py`：main vs v1-stable **差 149 增 / 106 删**（已面目全非）。
- `test_scheduler.py`：差 78 增 / 114 删。
- `test_scraper_tick` 在 **main 上根本不存在**（0 处）。

→ **这不是 main/生产的 bug，是 v1-stable 攒了旧代码。** 我（V1）没在 main 上乱改，也没造成这个。

### 请 V2 决策（不是让你修，是让你/用户定 v1-stable 怎么办）
按 COLLAB-PROTOCOL §2"v1-stable 用完即合回 main、不积累"：
- **选项 A（推荐）**：确认 main 的 `test_scheduler` 是绿的（大概率是，它是活跃主干）→ 认定这是 v1-stable 漂移 → **要么把 v1-stable 里还有用的 scheduler 改动 port 回 main，要么丢弃 v1-stable 的旧版**，让 v1-stable 回到"短命应急"本分。
- **选项 B**：明确把 v1-stable 当一次性草稿分支，接受它的 checklist 会红，不再据此判断健康。
- 退役 v1-stable 常驻是 **owner（用户）决策**（§8），V2 别单方拍板。

## 隐忧 2：门禁卫生（前瞻，真正归 main/V2）

`dev_checklist`/`pre-commit` 现在**容忍** ChromaDB 一类错误。请确认**容忍逻辑只白名单 `test_vector_store`**、不会顺手把别的真失败也吞掉——否则某天真 bug 会混在"已知红"里溜过门禁。这条是 main 门禁的长期健康，值得你扫一眼 `dev_checklist.check_tests()` 的判定。

## 附：知识体系化
V1 已把散落经验收成 `LESSONS.md`（总纲+索引）。建议你**拉进 main** 与其他 living docs（COLLAB-PROTOCOL 等）同处，避免又一份文档只在 v1-stable。
