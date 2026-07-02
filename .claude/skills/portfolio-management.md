---
name: portfolio-management
description: |-
  Portfolio analysis, risk management, and rebalancing workflow. Use when the user wants to
  review their portfolio, assess risk, optimize allocation, or get rebalancing suggestions.
metadata:
  type: project
  triggers:
    - portfolio
    - 组合
    - 持仓
    - 资产配置
    - rebalance
    - 调仓
    - risk
    - 风险
    - allocation
---

# Portfolio Management Agent Workflow

Analyze portfolio holdings, assess risk, and generate rebalancing recommendations.

## Workflow

### Step 1: Gather Portfolio Data
- Ask user for their current holdings: tickers + allocation percentages or share quantities
- If user provides share quantities, fetch current prices to calculate market values
- Support mixed portfolios: US stocks + A-shares + HK stocks + crypto + cash

### Step 2: Current State Analysis
For each holding and the portfolio overall:
1. **Performance**: recent returns (1W, 1M, 3M, YTD, 1Y)
2. **Allocation**: current % vs target %, drift amount
3. **P&L**: unrealized gain/loss per position
4. **Concentration**: top 3 positions as % of total

### Step 3: Risk Assessment
Calculate and interpret:
- **Portfolio Beta**: weighted average beta vs benchmark
- **Correlation Matrix**: cross-correlations between all holdings
- **Volatility**: portfolio annualized vol, each position's contribution
- **VaR (95%)**: 1-day and 1-month Value at Risk
- **CVaR**: Conditional VaR (expected loss beyond VaR)
- **Max Drawdown**: historical max drawdown of current allocation
- **Stress Tests**: 2008-style crash (-40%), 2020 COVID (-30%), rate shock (+200bps)

### Step 4: Macro Overlay
If FRED MCP is available, check:
- **Yield Curve**: 2Y-10Y spread → recession probability context
- **CPI / PCE**: inflation trend → impact on growth vs value
- **Fed Funds Rate**: rate path → impact on equity multiples and bonds
- **VIX**: current vol regime → position sizing adjustments
- **China Macro** (for A/H portfolios): PMI, M2 supply, social financing

### Step 5: Optimization
Generate rebalancing suggestions using:
- **Mean-Variance Optimization** (Markowitz): max Sharpe portfolio
- **Risk Parity**: equal risk contribution per asset
- **Minimum Variance**: lowest volatility allocation
- **Black-Litterman**: incorporate user views on specific assets

Constraints:
- Max 5% per single stock (10% for ETFs/crypto majors)
- Max 30% sector concentration
- Min 5% cash reserve
- Round lots consideration (A-shares: lots of 100 shares)

### Step 6: Rebalancing Plan
For each suggested change:
- **Action**: BUY / SELL / HOLD
- **Amount**: shares or dollar amount
- **Priority**: HIGH / MEDIUM / LOW (based on risk impact)
- **Tax Consideration**: short-term vs long-term capital gains (for US)
- **Execution**: suggest limit order prices

### Step 7: Output Format

```
# 投资组合分析报告

## 组合概览
- 总市值: $XXX,XXX
- 持仓数量: X
- 现金比例: X%
- 币种敞口: USD X% / CNY X% / HKD X% / Crypto X%

## 收益分析
| 标的 | 权重 | 1M收益 | YTD收益 | 贡献 |
|------|------|--------|---------|------|
| AAPL | 20% | +3.2% | +15.1% | +0.64% |
| ... | ... | ... | ... | ... |

## 风险指标
- 组合波动率: XX% (年化)
- Beta: X.XX
- VaR (95%, 1M): -$X,XXX
- 最大回撤 (历史): -XX%
- 最大相关性: [A] vs [B] = 0.XX

## 压力测试
| 情景 | 组合损失 | 最差持仓 |
|------|----------|----------|
| 2008 金融危机 | -XX% | [TICKER] -XX% |
| 2020 COVID | -XX% | ... |
| 加息 200bps | -XX% | ... |

## 宏观环境评估
- 美债收益率曲线: 倒挂/正常, 经济衰退概率 XX%
- 通胀趋势: 上升/下降/稳定
- 建议防御性配置: XX%

## 调仓建议
| 标的 | 动作 | 数量 | 金额 | 优先级 | 理由 |
|------|------|------|------|--------|------|
| XXX | 减仓 | -50股 | -$X,000 | 高 | 超配+技术面走弱 |
| YYY | 加仓 | +100股 | +$Y,000 | 中 | 低配+基本面改善 |

## 调仓后预期
- 预期收益: XX% (年化)
- 预期波动: XX%
- 预期 Sharpe: X.XX

⚠️ 以上分析基于历史数据和模型估算，不构成投资建议。请根据自身风险承受能力做出决策。
```

## Step 8: Persist Portfolio State
After the review:
1. **Save portfolio snapshot** to `data/portfolios/current.json` with updated holdings, cash, and target allocation
2. **Update portfolio memory** — refresh `.claude/memory/portfolio-state.md` with:
   - Current total value and daily P&L
   - Allocation vs target drift
   - Active risk alerts
3. **Update watchlist state** (`.claude/memory/watchlist-state.md`) if any watchlist tickers were referenced in the portfolio

## Data Source Notes
- Use `stock-scanner` `frankfurter_latest` / `frankfurter_convert` for FX rates on cross-currency holdings
- Use `stock-scanner` `tradingview_technicals` for quick technical checks on existing positions
- If `fred` MCP is available, use it for macro overlay (Step 4); otherwise fall back to `WebSearch`

## Important Rules
- Always fetch live prices — never use stale data.
- Flag any position with >20% unrealized loss for special review.
- Remind users about FX risk for cross-currency holdings.
- Crypto allocations above 10% should trigger a volatility warning.
- Always persist portfolio state after each review.
