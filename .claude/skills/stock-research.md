---
name: stock-research
description: Use when the user wants stock analysis, research reports, or ratings for individual stocks (US/A-share/HK/crypto). Triggers: "analyze", "research", "分析", "研究", "研报", ticker symbols like NVDA/AAPL/600519.
metadata:
  type: project
  triggers:
    - analyze
    - research
    - 分析
    - 研究
    - stock report
    - 研报
---

# Stock Research Agent Workflow

Perform comprehensive multi-source analysis on a given stock ticker. Produce an
institutional-grade research report with a clear BUY / HOLD / SELL rating.

## ⚠️ MCP Availability (verified 2026-07-01)

Always check this before fetching — status changes over time:

| Server | Status | Use For | Notes |
|--------|--------|---------|-------|
| `yfinance` | ✅ | US stocks | Rate-limited (~25 calls/day). Space out requests. |
| `stock-scanner` | ✅ | US/CN/HK quotes, SEC, Crypto, Options | Primary multi-source. tradingview_* tools may intermittently 500. |
| `fred` | ✅ | Macro indicators (CPI, rates, GDP) | FRED_API_KEY configured. Use `fred_indicator` / `fred_indicator_history`. |
| `finance` | ✅ | US stocks (Alpha Vantage) | Backup for yfinance. `get_stock_quote`, `get_company_overview`. |
| `coingecko` | ⚠️ | Crypto | Redundant with stock-scanner `coingecko_*` tools. |
| `cn-finance` | ❌ | A/H shares | **PyPI package does not exist. Use fallback only.** |
| `sec-edgar` | ⚠️ | Deep SEC filings | Redundant with stock-scanner `edgar_*` tools. |
| `crypto-trade` | ⚠️ | Exchange execution | Requires BINANCE_API_KEY + BINANCE_SECRET_KEY. |

## Workflow

### Step 0: Check MCP Health
Before fetching, run ONE quick smoke test:
- US stocks: try `stock-scanner` `alphavantage_quote` first. If 500/rate-limited, fall back to `finance` `get_stock_quote`.
- A/H shares: **cn-finance is UNAVAILABLE.** Go directly to fallback.
- Crypto: use `stock-scanner` `coingecko_coin` or `crypto_quote`.

### Step 1: Identify the Market
| Ticker Pattern | Market | Primary Source | Fallback |
|---------------|--------|---------------|----------|
| AAPL, TSLA, NVDA, ... | US | `stock-scanner` `tradingview_quote` | `finance` `get_stock_quote` / `yfinance` `get_stock_info` |
| 600xxx, 000xxx, 300xxx | A-Share | `stock-scanner` `tradingview_scan` + SHA/SHE | WebSearch Chinese financial sites |
| 07xxx, 09xxx | HK | `stock-scanner` `tradingview_scan` + HKEX | WebSearch |
| BTC, ETH, SOL, ... | Crypto | `stock-scanner` `coingecko_coin` | `stock-scanner` `crypto_quote` |

### Step 2: Gather Data (Parallel with Rate-Limit Awareness)
Fetch ALL of the following in parallel. **If rate-limited, note it — don't retry more than twice.**

1. **Price & Quote** — current price, day change, volume, market cap
2. **Price History** — last 6 months daily OHLCV for chart context
3. **Company Overview** — sector, industry, description, employees, PE, beta
4. **Financial Statements** — income statement, balance sheet, cash flow (if available)
5. **Technical Indicators** — RSI, MACD, SMA(50/200), Bollinger Bands via `tradingview_technicals`
6. **Analyst Data** — recommendations, price targets (if available)
7. **Recent News** — via `get_yahoo_finance_news` (US) or `WebSearch`
8. **Insider Trading** — via `stock-scanner` `edgar_insider_trades` (US only)
9. **Macro Context** — via `fred_indicator` (fed_funds, cpi, unemployment, treasury_10y)
10. **Sentiment** — via `stock-scanner` `reddit_sentiment` or `reddit_mentions`

### Step 3: Technical Analysis
Calculate and interpret:
- **Trend**: 20/50/200-day moving averages, MACD
- **Momentum**: RSI (14-day), stochastic oscillator
- **Volatility**: Bollinger Bands, ATR (14-day)
- **Volume**: On-Balance Volume, volume vs 20-day average
- **Support/Resistance**: Key levels from recent price action

