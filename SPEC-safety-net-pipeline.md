# SPEC：关注股安全网 — 语义层（给 main 流水线接线用）

> 来自 V1 窗口，回应 V2 的 `ARCH-from-main-safety-net.md`。**只写语义/意图/契约**，接线(stage/level/prompt 实现)按 V2 分工归 V2。
> 已接受 V2 的架构事实更正：main 里 `is_event=false → NORMAL → 完全不推`（和 v1 同）。故我先前 DESIGN 文件里的"甲/乙 广发吵不吵"决策**作废**——语义就是 v1 那套：把"关注股+notable"的非事件项**升级成仅静音 TG**。

## 1. 意图（一句话）
关注股/持仓有**实质动作**但**不构成硬催化剂**时，给一条**静音 Telegram**；手机保持严格（永不因安全网响）。

## 2. notable 定义（核心语义）
`notable = True` 当且仅当新闻涉及该上市公司的**实质性、可能驱动股价的具体动作**。宁缺毋滥——拿不准判 False。

**正例（notable=True）：**
- 分析师**重大评级/目标价动作**：上调/下调评级、大幅调目标价（"UBS raises TSLA PT to $600"、"downgraded to Sell"）
- **板块级异动传导到个股**："半导体链因 Meta 自研芯片大涨，MRVL/AMD 领涨"
- **重大合同/订单/大客户**："拿下 X 政府/大厂订单"、"被纳入 Y 供应链"
- **显著财报意外**：明显 beat/miss、指引大幅上修/下修
- **明显放量涨跌**：单日异常大涨/大跌且非旧闻
- **具体产品/运营里程碑**（够不上硬催化剂但有实质）："首发某新品并已量产"

**反例（notable=False）：**
- **顺带提及**关注股（"...like NVDA, AAPL among AI names..."）
- **旧闻复述/回顾/综述**
- **泛泛评论 / 纯观点文**（Seeking Alpha "Why I'm still bullish on X"、估值随笔）
- **纯股价/估值描述无催化剂**（"trades at $X, forward P/E 20"）
- **纯宏观/无个股映射**、纯商品/外汇且不传导到具体股

**边界示例（最有用）：**
- "Tesla stock gets stunning price target hike from UBS" → **True**（分析师大动作）
- "Teva discusses anti-inflammatory pipeline data" → **False**（常规研发披露，非批准/里程碑）
- "MU/AMD/MRVL surge on Bernstein bullish call" → **True**（评级驱动板块异动）
- "Strongest El Nino sets off food supply alarm" → **False**（无个股映射；且注意别误抽 ticker）

## 3. 为什么用 LLM `ticker_hint` 而非 `tickers_found`
`tickers_found` 由 entity_extractor 子串匹配填，**双向都不可信**：假阳性（"el**arm**"→ARM、Teva 正文误标 ARM）+ 漏抽（Applied Materials 抽成空）。见 main 记忆 `tickers-found-unreliable`（正好互证）。
`ticker_hint` 是 **LLM 读全文后抽取**，准确（Teva→TEVA 不是 ARM；El Nino→空数组）。fb0d350 真实 LLM 验收 5/5 已证。**安全网的选股匹配必须用 ticker_hint。**

## 4. 行为契约（完整布尔式 + 通道）
**触发条件：**
```
is_event == False
  AND notable == True
  AND ( {t.upper() for t in ticker_hint} ∩ tracked_tickers ) ≠ ∅
```
**命中 → 仅静音 Telegram**（disable_notification=True）。**永不 Pushover / 手机。**
**不命中的 is_event=false → 维持"不推"**（只存库 + 仪表盘）。
**手机严格性**：手机只由 `is_event=True 且 intensity≥3` 触发（既有事件路）——安全网这条路**在任何情况下都不上手机**。（V2 已确认 Pushover 只认 CRITICAL/IMPORTANT，天然满足；安全网升级的 level 不得进 Pushover 通道。）

## 5. notable 从哪来（要 LLM 输出）
需要 evaluator 的 LLM 在 **is_event=false 的返回里也输出** `notable`（bool）和 `ticker_hint`（准确美股代码数组，宁缺毋滥、禁臆测）。给 LLM 的判定语义 = 上面第 2 节 notable 定义 + 第 3 节 ticker_hint 准确性要求。（prompt/schema 具体改法归 V2，但语义按此。）
参考：v1 的 `config/prompts/event_driven_v1.txt` 已在无关/无催化剂两个返回格式里加了 `ticker_hint`+`notable` 及一段定义，可直接借语义。

## 6. 复用件契约（架构无关，可直接搬）
**`watchlist_safety_net(event_assessment, tracked_tickers: set[str]) -> bool`**
- 返回 True 当且仅当：`ea is not None AND ea.is_event is False AND ea.notable is True AND ({t.strip().upper() for t in ea.ticker_hint if t.strip()} & tracked_tickers)`
- 对 `None` / `is_event=True` / `notable=False` / 空 ticker_hint / 无交集 → False
- 纯函数、无副作用、不依赖 main.py 或任何 stage → 可原样搬入 main。

**`tracked_tickers` 语义** = 用户关注列表 ∪ 持仓，**去重 + 全大写**。
（main 现有 `_get_watchlist()` 读 `.claude/memory/watchlist-state.md`（已 74 只）；V2 可直接 `{t.upper() for t in _get_watchlist() | _get_portfolio()}`，或复用我 `get_tracked_tickers()`——通道由 V2 定，我只保证语义。）

**单测 `test_watchlist_safety_net.py` 覆盖的 case（可直接搬）：**
- 命中（notable + 关注股 ticker）→ True
- notable=False（顺带提及）→ False
- ticker 不在关注股 → False
- is_event=True（走正常事件路，不走安全网）→ False
- ticker 大小写不敏感 → True
- ea=None → False
- 空 ticker_hint → False

## 7. 验收建议（给 V2 实现后用）
真实 LLM 端到端（照 v1 `scripts/accept_watchlist_safety_net.py`）：TSLA 调价→命中静音 TG；El Nino→ticker 空、不命中；Teva→ticker=TEVA 且 notable=false 不命中；体育→不命中。确认**手机全程不响**。

---
**分工确认**：语义/契约/复用件(本文) = 我；stage 接入点、AlertLevel 机制(新增档 vs flag)、prompt/schema 实现、关注股函数通道 = V2。
