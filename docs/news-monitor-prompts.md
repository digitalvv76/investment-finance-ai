# News Monitor — Prompt 文档

> 本文档记录 news-monitor 中所有 LLM prompt 的定义、用途、模板变量和调用参数。
> 最后更新: 2026-07-07

---

## 目录

1. [总览](#总览)
2. [Prompt 详细说明](#prompt-详细说明)
   - [1. ANALYSIS_PROMPT — 深度分析 (Flash Note)](#1-analysis_prompt--深度分析-flash-note)
   - [2. impact_v1.txt — 市场影响评估](#2-impact_v1txt--市场影响评估)
   - [3. Actionability Review — 推送二次审核](#3-actionability-review--推送二次审核)
   - [4. CURATOR_PROMPT — 新闻策展评分](#4-curator_prompt--新闻策展评分)
   - [5. EXTRACT_PROMPT — 知识提取](#5-extract_prompt--知识提取)
   - [6. TRANSLATE_PROMPT — 标题翻译](#6-translate_prompt--标题翻译)
   - [7. DEFAULT_PROFILE — 默认用户画像](#7-default_profile--默认用户画像)
   - [8. 校准提示 (Calibration Hint)](#8-校准提示-calibration-hint)
   - [9. 历史事件示例 (Few-Shot Examples)](#9-历史事件示例-few-shot-examples)
   - [10. 用户自定义分析框架](#10-用户自定义分析框架)
3. [LLM 调用汇总](#llm-调用汇总)
4. [模型参数速查](#模型参数速查)
5. [调用链路图](#调用链路图)

---

## 总览

| # | 名称 | 文件 | 用途 | 提供商 |
|---|------|------|------|--------|
| 1 | `ANALYSIS_PROMPT` | `engine/deep_lane.py:43` | 买方分析师 Flash Note | DeepSeek / Anthropic |
| 2 | `impact_v1.txt` | `config/prompts/impact_v1.txt` | 市场影响 JSON 评分 | DeepSeek / Anthropic |
| 3 | `_SYSTEM_PROMPT` | `engine/actionability_review.py:31` | 灰色地带推送审核 | DeepSeek |
| 4 | `_USER_PROMPT_TEMPLATE` | `engine/actionability_review.py:50` | 灰色地带推送审核 | DeepSeek |
| 5 | `CURATOR_PROMPT` | `engine/curator.py:17` | 个性化相关性评分 | DeepSeek |
| 6 | `EXTRACT_PROMPT` | `engine/trainer.py:18` | 文档知识提取 | DeepSeek |
| 7 | `TRANSLATE_PROMPT` | `bot/translator.py:8` | 英→中标题翻译 | DeepSeek |
| 8 | `DEFAULT_PROFILE` | `engine/curator.py:48` | 用户画像 (注入 Prompt 5) | N/A |
| 9 | 校准提示 | `engine/impact_learner.py:32` | 自学习偏差纠正 (注入 Prompt 2) | N/A |
| 10 | 历史示例 | `engine/event_matcher.py:218` | Few-shot 历史先例 (注入 Prompt 2) | N/A |
| 11 | 自定义框架 | `engine/deep_lane.py:415` | 用户自定义 Flash Note 模板 | DeepSeek / Anthropic |

---

## Prompt 详细说明

### 1. ANALYSIS_PROMPT — 深度分析 (Flash Note)

- **文件**: `news-monitor/engine/deep_lane.py` (第 43-66 行)
- **类型**: 模块级字符串常量
- **用途**: 面向用户的深度新闻分析，以买方分析师口吻撰写简短可执行的 Flash Note。由 `DeepLane` 编排器在优先级足够高时调用。
- **用户自定义**: 可通过 Telegram `/analyze set <文本>` 设置自定义框架，存储在 DB preference `analysis_framework` 中，完全替换此 prompt。

**Prompt 正文:**

```
You are a buy-side analyst writing a flash note for a portfolio manager.
Be CONCISE. Be ACTIONABLE. Do NOT write an academic essay.

Title: {title}
Source: {source}
Tickers: {tickers}
Macro indicators: {macro_tags}
Sentiment: {sentiment} (score: {sentiment_score:.2f})

{extra_context}

Write a short flash note in Chinese with exactly these 3 sections. 150-250 words total.

CRITICAL RULES:
- Only quote numbers that are explicitly provided in the market data above.
  If no real-time data is available, say "需查当前价格" rather than guessing.
- ONLY mention tickers listed in the investor's watchlist or the news tickers.
  Do not invent unrelated stocks.
- The "Action" must be ONE recommendation. Pick one and commit.

1. What happened (1-2 sentences)

2. Market impact (2-3 sentences)

3. Action (1-2 sentences)

Confidence: High/Medium/Low
```

**模板变量:**

| 变量 | 来源 | 说明 |
|------|------|------|
| `{title}` | NewsItem | 新闻标题 |
| `{source}` | NewsItem | 新闻来源 |
| `{tickers}` | NewsItem | 相关股票代码 |
| `{macro_tags}` | NewsItem | 宏观标签 |
| `{sentiment}` | 情感分析 | 情感方向 (positive/negative/neutral) |
| `{sentiment_score}` | 情感分析 | 情感分数 (0-1) |
| `{extra_context}` | 运行时构建 | 包含: 投资者持仓/观察列表、知识库上下文、实时市场数据 |

**LLM 参数:**

| 提供商 | 模型 | Temperature | Max Tokens |
|--------|------|-------------|------------|
| DeepSeek | `deepseek-chat` | 0.3 | 1500 |
| Anthropic | `claude-fable-5` | — | 1500 |

**调用位置**: `deep_lane.py` 第 524 行 (DeepSeek) / 第 552 行 (Anthropic)

---

### 2. impact_v1.txt — 市场影响评估

- **文件**: `news-monitor/config/prompts/impact_v1.txt`
- **类型**: 磁盘文件，由 `PromptVersionManager` 加载
- **用途**: 后端影响评估。LLM 评估金融新闻对市场的潜在影响，返回结构化 JSON 用于评分和推送决策。
- **版本管理**: 通过 `PromptVersionManager` 支持版本切换。当前激活版本 `v1`。

**Prompt 正文:**

```
You are a senior macro analyst at a top-tier hedge fund. Your job is to evaluate
the potential MARKET IMPACT of a financial news event. You think in terms of:

1. EVENT TYPE & INHERENT SIGNIFICANCE
   - Monetary policy (FOMC, rate decisions, forward guidance) -> highest impact
   - Geopolitical shocks (war, sanctions, trade war escalation) -> very high impact
   - Major macro data surprises (CPI, NFP, retail sales) -> high impact
   - Corporate earnings / product launches (mega-cap only) -> moderate impact
   - Routine data / minor policy -> low impact

2. SURPRISE MAGNITUDE
   - How far does the actual figure deviate from expectations?
   - A 0.1% CPI miss is noise; a 0.5% miss is a regime change signal.

3. MARKET BREADTH
   - Single stock -> sector -> broad index -> multi-asset (equities+bonds+FX+commodities)
   - Wider breadth = higher impact

4. HISTORICAL PRECEDENT
   - Has a similar event occurred in the past 2 years? What was the market reaction?
   - Use the provided historical examples below as calibration references.
   {historical_examples}

5. CURRENT MARKET CONTEXT
   - Is the market positioned for this? (crowded trades amplify moves)
   - Current VIX / Fear & Greed regime (fear amplifies negative news)
   {market_context}

{calibration_hint}

OUTPUT FORMAT (strict JSON, no markdown wrapping):
{
  "impact_score": <0-100 integer>,
  "confidence": <0-100 integer>,
  "event_category": "<monetary|geopolitical|macro_data|corporate|regulatory|other>",
  "surprise_level": "<expected|minor_surprise|major_surprise|shock>",
  "breadth": "<single_stock|sector|broad_market|cross_asset>",
  "reasoning_chain": ["Step 1: ...", "Step 2: ...", ..., "Step 5: ..."],
  "similar_historical_events": ["Event (approx date): brief impact description"],
  "expected_sectors_affected": ["Technology", "Financials"],
  "expected_asset_moves": {
    "equities": "<direction: up/down/flat> <magnitude: small/moderate/large>",
    "bonds": "<direction> <magnitude>",
    "fx": "<direction> <magnitude>",
    "commodities": "<direction> <magnitude>"
  },
  "calibration_note": "Based on past assessments, this evaluator tends to
    [over/under]estimate [type] events by ~[X] points",
  "analyst_note": "以买方分析师口吻，用2-4句中文写出对此事件的判断..."
}
```

**模板变量:**

| 变量 | 来源 | 说明 |
|------|------|------|
| `{market_context}` | 运行时构建 | 当前 VIX、Fear & Greed、市场定位 |
| `{calibration_hint}` | `ImpactLearner` | 自学习偏差提示 (如 "倾向于高估货币政策事件 ~5 分") |
| `{historical_examples}` | `EventMatcher` | Few-shot 历史类似事件示例 |

**User Prompt** (额外构建):
```
Title: {title}
Source: {source}
Tickers: {tickers}
Macro tags: {macro_tags}
Content: {snippet}  (前 800 字符)
```

**LLM 参数:**

| 提供商 | 模型 | Temperature | Max Tokens | 超时 |
|--------|------|-------------|------------|------|
| DeepSeek | `deepseek-chat` | 0.3 | 1200 | 45s |
| Anthropic | `claude-fable-5` | — | 1200 | 45s |

**调用位置**: `impact_evaluator.py` 第 325 行 (DeepSeek) / 第 345 行 (Anthropic)

**重试策略**: 每个提供商最多 2 次重试

---

### 3. Actionability Review — 推送二次审核

- **文件**: `news-monitor/engine/actionability_review.py` (第 31-57 行)
- **类型**: 模块级字符串常量 (System + User 两部分)
- **用途**: 对边界推送决策 (综合评分 0.30–0.70) 进行快速 LLM 二次审核，防止误报推送。限制每日约 5-10 次调用。

**System Prompt:**

```
You are an investment analyst reviewing whether a news alert should
be pushed to a trader's phone. Your ONLY job is to catch false positives
that the automated system missed.

Reply with EXACTLY ONE WORD: ACTIONABLE or NOT_ACTIONABLE.

The news is ACTIONABLE if ALL of:
- It describes a NEW event (not a recap/summary of something that already happened)
- It describes a concrete ACTION (not a threat/proposal/consideration)
- An investor could TRADE on this right now (specific ticker, sector, or macro instrument)
- If a personnel change, it comes with specific policy implications

The news is NOT_ACTIONABLE if ANY of:
- It's a recap, review, or summary of past events ("monthly review", "year-to-date")
- It's a threat, proposal, or hypothetical ("considering tariffs", "may impose")
- It's purely a personnel appointment without policy action
- It describes a historical event from a different era (2008, 2020, etc.)
- It's about a foreign country's local politics with no global market implication
```

**User Prompt 模板:**

```
News: {title}
Source: {source}
Content: {snippet}

Signal scores: composite={composite:.2f}, timeliness={timeliness:.2f},
  novelty={novelty:.2f}, relevance={relevance:.2f} ({direction})
Event category: {category}

Is this ACTIONABLE?
```

**模板变量:**

| 变量 | 说明 |
|------|------|
| `{title}` | 新闻标题 |
| `{source}` | 新闻来源 |
| `{snippet}` | 内容片段 |
| `{composite}` | 综合信号分数 |
| `{timeliness}` | 时效性分数 |
| `{novelty}` | 新颖性分数 |
| `{relevance}` | 相关性分数 |
| `{direction}` | 信号方向 |
| `{category}` | 事件类别 |

**LLM 参数:**

| 提供商 | 模型 | Temperature | Max Tokens | 超时 |
|--------|------|-------------|------------|------|
| DeepSeek | `deepseek-chat` | 0.0 | 10 | 10s |

**调用位置**: `actionability_review.py` 第 125 行

---

### 4. CURATOR_PROMPT — 新闻策展评分

- **文件**: `news-monitor/engine/curator.py` (第 17-46 行)
- **类型**: 模块级字符串常量
- **用途**: 批量对传入新闻标题进行个性化相关性评分，对比用户兴趣画像。使用语义理解而非关键词匹配。

**Prompt 正文:**

```
You are a personal news curator. Your job is to score how relevant each news
headline is to the user's interests, and assess potential market impact.

=== USER PROFILE ===
{profile_description}

=== LEARNED KNOWLEDGE (from user-provided documents) ===
{learned_knowledge}

=== POSITIVE EXAMPLES (news user found relevant) ===
{positive_examples}

=== NEGATIVE EXAMPLES (news user does NOT want) ===
{negative_examples}

=== SCORING RULES ===
- Score 9-10: Directly about user's core interests. Would be the first thing they read.
- Score 7-8: Clearly relevant. User would want to know.
- Score 5-6: Somewhat relevant. Worth a glance.
- Score 3-4: Tangentially related. Probably skip.
- Score 1-2: Not relevant. Skip.
- Score 0: User explicitly does not want this.
- Consider the LEARNED KNOWLEDGE: if the user has uploaded analysis frameworks
  or investment theses, use them to judge relevance and market impact.

=== NEWS HEADLINES TO SCORE ===
{headlines}

=== OUTPUT FORMAT ===
Return ONLY a JSON array. Each item:
{{"id": <number>, "score": <0-10>, "reason": "<brief Chinese reason>"}}

JSON:
```

**模板变量:**

| 变量 | 说明 |
|------|------|
| `{profile_description}` | 用户兴趣描述 (默认见下方 DEFAULT_PROFILE) |
| `{learned_knowledge}` | 从用户上传文档中提取的知识 |
| `{positive_examples}` | 用户标记为相关的正面示例 |
| `{negative_examples}` | 用户标记为不相关的负面示例 |
| `{headlines}` | 待评分的新闻标题列表 |

**LLM 参数:**

| 提供商 | 模型 | Temperature | Max Tokens |
|--------|------|-------------|------------|
| DeepSeek | `deepseek-chat` | 0.1 | 500 |

**调用位置**: `curator.py` 第 207 行

---

### 5. EXTRACT_PROMPT — 知识提取

- **文件**: `news-monitor/engine/trainer.py` (第 18-29 行)
- **类型**: 模块级字符串常量
- **用途**: 将用户提供的训练文档 (URL/PDF/DOCX/MD/TXT) 摘要为投资洞察，存入策展器的知识库。

**Prompt 正文:**

```
Extract the key investment insights from this article. Focus on:
1. What sectors/stocks are discussed
2. The market thesis or analysis framework
3. How events might impact stock prices
4. Key indicators or signals mentioned

Summarize in 3-5 bullet points in Chinese. Be specific about cause-effect relationships.

Article:
{content}

Key Insights:
```

**模板变量:**

| 变量 | 说明 |
|------|------|
| `{content}` | 文档正文 (前 4000 字符) |

**LLM 参数:**

| 提供商 | 模型 | Temperature | Max Tokens | 超时 |
|--------|------|-------------|------------|------|
| DeepSeek | `deepseek-chat` | 0.3 | 400 | 45s |

**调用位置**: `trainer.py` 第 323 行

---

### 6. TRANSLATE_PROMPT — 标题翻译

- **文件**: `news-monitor/bot/translator.py` (第 8-11 行)
- **类型**: 模块级字符串常量
- **用途**: 将英文金融新闻标题翻译为中文。由 Telegram Bot 和 `AlertDispatcher` 共用。

**Prompt 正文:**

```
Translate this financial news headline to Chinese. Keep it concise and accurate.
Preserve ticker symbols (like NVDA, AAPL) as-is.
Only output the Chinese translation, nothing else.

English: {text}
Chinese:
```

**模板变量:**

| 变量 | 说明 |
|------|------|
| `{text}` | 英文文本 (前 500 字符) |

**LLM 参数:**

| 提供商 | 模型 | Temperature | Max Tokens |
|--------|------|-------------|------------|
| DeepSeek | `deepseek-chat` | 0.1 | 200 |

**调用位置**: `translator.py` 第 43 行

---

### 7. DEFAULT_PROFILE — 默认用户画像

- **文件**: `news-monitor/engine/curator.py` (第 48-64 行)
- **类型**: 字典常量，注入到 `CURATOR_PROMPT` 的 `{profile_description}`
- **用途**: 定义默认的投资者人设。用户可以通过 Telegram `/profile set` 自定义。

**内容:**

```
我是一名全球宏观投资者，关注美联储货币政策、通胀数据、地缘政治风险、
以及大型科技股（尤其是AI和半导体行业）的动态。同时也关注重大市场事件
和系统性风险。

重点关注标的: NVDA, AMD, MSFT, GOOGL, AAPL, TSLA
```

---

### 8. 校准提示 (Calibration Hint)

- **文件**: `news-monitor/engine/impact_learner.py` (第 32-52 行)
- **类型**: 程序化生成，注入到 `impact_v1.txt` 的 `{calibration_hint}`
- **用途**: 分析历史预测误差，检测系统性高估/低估偏差，按事件类别提供校准建议。

**生成逻辑**: `ImpactLearner` 从 DB 读取历史评估记录，计算每个事件类别的平均偏差，生成提示如:

```
Based on past assessments, this evaluator tends to over-estimate
monetary events by ~5 points; under-estimate geopolitical events by ~3 points.
```

回退值: `"No calibration data yet"`

---

### 9. 历史事件示例 (Few-Shot Examples)

- **文件**: `news-monitor/engine/event_matcher.py` (第 218-233 行)
- **类型**: 程序化生成，注入到 `impact_v1.txt` 的 `{historical_examples}`
- **用途**: 从历史事件库中检索类似事件，作为 Few-shot 示例注入影响评估 prompt。

**数据来源**: `config/training_news_events_2026H1.md`

**生成格式:**

```
1. [2026-01-15] CRITICAL -- Description of historical event
   Market reaction: SPX -2.1%, VIX +8.3 to 24.5
   Affected: NVDA, AMD, MSFT
```

**检索逻辑**: 基于新闻文本和事件类别的语义匹配，返回 top 3 最相似历史事件。

---

### 10. 用户自定义分析框架

- **文件**: `news-monitor/engine/deep_lane.py` (第 415-468, 489-507 行)
- **存储**: DB preference key `analysis_framework`
- **用途**: 用户可通过 Telegram `/analyze set <完整 prompt 模板>` 设置自定义分析框架，完全替换 `ANALYSIS_PROMPT`。

**管理方法:**

| 方法 | 说明 |
|------|------|
| `DeepLane.get_framework()` | 获取当前框架 (默认返回 `ANALYSIS_PROMPT`) |
| `DeepLane.set_framework(text)` | 存储自定义框架到 DB |
| `DeepLane.reset_framework()` | 重置为默认 `ANALYSIS_PROMPT` |

**Bot 命令处理**: `bot/handlers.py` 第 466-508 行

自定义模板可使用相同的格式变量: `{title}`, `{source}`, `{tickers}`, `{macro_tags}`, `{sentiment}`, `{sentiment_score}`, `{extra_context}`

---

## LLM 调用汇总

| # | 调用位置 | 文件:行号 | 提供商 | 方法 |
|---|---------|-----------|--------|------|
| 1 | DeepLane 深度分析 | `deep_lane.py:524` | DeepSeek | `chat.completions.create()` |
| 2 | DeepLane 深度分析 | `deep_lane.py:552` | Anthropic | `messages.create()` |
| 3 | ImpactEvaluator | `impact_evaluator.py:325` | DeepSeek | `chat.completions.create()` |
| 4 | ImpactEvaluator | `impact_evaluator.py:345` | Anthropic | `messages.create()` (via `to_thread`) |
| 5 | ActionabilityReview | `actionability_review.py:125` | DeepSeek | `chat.completions.create()` |
| 6 | Curator 策展 | `curator.py:207` | DeepSeek | `chat.completions.create()` |
| 7 | Trainer 知识提取 | `trainer.py:323` | DeepSeek | `chat.completions.create()` |
| 8 | Translator 翻译 | `translator.py:43` | DeepSeek | `chat.completions.create()` |

---

## 模型参数速查

| 组件 | 模型 | Temperature | Max Tokens | 超时 | 重试 |
|------|------|-------------|------------|------|------|
| DeepLane (DeepSeek) | `deepseek-chat` | 0.3 | 1500 | — | — |
| DeepLane (Anthropic) | `claude-fable-5` | — | 1500 | — | — |
| ImpactEvaluator (DeepSeek) | `deepseek-chat` | 0.3 | 1200 | 45s | 2次 |
| ImpactEvaluator (Anthropic) | `claude-fable-5` | — | 1200 | 45s | 2次 |
| ActionabilityReview | `deepseek-chat` | 0.0 | 10 | 10s | — |
| Curator | `deepseek-chat` | 0.1 | 500 | — | — |
| Trainer | `deepseek-chat` | 0.3 | 400 | 45s | — |
| Translator | `deepseek-chat` | 0.1 | 200 | — | — |

---

## 调用链路图

```
新闻摄入 (IngestStage)
    │
    ├─→ Curator (CURATOR_PROMPT)
    │   └─ 个性化相关性评分 → 过滤低相关性新闻
    │
    ├─→ Translator (TRANSLATE_PROMPT)
    │   └─ 英→中标题翻译
    │
    └─→ Trainer (EXTRACT_PROMPT)  [离线/异步]
        └─ 用户文档 → 知识提取 → 知识库

评分阶段 (EvaluateStage)
    │
    ├─→ ImpactEvaluator (impact_v1.txt)
    │   ├─ ImpactLearner → {calibration_hint}
    │   └─ EventMatcher → {historical_examples}
    │   └─ 输出: JSON 影响评分 (0-100)
    │
    └─→ ActionabilityReview (_SYSTEM_PROMPT + _USER_PROMPT_TEMPLATE)
        └─ 触发条件: 综合评分 0.30-0.70 (灰色地带)
        └─ 输出: ACTIONABLE / NOT_ACTIONABLE

深度分析阶段 (DeepStage)
    │
    └─→ DeepLane (ANALYSIS_PROMPT 或用户自定义框架)
        ├─ 注入: 持仓/观察列表 + 实时行情 + 知识库
        └─ 输出: Flash Note (中文, 150-250 字)
        └─ 回退: 规则生成 (无 LLM 可用时)
```

---

## 相关文件索引

| 文件 | 说明 |
|------|------|
| `news-monitor/engine/deep_lane.py` | ANALYSIS_PROMPT, 自定义框架管理, DeepSeek/Anthropic 调用 |
| `news-monitor/engine/impact_evaluator.py` | impact_v1.txt 加载, PromptVersionManager, LLM 调用 |
| `news-monitor/engine/actionability_review.py` | 推送二次审核 prompt 和调用 |
| `news-monitor/engine/curator.py` | CURATOR_PROMPT, DEFAULT_PROFILE, LLM 调用 |
| `news-monitor/engine/trainer.py` | EXTRACT_PROMPT, LLM 调用 |
| `news-monitor/bot/translator.py` | TRANSLATE_PROMPT, LLM 调用 |
| `news-monitor/engine/impact_learner.py` | 自学习校准提示生成 |
| `news-monitor/engine/event_matcher.py` | 历史事件 Few-shot 示例生成 |
| `news-monitor/config/prompts/impact_v1.txt` | 影响评估 System Prompt 磁盘文件 |
| `news-monitor/config/training_news_events_2026H1.md` | 历史事件库 (供 EventMatcher 检索) |
| `news-monitor/bot/handlers.py` | Telegram `/analyze set` 自定义框架处理 |
