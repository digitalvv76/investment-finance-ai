# LESSONS — V1/V2 经验总纲

> 单页索引：把散落在 `.claude/TROUBLESHOOTING.md`(22条踩坑) + `.claude/memory/`(记忆) + `COLLAB-PROTOCOL.md` + 各 `SPEC-*` 里的经验收成一页。
> 新会话快速上手看这里；细节回溯看对应源文件。**仅追加/修订，别让它和源双写冲突——这里放"原则+索引"，具体步骤留在源。**
> 建立：2026-07-11（V1）。living doc，建议 V2 拉进 main 与其他活文档同处。

---

## 0. 第一原则（最贵的元教训）

**不要假设行为，对着代码/真实数据核实。**
时区坑、`tickers_found` 误匹配、测试真发推送、`disable/silent/skip` 语义——根因全是"以为它这样，没验证"。V1+V2 双双栽过。凡涉及语义判断，先 `git show`/读源/实测再动手。

---

## A. 协作机制（双窗口）
- **单主干 main + 短命 v1-stable + 影子验证**，不长期分叉（曾分叉到 97/82 commit = 重复劳动）。
- **生产只走 git**（push→pull→rebuild）；V1 **永不** scp/直改生产（铁律）。
- **跨窗口任务先确认再动**——用户会搞混 V1/V2 分工。
- **交接走仓库文件当信道**：`HANDOFF-*`/`SPEC-*`/`ARCH-*`/`DESIGN-*`，比人肉转述可靠可审。
- **写交接前先 `git show 目标分支:文件`** 看真实代码（main 与 v1-stable 常不同）。
- 会话开始读对方 `SESSION.md` + `git log origin/main & origin/v1-stable`。
- → 细节：`COLLAB-PROTOCOL.md` §1–§8。

## B. 技术硬坑（可直接复用）
- **时区+T分隔符**：`captured_at` 存本地时间、Py3.12 存 `T` 分隔 → SQL 必须 `datetime()` 包裹 + `localtime`。看门狗/事件线/stale-event 三处都栽过。
- **测试真发手机推送**：构造真实 `AlertDispatcher` 会真发 Pushover → 必须清空凭证 + stub 发送方，别信"凭证不存在"假设。
- **`tickers_found` 子串误匹配**：禁用于推送门禁，改用 LLM `ticker_hint`。
- **异步管道藏同步 O(N²)**：编码阻塞事件循环 → 采集静默停摆。
- **deploy-shadow `--down`**：`compose down` 会连 V1 一起删 → 必须 `rm -sf` 单服务。
- **手机 API 必须走 Vercel HTTPS**：裸 IP HTTP 手机不可靠；新增手机端点必同步 Vercel rewrite。
- **改阈值必须同步改测试断言**（硬编码断言会挂）。
- **RSS/Sina 源**：每个源从 ECS 实测；Sina 用 `zhibo` feed 绕 IP 级 403。
- → 细节：`.claude/TROUBLESHOOTING.md`。

## C. 推送/评级（信噪比治理）
- **少而精**，屏门槛严。
- **只推已发生的硬事件**，预测/观察不推（模因股"或再现"→不推）。
- **手机门槛要有时效性**：投行研报不推手机；旧催化剂过期降级。
- **大额政府计划广度不降级**，反而深挖受益股；降级只看时效性。
- **事件哨兵硬门禁会致零推送** → 关注股安全网(LLM notable)兜底。
- **强度标尺方向中性**：利空别硬套利好顶格（否则误拉警笛）。
- **分档门槛（2026-07-11 锁）**：手机≥4 / 强度3只上TG静音 / 利空降档B（命中持仓+已确认才升警笛）。
- **用生产真实过评做校准锚点**（见 `data/training/catalyst-cases-negative.jsonl` cal-01）。
- → 细节：`SPEC-intensity-scale-bear-bias.md`、记忆 `govt-program-rating-deepdig`/`push-*`。

## D. 流程纪律
- **持久化三件套**：HISTORY.md(唯一真相,仅追加) + SESSION.md(状态) + TROUBLESHOOTING.md(踩坑)。
- **git log 是唯一权威**，HISTORY.md 可能滞后。
- **高风险改动质量门**：对抗式核实子 agent + 必须有测试 + 回滚 tag。⚠️**同模型 agent 共享盲点**——对抗要换模型/换视角。
- **每个新功能 Playwright 端到端验收**，不只单测。
- **用户不懂编程**：每个决策点给"推荐+理由"、非技术语言。
- **systematic-debugging**：先复现找根因再改。

## E. AI / 评估
- **盲测藏答案**，few-shot 样本必须排除防泄露。
- **自动标注闭环**：新闻出题→市场(涨跌)给答案→训练集自增长；命门=ticker 清洗。
- **验收前置**：钉死可度量通过线再开工。
- **防编数硬门禁**：无实时行情禁止 LLM 输出价格/建议（软约束会被 DeepSeek 无视）。

---

## ⚠️ 已知隐忧（待处置，见 `HANDOFF-lessons-concerns.md`）
1. **v1-stable 测试红 ≠ main 有 bug（已查清 2026-07-11）**：`dev_checklist` 报 3 failed / 6 errors，实为——
   - 6 errors = `test_vector_store.py` 的 ChromaDB-on-Windows 文件锁（**已知容忍项**，Linux/ECS 不出）。
   - 3 failed 全在 `test_scheduler.py`，是 **v1-stable 分叉漂移**：`collector/scheduler.py` 与 main 差 149/106 行，其中 `test_scraper_tick` 在 main 上**根本不存在**。→ 非 main/生产问题。
   - **真隐忧**：v1-stable 积累了漂移（违反 §2"用完即合回 main、不积累"）；且门禁若长期容忍一类错误，可能掩盖真失败。
2. **经验散落/部分过时**：27 记忆 + 22 踩坑 + 协议 + SPEC，本文件是"体系化"第一步；记忆需定期核实（名字/文件/flag 可能已过时）。

