# SPEC：深度分析卡片在编造行情数据（deep-analysis stale/fabricated data）

> 类型：故障诊断 + 修复契约（§5 分工——V1 诊断+实测+出规格，V2 在 main 流水线实现）
> 出处：V1 窗口（v1-stable）诊断，2026-07-10
> 归属实现：**V2 / main**（改动 `engine/deep_lane.py`，属 main 流水线，§6）
> 严重度：**高**——假行情驱动了真实交易建议（做空 META），用户若照做即反向操作

---

## 1. 背景（什么坏了）

用户反馈：新闻卡片"深度分析"里的股价涨跌幅全错，甚至方向反了。

**样本 id=3340**（TG 卡片，标题 "Micron's $250 Billion Bet... Pepsi and Levi Get Punished Anyway"）深度分析原文节选：
> META因宏观逆风与消费疲软被空头打压，**盘前下跌7.64%至649.2美元，跌破20日均线**。… **做空META**，目标580美元，止损670。

## 2. 实测证据（V1 已双源核实）

抓取时刻两个独立源（Finnhub 实时 + yfinance）**完全一致**，与卡片逐条对照：

| 股票 | 卡片声称 | 真实（Finnhub+yfinance） | 判定 |
|------|---------|--------------------------|------|
| **META** | **-7.64%** @ $649.2 | **+4.70%**（盘前 +3.68% @ $654.7，昨收 603.12） | 🔴 **方向反了** |
| MRVL | +3.75% | +4.99% | ❌ 幅度错 |
| LITE | +9.63% | +11.13% | ❌ |
| WOLF | +3.12% | +3.88% | ❌ |
| BABA | +4.51% | +1.98% | ❌ |
| SMR | +3.54% | +3.08% | ❌ |

**特征**：方向对 5/6（芯片股确实是上涨日）、幅度全是假的、META 编反。这是"照新闻语气猜数、而非读真实行情"的典型，**不属于任何真实时点**（对上用户"现在盘前和昨日都对不上"）。$649.2 需在"昨收≈$703"时才等于 -7.64%，而真实昨收是 603.12 → 数据是编的。

**时序实测**（本地，同 yfinance 源）：
```
[download 90d 8只]  2.4s
[.info x6 逐只]      4.8s
TOTAL               7.3s   ← 超时预算 _ENRICH_TIMEOUT = 8.0s
```
7.3s 卡在 8s 悬崖边。生产 ECS 网络/磁盘更慢（参见 IOPS 隐患），**必然经常超时**。这解释了"有时对、有时错"的间歇性。

## 3. 根因链（已坐实，附 file:line）

1. `engine/deep_lane.py:566-572` — `_call_llm` 用 `asyncio.wait_for(self._fetch_market_enrichment(...), timeout=_ENRICH_TIMEOUT)` 抓行情，`_ENRICH_TIMEOUT = 8.0`（`:37`）。
2. `engine/deep_lane.py:575-576` — 超时后：
   ```python
   except asyncio.TimeoutError:
       logger.debug("Market enrichment timed out — proceeding without it")
   ```
   **静默丢弃行情**（debug 级，生产日志级别通常看不见），LLM **零实时数据**继续分析。
3. `engine/deep_lane.py:56`（prompt）— 防幻觉是**软约束**：
   > Only quote numbers that are explicitly provided in the market data above. If no real-time data is available, say "需查当前价格" rather than guessing.
   DeepSeek **无视此约束**，顺着新闻文本语气**凭空编造**具体价格/涨跌/交易建议。
4. `engine/deep_lane.py:204-214` — 编出的 `llm_analysis` 照常落库并推送，无任何校验/时间戳。

**一句话**：抓数据超时 → 静默无数据 → 软约束拦不住 → LLM 编数字 → 假建议入库推送。

## 4. 修复契约（要实现成什么样）

按优先级，**①可先单独上线（小改动、高价值），②③④随后**：

