# 架构回执：给 V1 窗口 — 写"流水线版安全网"规格前必读

> 来自 V2/main 窗口（2026-07-10）。你要写"在流水线里重新实现关注股安全网"的设计规格，
> 这份文件给你 main 的**真实架构事实**，免得规格再基于旧内联架构假设（上次 HANDOFF 的盲点）。
> **分工**：你写语义层（notable 定义/意图/复用件），V2 写接线层（stage/level 机制/prompt）。

---

## 1. 当前推送决策架构（已核实代码）

**决策在 `pipeline/evaluate.py` 的 `EvaluateStage`，不是 DispatchStage。** 流程：

```
IngestStage → ScreenStage → EvaluateStage(定 item.decision.alert_level) → DispatchStage(按 level 路由) → DeepStage
```

- `EvaluateStage` 把 `event_assessment` 映射成 `item.decision = DispatchDecision(alert_level=...)`
- `event_assessment.is_event == False` → **直接判 `AlertLevel.NORMAL`**（evaluate.py:92-93 一带）
- `intensity` → level 映射（evaluate.py:225-229）：高 intensity → CRITICAL，其余 IMPORTANT/NORMAL
- `DispatchStage`（dispatch.py:38）：`disable = alert_level == NORMAL` → **NORMAL 就完全不推**

**安全网的缺口**：`is_event=false` 的新闻现在一律 NORMAL → 一条都不发。安全网要的是：这类里"notable + 命中关注股"的 → **升级成仅静音 TG**（永不上手机）。**接入点就是 EvaluateStage 那个 NORMAL 分支。**

## 2. 现成可用 / 缺失的件（已核实）

| 件 | 现状 |
|----|------|
| `EventAssessment` 字段 | 有 `is_event` / `intensity` / `ticker_hint`；**没有 `notable` 字段** |
| `should_push` | `is_event and intensity >= 3`（纯事件逻辑，安全网是另一条路） |
| `AlertLevel` 枚举 | CRITICAL / IMPORTANT / NORMAL —— **没有"静音 TG"这一档**，需 V2 定机制（新增 level vs decision 上加 flag） |
| `get_tracked_tickers()` | **main 里不存在**（是你 fb0d350 加的）。main 现用 `engine/relevance.py::_get_watchlist()`（读 `.claude/memory/watchlist-state.md`，已扩到 74 只） |
| `watchlist_safety_net()` + `test_watchlist_safety_net.py` | **未搬入 main**（随 fb0d350 一起没搬）。若是架构无关的纯函数，V2 会复用；请在规格里指明它的入参/返回契约 |

## 3. 请你（V1）在规格里写清楚（语义层）

- [ ] **notable 定义**：什么算"值得静音提醒的实质动作"？给 3-5 个正例 + 3-5 个反例（边界最有用）
- [ ] **为什么 LLM `ticker_hint` 而非 `tickers_found`**：原始理由（和 main 记忆 `tickers-found-unreliable` 一致，正好佐证）
- [ ] **行为契约**：只静音 TG、**永不 Pushover/手机**；触发条件的完整布尔式（is_event=false ∧ notable ∧ ticker_hint∩关注股≠∅）
- [ ] **notable 从哪来**：需要 LLM 输出它吗？如果是，给出你期望的判定标准（V2 来改 prompt/schema，但要你的语义）
- [ ] **复用件契约**：`watchlist_safety_net(event_assessment, tracked_tickers) -> bool` 的确切签名 + 语义，以及单测覆盖了哪些 case

## 4. 别写（留给 V2 接线层）

- ❌ 挂哪个 stage 的具体代码（V2 定：EvaluateStage 的 NORMAL 分支）
- ❌ 新增 AlertLevel 还是加 flag（V2 权衡）
- ❌ prompt/schema 的具体改法（V2 实现，但按你的 notable 语义）
- ❌ 关注股用哪个函数（V2 定：复用 `_get_watchlist` 或补 `get_tracked_tickers`）

## 5. 交付方式

规格写成 `.claude/worktrees/v1-stable/SPEC-safety-net-pipeline.md`（或你惯用位置），V2 窗口会读。
规格聚焦"是什么/为什么/契约"，接线"在哪/怎么挂"交给 V2——这样不会再有架构错配。
