---
name: daily-briefing
description: |-
  Automated daily market briefing. Use when the user wants a morning briefing, market overview,
  or daily summary covering indices, portfolio, signals, economic events, and news.
metadata:
  type: project
  triggers:
    - briefing
    - daily
    - 早报
    - 日报
    - morning
    - 每日
    - market overview
    - 市场概览
---

# Daily Market Briefing Agent Workflow

Generate a comprehensive daily market briefing covering global markets, portfolio status,
active signals, and key events.

## Workflow

### Step 0: Load State (Before all data fetching)
Load cross-skill state to understand the current context:
1. Read `.claude/memory/portfolio-state.md` — portfolio snapshot and risk alerts
2. Read `.claude/memory/watchlist-state.md` — latest watchlist prices and signals
3. Read `.claude/memory/active-signals.md` — active trade signals from quant-strategy
4. Read `data/watchlists/default.json` — the ticker universe to cover
5. **If any file is missing**, skip gracefully and note the gap in the briefing
6. **If any file is >24 hours stale**, include a warning: "⚠️ [file] 数据已过期 (X 小时前更新)"

### Step 1: Global Market Snapshot (Fetch in Parallel)
For each major market, get the latest session data:

**US Markets:**
- S&P 500, Nasdaq, DJIA: last close, % change, volume
- Sector performance: best/worst 3 sectors
- VIX: current level and change
- US Dollar Index (DXY)

**China/HK Markets:**
- 上证指数, 深证成指, 沪深300, 创业板指
- 恒生指数, 恒生科技指数
- 北向资金净流入/流出
- 人民币汇率 (USD/CNY)

**Crypto Markets:**
- BTC, ETH: price, 24h change, dominance
- Total crypto market cap
- Fear & Greed Index

**Commodities & Others:**
- Gold, Crude Oil (WTI), Copper
- US 10Y Treasury yield
- JPY/USD, EUR/USD

### Step 2: Watchlist Update
For each ticker on the user's watchlist:
- Current price and daily change
- Any technical alert triggers (MA crossover, RSI extreme, volume spike)
- Key support/resistance levels tested

### Step 3: Portfolio Status
If user has shared holdings:
- Total portfolio value and daily P&L
- Top winners and losers today
- Any position approaching stop-loss levels
- Dividends or corporate actions today

### Step 4: Active Signals
Review any active trade signals from quant-strategy skill:
- Signals nearing expiration
- Signals that triggered today
- Performance of recently closed signals

### Step 5: Economic Calendar
Key events for today and this week:
- Earnings reports (major companies)
- Economic data releases (CPI, GDP, employment, PMI, FOMC)
- Holidays and market closures

### Step 6: News Digest
Top 5 market-moving news items:
- Global macro
- Sector-specific
- Company-specific (watchlist + portfolio)

### Step 7: Briefing Format

```
# 📊 每日投资简报 — YYYY-MM-DD

## 🌍 全球市场概览
| 市场 | 指数 | 收盘 | 涨跌 | 备注 |
|------|------|------|------|------|
| 美股 | S&P 500 | X,XXX | +X.X% | |
| 美股 | Nasdaq | XX,XXX | -X.X% | |
| A股 | 上证指数 | X,XXX | +X.X% | |
| A股 | 沪深300 | X,XXX | -X.X% | |
| 港股 | 恒生指数 | XX,XXX | +X.X% | |
| 加密 | BTC | $XX,XXX | -X.X% | 恐慌指数: XX |

## 📈 持仓概览
- 总市值: $XXX,XXX (今日 +$X,XXX / +X.X%)
- 今日最佳: [TICKER] +X.X%
- 今日最差: [TICKER] -X.X%
- 止损预警: [TICKER] 距止损位 XX%

## 🎯 活跃信号
| 信号ID | 标的 | 方向 | 入场 | 现价 | 盈亏 | 状态 |
|--------|------|------|------|------|------|------|
| S001 | NVDA | BUY | $120 | $125 | +4.2% | 持有 |

## 📅 今日重要事件
- 09:30 — 美国CPI数据发布
- 盘前 — AAPL 财报
- ...

## 📰 要闻速览
1. **[标题]** — 一句话摘要
2. ...

## ⚡ 今日关注
- 🔴 高优先级: ...
- 🟡 中等关注: ...
- 🟢 持续跟踪: ...

⚠️ 以上信息仅供参考，不构成投资建议。
```

## Step 8: Archive Briefing
After generating the briefing:
1. **Save briefing** to `data/briefings/YYYY-MM-DD.md` (use the briefing date, not generation date)
2. **Update cross-skill memory files** with the latest data gathered during the briefing:
   - `.claude/memory/watchlist-state.md` — refresh with latest prices
   - `.claude/memory/portfolio-state.md` — refresh with today's P&L (if portfolio configured)
   - `.claude/memory/macro-state.md` — refresh with latest macro indicators
3. **Cross-reference active signals** — for each signal in `data/signals/active.json`, check if stop-loss or take-profit was hit today

## Data Source Fallbacks
| Data Needed | Primary Source | Fallback |
|-------------|---------------|----------|
| US indices | `stock-scanner` `tradingview_market_indices` | `finance` `get_market_overview` |
| China/HK indices | `cn-finance` (unavailable) | `stock-scanner` `tradingview_quote` with exchange prefix |
| Crypto prices | `stock-scanner` `coingecko_coin` | `coingecko` MCP |
| Fear & Greed | `stock-scanner` `sentiment_fear_greed` | N/A |
| Economic calendar | `WebFetch` investing.com | `config/economic-calendar.json` |
| News headlines | `WebSearch` + `WebFetch` | `stock-scanner` `reddit_trending` |

## Configuration
The user can configure:
- **Watchlist**: list of tickers to track daily (edit `data/watchlists/default.json`)
- **Portfolio**: holdings for P&L tracking (edit `data/portfolios/current.json`)
- **Briefing Time**: morning (pre-market) or evening (post-market)
- **Language**: Chinese (default) or English
- **Focus Markets**: which markets to include in the snapshot