### ① 硬门禁（最高优先）
**拿不到真实行情时，代码级禁止 LLM 输出任何具体价格 / 涨跌幅 / 交易建议。**
- 判定"拿到了行情" = enrichment 字符串非空且含有效价格行。
- 无行情时二选一：
  - **(推荐)** 在 prompt 里注入硬指令 + 占位："本条无实时行情数据，禁止给出任何具体价位、涨跌幅或买卖建议；只做定性事件解读。" 并在卡片顶部打 `⚠️ 行情数据缺失` 横幅。
  - 或整卡降级：`needs_deep` 项无行情则跳过 LLM 数值分析，仅保留事件摘要。

### ② 输出校验（防漏网幻觉）
LLM 产出后，**扫描其中每个 `$价格` 和 `±x.xx%`，必须能在喂进去的行情串里匹配到**；对不上的数字 → 打回重生成一次，或删除该句 + 记 WARNING。这是即使①放行了部分数据、也兜住"半真半编"的最后一道。

### ③ 数据源与超时（治本）
- **Finnhub 设为主源**（实时、有 key、快——单次报价远快于 yfinance 逐只 `.info` 的 4.8s），yfinance 只用于算均线/历史。
- 或：并发抓取（当前 `.info` 是串行逐只）+ 缓存（同一 ticker 短 TTL）+ 拆分预算（先拿报价 3s、再补均线）。
- 目标：常态在预算内完成；实在拿不到就走①，绝不静默编。

### ④ 可见化
- `575-576` 的超时日志 **debug → WARNING**（出事能在生产日志看见）。
- 卡片显示**数据时间戳** + 用可靠源判 marketState（盘前/盘中/盘后），旧卡片不许假装实时。

## 5. 测试用例（TDD，测试禁用真实推送凭证）

| # | 场景 | 断言 |
|---|------|------|
| 1 | enrichment="" (模拟超时/无数据) → 跑深度分析 | 输出**不含任何 `$价格` / `%`**；含"行情缺失"标记；**不含交易建议**（做多/做空/目标价/止损） |
| 2 | enrichment 提供真实数字 → LLM 引用 | LLM 文本里每个 `$/%` 都能在 enrichment 串里匹配到（输出校验通过） |
| 3 | enrichment 提供 META +4.70%，但 LLM 硬编 -7.64% | 输出校验**捕获不匹配** → 打回/删除 |
| 4 | 计时：N 只股 enrichment | 在预算内完成 **或** 优雅降级（走①），不静默丢弃、不抛未捕获异常 |
| 5 | 超时发生 | 产生 **WARNING** 级日志（非 debug） |

新增 `tests/test_deep_analysis_grounding.py`；在 `config/module_registry.json` 挂到 `engine/deep_lane.py` 的 `tests`（注意该 JSON 是 UTF-8，Windows `open()` 需显式 `encoding='utf-8'`）。

## 6. 部署 & 回滚（§1 / §1b）

1. 本地 TDD 绿 + registry-mapped 测试全绿。
2. **对抗式核实子 agent**：构造"无行情"与"行情齐全"两类新闻，确认①硬门禁不误伤正常卡、②不漏放幻觉数字（quality-gate 要求）。
3. `deploy-shadow.sh` 影子容器试跑，抽查若干卡片：有行情的数字对得上真实报价、无行情的不再出现具体数。
4. 部署前打回滚 tag：`docker tag docker-news-monitor docker-news-monitor:rollback-pre-deepground`。
5. `git push origin main` → ECS `git fetch && checkout origin/main -- engine/deep_lane.py ... && rebuild`。

## 7. 临时缓解（V2 修好前）

深度分析卡里的**具体股价、涨跌幅、买卖建议不可信**；事件本身的定性方向可参考。建议先单独快上**契约①硬门禁**止血，再做③数据源治本。

---
**交接完成。** V1 侧诊断+双源核实+时序实测已做完；实现/测试/部署归 V2/main。疑问回本 SPEC 或 v1-stable SESSION/HISTORY。
