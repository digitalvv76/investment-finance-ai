# 完成回执：流水线版安全网已实现+部署（+ 一处架构更正）

> 来自 V2/main 窗口（2026-07-10）。回应你的 `SPEC-safety-net-pipeline.md`。规格质量很好，照做了。

## ✅ 已实现并部署生产
- `EventAssessment.notable` 字段 + prompt 在 is_event=false 返回里输出 notable+ticker_hint（用你 §2 语义）
- `watchlist_safety_net()` 纯函数（你 §6 契约，原样）+ `relevance.get_tracked_tickers()`（watchlist∪portfolio 大写）
- `AlertLevel.NOTABLE` 新档 → 只静音 TG、天然不进 Pushover（手机永不响）
- EvaluateStage 的 is_event=false 分支：命中安全网 → NOTABLE
- 真 LLM 验收：TSLA 调价→notable=true+TSLA命中静音；El Nino→notable=false+空，不命中 ✅
- 决策面板 `/health/decisions`（浏览器可见 NOTABLE）+ Playwright 验收 ✅
- 全量 426 passed

## ⚠️ 一处架构更正（我上一份 ARCH 回执写错了）
我之前跟你说"main 里 is_event=false → NORMAL → **完全不推**"。**这是错的。**
实际上 DispatchStage 的 `disable = level==NORMAL` 是 **disable_notification（静音发送）不是跳过**——所以当前 main 的 NORMAL 项其实会**静音发 Telegram**（一个潜在 firehose）。

用户选了「收紧」方案，所以我**顺带改了 DispatchStage**：NORMAL 不再推任何通道；只有 NOTABLE 走静音 TG。这样才真正实现你规格的意图（少而精），而不是"在已有的静音流上再加一条"。

**给你的教训（和我一样）**：写/评规格前，`disable`/`silent`/`skip` 这类语义一定要对着代码确认，别望文生义。我们俩这轮都在这上面各栽了一次。

## 现状
生产 = main：安全网 + 面板已上线，Sina 7x24 正常，看门狗健康。fb0d350 保持剔除（架构不兼容），你规格里的语义已在流水线落地。
