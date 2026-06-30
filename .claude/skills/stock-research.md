# /stock-research — 个股深度研究

对任意股票进行全面多维度分析，生成投资研究报告和评级。

## 触发词
- `/stock-research`
- "分析 [ticker]"
- "research [ticker]"
- "看看 [股票名]"

## 分析流程

### 1. 基本面分析
- 使用 `yfinance.get_stock_info` 获取公司概况
- 使用 `yfinance.get_financial_statement` 获取三大报表
- 使用 `stock-scanner.edgar_company_facts` 获取 SEC XBRL 数据
- 评估: PE/PB/PS 估值、ROE/ROA 盈利能力、负债率、自由现金流

### 2. 技术面分析
- 使用 `stock-scanner.tradingview_technicals` 获取 RSI/MACD/均线
- 使用 `yfinance.get_historical_stock_prices` 获取历史价格
- 关键位识别: 支撑/阻力/趋势线

### 3. 市场情绪
- 使用 `stock-scanner.reddit_sentiment` 获取 Reddit 情绪
- 使用 `stock-scanner.options_unusual_activity` 检测期权异动
- 使用 `yfinance.get_recommendations` 查看分析师评级

### 4. 机构动向
- 使用 `stock-scanner.edgar_insider_trades` 查看内部人交易
- 使用 `stock-scanner.edgar_institutional_holdings` 查看机构持仓
- 使用 `yfinance.get_holder_info` 获取持股分布

### 5. 综合评级
生成 1-5 星评级，含:
- 投资论点 (bull case + bear case)
- 目标价区间
- 风险因素
- 建议仓位比例

## 报告输出
报告保存到 `data/reports/[ticker]_[date].md`

## 数据回退
| 不可用 | 回退 |
|--------|------|
| yfinance | stock-scanner tradingview_quote + alphavantage_overview |
| sec-edgar | stock-scanner 内置 edgar_* 工具 |

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