### Step 4: Fundamental Analysis
- **Valuation**: Compare P/E, P/B, EV/EBITDA to industry averages and 5-year history
- **Growth**: Revenue and EPS growth rates (YoY, QoQ)
- **Quality**: ROE, ROIC, profit margins trend
- **Financial Health**: Debt levels, interest coverage, free cash flow
- **DCF Estimate**: Back-of-envelope DCF using FCF and reasonable growth assumptions

### Step 5: Sentiment & Catalysts
- **News Sentiment**: Summarize recent news tone (positive/negative/neutral)
- **Upcoming Events**: Earnings dates, product launches, regulatory decisions
- **Macro Context**: Relevant macro indicators (interest rates, sector trends, policy)

### Step 6: Risk Assessment
- **Company-specific**: concentration risk, litigation, regulation, key-person risk
- **Market risk**: beta, sector correlation, liquidity
- **Tail risks**: black swan scenarios, worst-case drawdown estimate

### Step 7: Generate Report
Structure the final report as:

```
# [TICKER] 深度研究报告

## 1. 执行摘要 (Executive Summary)
- 评级: BUY / HOLD / SELL
- 目标价: $XXX (X% upside/downside)
- 3句话核心逻辑

## 2. 公司概览 (Company Overview)
## 3. 技术分析 (Technical Analysis)
## 4. 基本面分析 (Fundamental Analysis)
## 5. 估值分析 (Valuation)
## 6. 风险提示 (Risk Factors)
## 7. 催化剂与时间线 (Catalysts & Timeline)
```

## Step 8: Persist State
After generating the report:
1. **Save research report** to `data/reports/<TICKER>-<YYYY-MM-DD>.md`
2. **Update report index** — append a row to `data/reports/ARCHIVE.md`:
   ```
   | YYYY-MM-DD | TICKER | RATING | TARGET | Key thesis in one line |
   ```
3. **Update watchlist state** — refresh the analyzed ticker's row in `.claude/memory/watchlist-state.md` with latest price, RSI, and MA status
4. **If you changed your rating**, note the previous rating (if any) from the archive for comparison

## Data Source Fallbacks (verified 2026-07-01)
If a primary source fails, use these fallbacks in order:

| Data Needed | 1st Choice | 2nd Choice | 3rd Choice |
|-------------|-----------|------------|------------|
| US stock quote | `stock-scanner` `tradingview_quote` | `finance` `get_stock_quote` | `yfinance` `get_stock_info` |
| US fundamentals | `yfinance` `get_stock_info` | `stock-scanner` `alphavantage_overview` | `finance` `get_company_overview` |
| US price history | `yfinance` `get_historical_stock_prices` | `stock-scanner` `alphavantage_daily` | — |
| A/H shares | `stock-scanner` `tradingview_scan` (SHA/SHE) | `stock-scanner` `tradingview_quote` (SSE:xxx) | WebSearch |
| Crypto price | `stock-scanner` `coingecko_coin` | `stock-scanner` `crypto_quote` | `coingecko` MCP |
| Technical indicators | `stock-scanner` `tradingview_technicals` | manual calculation from OHLCV | — |
| SEC filings | `stock-scanner` `edgar_company_filings` | `stock-scanner` `edgar_search` | — |
| Macro indicators | `stock-scanner` `fred_indicator` (✅ verified) | `WebSearch` + `sentiment_fear_greed` | — |
| News (US) | `yfinance` `get_yahoo_finance_news` | `WebSearch` | `stock-scanner` `reddit_trending` |
| Reddit sentiment | `stock-scanner` `reddit_sentiment` | `stock-scanner` `reddit_mentions` | — |
| Options flow | `stock-scanner` `options_unusual_activity` | `stock-scanner` `options_chain` | — |

**Rate Limit Rules:**
- `yfinance`: max 25 calls/day. Batch tickers where possible.
- `finance` (Alpha Vantage): 5 calls/min, 25/day. 
- `stock-scanner` tradingview_*: may return INTERNAL_ERROR. Wait 2s and retry ONCE.
- If all sources fail for a data point, report "数据暂不可用" rather than fabricating.

## Important
- Always end with: "⚠️ 免责声明：本报告仅供教育和研究目的，不构成投资建议。Educational/research use only. Not financial advice."
- If a data source is unavailable, note it explicitly rather than fabricating data — use the fallback table above
- For Chinese stocks, generate the report primarily in Chinese
- For US/Crypto, generate the report in Chinese with English key terms
