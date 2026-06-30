# /quant-strategy — 量化策略开发与回测

开发、回测和优化量化交易策略，生成可执行的交易信号。

## 触发词
- `/quant-strategy`
- "策略"
- "backtest"
- "回测"
- "signal"
- "信号"

## 支持策略类型

### 趋势跟踪
- 双均线交叉 (Golden/Death Cross)
- 动量突破 (N日新高)
- 唐奇安通道突破

### 均值回归
- 布林带回归
- RSI 超买超卖
- 统计套利 (配对交易)

### 多因子
- 价值因子 (PE/PB/PS)
- 质量因子 (ROE/毛利率)
- 动量因子
- 低波动因子

### 风险管理
- 仓位大小 (Kelly/固定比例/ATR-based)
- 止损止盈
- 最大回撤控制

## 回测流程

1. **数据获取**: `yfinance.get_historical_stock_prices` 获取历史数据
2. **信号生成**: 根据策略规则生成买卖信号
3. **绩效计算**: 累计收益、年化收益、夏普比率、最大回撤、胜率
4. **可视化**: 收益曲线、回撤曲线、信号标注

## 信号输出
- 活跃信号保存到 `data/signals/active.json`
- 历史信号追加到 `data/signals/history.jsonl`
- 回测报告保存到 `data/reports/backtest_[strategy]_[date].md`

## 数据回退
| 不可用 | 回退 |
|--------|------|
| yfinance | stock-scanner alphavantage_daily + tradingview_quote |
| cn-finance | stock-scanner tradingview_scan + SHA/SHE 交易所过滤 |

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
