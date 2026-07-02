---
name: quant-strategy
description: |-
  Quantitative strategy development and backtesting workflow. Use when the user wants to
  develop, backtest, or run a trading strategy (momentum, mean-reversion, factor-based, etc.)
  and generate actionable trade signals.
metadata:
  type: project
  triggers:
    - strategy
    - backtest
    - quant
    - signal
    - 策略
    - 回测
    - 量化
    - trade signal
---

# Quantitative Strategy Agent Workflow

Develop, backtest, and run quantitative trading strategies. Output trade signals for human review.

## Workflow

### Step 1: Understand the Strategy Request
Clarify with the user:
- **Strategy type**: momentum / mean-reversion / factor / breakout / pairs-trade / grid / arbitrage
- **Universe**: specific tickers, index components, or sector
- **Timeframe**: intraday / daily / weekly
- **Constraints**: long-only / long-short / max positions / risk limits

### Step 2: Fetch Historical Data
- Use `yfinance` for US stocks, `cn-finance` for A/H-shares, `coingecko` for crypto
- Fetch daily OHLCV for the requested period (minimum 2 years for statistical significance)
- If backtesting on an index basket, fetch all components

### Step 3: Implement Strategy Logic
Common strategies with parameters:

**Momentum Strategy**
- Lookback period: 20/60/120 days
- Entry: price > N-day high OR momentum score > threshold
- Exit: price < M-day low OR momentum reverses

**Mean Reversion Strategy**
- Bollinger Bands (20, 2): buy at lower band, sell at upper band
- RSI: buy when RSI < 30, sell when RSI > 70
- Z-score: buy when z-score < -2, sell when > +2

**Moving Average Crossover**
- Fast MA (e.g., 20-day) crosses above slow MA (e.g., 50-day) → BUY
- Fast MA crosses below slow MA → SELL

**Dual Thrust / Turtle / Breakout**
- Entry at N-day high/low breakout
- ATR-based position sizing (risk 2% per trade)

### Step 4: Run Backtest
Calculate:
1. **Returns**: total return, CAGR, annualized volatility
2. **Risk**: max drawdown, longest drawdown period, VaR (95%), CVaR
3. **Risk-Adjusted**: Sharpe ratio, Sortino ratio, Calmar ratio
4. **Trading**: win rate, profit factor, avg win/loss ratio, number of trades
5. **Benchmark Comparison**: vs buy-and-hold, vs relevant index

### Step 5: Generate Current Signal
Based on latest market data:
- **Signal**: BUY / SELL / WAIT
- **Entry Price**: specific price or range
- **Stop-Loss**: mandatory level (e.g., -2 ATR or -5% from entry)
- **Take-Profit**: target level(s) with partial exit plan
- **Position Size**: Kelly-based or fixed-fraction (max 5% of portfolio)
- **Confidence Level**: based on historical win rate and current setup quality

### Step 6: Output Format

```
# [策略名称] 交易信号

## 策略概述
- 类型: momentum / mean-reversion / ...
- 标的: [TICKER]
- 时间框架: daily

## 回测结果
| 指标 | 策略 | 基准 |
|------|------|------|
| 年化收益 | XX% | XX% |
| 最大回撤 | -XX% | -XX% |
| Sharpe | X.XX | X.XX |
| 胜率 | XX% | - |
| 交易次数 | XX | - |

## 当前信号
- 🟢/🔴/🟡 信号: BUY / SELL / WAIT
- 入场价: $XXX
- 止损: $XXX (-X%)
- 止盈: $XXX (+X%)
- 建议仓位: X% of portfolio

## 风险提示
- 主要风险: ...
- 失效条件: ...

⚠️ 以上为量化模型输出，需人工审核确认后方可执行。不构成投资建议。
```

## Step 7: Persist Signals
After generating signals:
1. **Save active signals** to `data/signals/active.json` — update the `active` array with all currently active signals
2. **Append closed signals** — for any signal that closed this session, append a JSON line to `data/signals/history.jsonl`:
   ```json
   {"id":"SIG-YYYYMMDD-NNN","ticker":"...","direction":"BUY/SELL","strategy":"...","entryPrice":...,"exitPrice":...,"pnlPct":...,"opened":"...","closed":"..."}
   ```
3. **Update signal memory** — refresh `.claude/memory/active-signals.md` with current active signals, recent closures, and updated statistics
4. **Signal ID format**: `SIG-YYYYMMDD-NNN` (e.g., `SIG-20260630-001`)

## Important Rules
- NEVER execute trades automatically. Always present for human approval.
- Always include stop-loss in every signal.
- Position size must not exceed 5% of portfolio per trade (see `config/indicators.json` risk parameters).
- If backtest period < 2 years, warn about limited statistical significance.
- For crypto: mention higher volatility and 24/7 trading considerations.
- Always persist signals after generation so daily-briefing can read them.
