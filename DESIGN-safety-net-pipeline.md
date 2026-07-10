# 设计规格：在 main 流水线里(重新)实现关注股安全网

> 给 V2 窗口。作者是 fb0d350(v1 安全网)的原设计者。**先读完"关键发现"再动手** —— main 的推送模型和 v1 不同，直接照 v1 语义实现会做错。

## 背景意图（安全网到底要解决什么）
用户诉求：**关注股/持仓有"实质动作"(调目标价/评级变动/板块异动/大涨跌)但不是硬催化剂时，给一条静音 Telegram 提醒；手机保持严格(只有硬催化剂 intensity≥3 才响)。** 判断用 LLM 抽的 `ticker_hint`(准)，不用 `tickers_found`(子串误匹配，见记忆 tickers-found-unreliable)。

## 关键发现：main 的推送模型 ≠ v1（务必先懂）
我核实了 main 的 `pipeline/`：
- 流水线：`Ingest → Screen(fast_lane) → Evaluate → Dispatch → Deep`。
- `PushoverChannel.send`：**只在 alert_level=CRITICAL/IMPORTANT 发**，NORMAL→不发。→ **手机已天然安全**。
- `TelegramChannel.send`：**不按 alert_level 过滤，凡进 Dispatch 的都发**，`disable_notification=(alert_level==NORMAL)`。
- `EvaluateStage._evaluate_one`：`is_event=false` 分支(evaluate.py ~line 91)把 `alert_level=NORMAL` + 带上 `ticker_hint/filter_reason/headline_signal`。
- **结论**：在 main 上，凡**过了 fast_lane 屏**的 `is_event=false` 项，**已经在静音发 TG 了**。v1 的"is_event=false 一律丢弃"在 main 不存在。

⚠️ **因此安全网在 main 的性质变了**：不是"补一条被丢的推送"，而是二选一的设计决策 ↓

## 待定的设计决策（建议先问用户/确认）
- **方案甲（收窄/精度）**：main 现在把**所有过屏的非事件项**都静音发 TG，可能偏吵。安全网改造成 = **只让"关注股 且 notable"的非事件项静音发 TG，其余非事件项不发**。即把 `watchlist_safety_net` 当**过滤器**用在 Dispatch 前。
- **方案乙（旁路/补漏）**：保持现有广发不动，安全网额外用途 = **关注股+notable 的新闻即使没过 fast_lane 屏也放行**到静音 TG（防止冷门关注股异动被通用屏筛掉）。需要在 Screen 阶段加"关注股 bypass"。
- **先验证**：`bot/telegram_bot.py::push_alert`(line ~117/121 有 early return) 是否已有隐藏门槛，以及繁忙时段 TG 静音量是否真的很大。若已经不吵，方案甲优先级低。

**我的推荐**：先跑一次验证(繁忙时段 TG 静音发送量 vs 关注股命中量)。若确实广发偏吵→方案甲；若 push_alert 本就有门槛、不吵→做方案乙(关注股 bypass，价值最高：保证你关注的票异动不被通用屏漏掉)。

## 可直接复用（架构无关，从 v1-stable 搬）
1. `engine/event_driven_evaluator.py` 的纯函数 **`watchlist_safety_net(ea, tracked) -> bool`**（is_event=false 且 notable 且 ticker_hint∩tracked）。
2. `engine/relevance.py` 的 **`get_tracked_tickers() -> set[str]`**（watchlist ∪ portfolio，大写）。
3. 单测 `tests/test_watchlist_safety_net.py`。
4. **`EventAssessment.notable` 字段 + prompt 改动**：`config/prompts/event_driven_v1.txt` 里 is_event=false 也要求 LLM 输出 `ticker_hint` + `notable`(是否实质动作)。**main 的 evaluator 若没有 notable，必须一并加**——这是 V2 说的"设计任务"的核心依赖。

## 落地点（按方案甲示意）
- `DispatchDecision`(pipeline/item.py) 加 `notable: bool = False` + `is_event: bool = False`。
- `EvaluateStage`：is_event=false 分支把 `notable`/`is_event` 灌进 decision；并在决定"是否让此 NORMAL 项进 TG"处调用 `watchlist_safety_net`。
- 若走"过滤"：给 `TelegramChannel` 或 Dispatch 前加一条 —— NORMAL 且非 safety_net 命中 → 不发 TG（手机逻辑不动）。
- 手机严格性**天然满足**（Pushover 只认 CRITICAL/IMPORTANT），无需额外保护。

## 验证
- 单测：复用 test_watchlist_safety_net + 新增 DispatchStage/EvaluateStage 的 notable 分支测试。
- 真实 LLM 验收(照 v1 的 `scripts/accept_watchlist_safety_net.py`)：TSLA 调价→命中；El Nino→不命中；Teva→ticker 正确且 notable=false 不命中。
- 部署后现场：查日志确认关注股 notable 项静音到 TG、手机不响。

## 一句话给 V2
`watchlist_safety_net`/`get_tracked_tickers`/notable-prompt 这三块纯逻辑直接搬；但"挂哪、是过滤还是旁路"是 main 特有的设计决策，取决于 main 当前 TG 广发到底吵不吵——**先验证再定方案甲/乙**，别照 v1"补推送"的语义做。
