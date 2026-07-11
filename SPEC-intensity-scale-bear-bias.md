# SPEC — intensity 强度标尺"利好偏置"修正（利空事件被顶格误拉警笛）

> 交接：**V1 → V2**（诊断+语义契约由 V1 出；prompt 属 main 流水线 = V2 地盘，§6）
> 日期：2026-07-11 · 分支信道：v1-stable（V2 会话开始读 `origin/v1-stable`）
> 归属实现：V2 / main。V1 不在本窗口改 main（COLLAB-PROTOCOL §3/§6）。

## 1. 缺陷（已在 main 真实代码坐实，非 v1-stable 假设）

`event_driven_v1.txt` 第三步 `intensity` 1-5 标尺**整条按"利好暴涨"写**。
main 当前原文（`git show origin/main:news-monitor/config/prompts/event_driven_v1.txt` 第38行）：

> `intensity`：1-5 星。**5=极可能引发板块级暴涨；4=大概率个股暴涨**；3=明显异动；2=温和提振；1=短期小幅波动。

档位映射（`event_driven_evaluator.py:59-65`，main 一致）：`intensity>=5 → critical → 手机警笛`。

**后果**：利空/避险事件（制裁、管制、暴雷、降维打击）**没有对应档位**，LLM 只能按"剧烈程度"往利好尺子顶端硬套 → 一个下行事件也能拿满分 5 → 拉手机警笛。

## 2. 实测证据（生产真实过评）

- **news_id = 3612**（cal-01，见 `data/training/catalyst-cases-negative.jsonl`）
- 新闻：OpenAI/谷歌被曝向五角大楼黑名单中资企业新加坡子公司供 AI。**利空/避险向**（合规审查/制裁风险 → 板块做空）。
- 系统实际：`catalyst_types=[1,2] intensity=5 → CRITICAL → 手机警笛`。
- 应为：`important`（上手机、不拉警笛）/ intensity 3。三条降级理由：①`reportedly` 二手非官方；②GOOGL/MSFT 万亿巨头，单条合规传闻难成板块级异动；③**利空被硬塞进利好标尺顶格**（本 SPEC 要修的系统性根因）。

## 3. 修正契约（V2 落地，主改 prompt）

**主修（系统性根因）——intensity 标尺改为方向中性的"波动剧烈程度"，并显式给出利空档位样例：**

建议新措辞（V2 可润色，语义为准）：
> `intensity`：1-5 星，度量**预期价格波动的剧烈程度（不分涨跌）**。
> 5 = 板块级剧烈波动（暴涨 **或** 避险抛售/暴跌）；4 = 个股大幅波动（暴涨或暴跌）；3 = 明显异动；2 = 温和变动；1 = 短期小幅波动。
> `direction` 单独判涨/跌（新增或复用 sentiment），**强度与方向解耦**。

这样利空事件按自己的剧烈程度评级，不再靠类比利好顶格。

## 4. ✅ 渠道决策（owner 已拍板 2026-07-11：**方案 B**）

强度方向中性后，利空也可能评到 5。渠道规则**锁定为 B（利空降一档 + 命中关注股才升级，但传闻不升级）**：

- `direction=up`（利好）：维持现状，`intensity>=5 → critical → 手机警笛`。
- `direction=down`（利空）：**手机最高到 `important`（高优提醒、不拉警笛）**，即利空 5 星映射 important 渠道，不发 Pushover emergency。
- **利空升级回 critical/警笛的唯一条件（两者同时满足）**：
  1. `losers ∩ tracked_tickers`（持仓 ∪ 关注股，复用 `get_tracked_tickers()`）非空 —— 砸到你的钱；**且**
  2. 事件**已确认**（非 `reportedly`/传闻/未证实）—— 确定性够。

> ⚠️ **为什么必须加第 2 条（实现别漏）**：cal-01 的 losers=[GOOGL, MSFT]，而 **GOOGL 就在关注股里**（`watchlist-state.md:41`）。若只按"利空命中关注股→升级"，cal-01 会被重新拉回 critical，**违反 §6 验收锚点**。第 2 条"传闻不升级"正好挡住：cal-01 是 `reportedly` 二手 → 不满足 → 保持 important。此条与 §5 的信源置信度门槛是同一根因，建议一并落地。

## 5. 次要硬化（可选，二期）

- **确定性/信源门槛**：`reportedly`/未证实传闻 + 万亿市值标的 → intensity 打折。现 prompt 只有"市场预期充分度"，无信源置信度维度。
- 与 `SPEC-stale-event-downgrade.md`（时效降级）正交：那管"旧闻降级"，本 SPEC 管"利空标尺缺失"。两者叠加才完整。

## 6. 验收锚点（A3 回归，硬性）

- **cal-01 / news_id=3612**：改后**不得判 critical**（目标 important）。判成 critical = 回归。
  - ⚠️ 陷阱：losers=[GOOGL,MSFT]，**GOOGL 在关注股内** → 必须靠 §4 第 2 条"传闻不升级"挡住，否则会被"利空命中关注股→升级"重新拉成 critical。此锚点专门盯这条交互。
- **利空命中关注股 + 已确认**（构造用例：关注股确认级利空，如 portfolio/watchlist 内个股确认下调指引/重大合同流失）：**应**升级 critical/警笛（B 的升级路径正常工作）。
- 取一条**确认的**利好板块级事件（如 catalyst-cases.jsonl 中 gov 高优例）：仍应 5/critical，**别把利好档误伤降级**。
- 校准素材：`data/training/catalyst-cases-negative.jsonl`（N1-N5 镜像 + cal-01）已备好，可作少样本/回归集。

## 7. 归属与信道

- prompt (`config/prompts/event_driven_v1.txt`) + evaluator = **main 流水线 = V2**。
- V1 只出本 SPEC（语义契约），不 cherry-pick 进 main（§3）。
- V2 落地后请写 `REVIEW-intensity-scale-bear-bias.md` 或在 SESSION 回执；生产走 §1 git 部署，V1 不碰 live。
