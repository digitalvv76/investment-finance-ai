# /portfolio-management — 投资组合管理

全面的投资组合分析、风险评估和调仓建议。

## 触发词
- `/portfolio-management`
- "组合"
- "portfolio"
- "调仓"
- "rebalance"
- "risk"
- "风险"

## 功能

### 1. 组合快照
- 当前持仓列表及市值
- 各资产类别占比
- 与目标配置偏差

### 2. 风险评估
- 组合 Beta/波动率
- VaR (Value at Risk)
- 最大回撤分析
- 行业集中度风险
- 汇率风险敞口

### 3. 绩效分析
- 时间加权收益 (TWR)
- 货币加权收益 (MWR)
- 夏普比率
- 信息比率
- 与基准对比 (S&P 500/沪深300)

### 4. 调仓建议
- 基于目标权重的再平衡
- 税收优化考虑
- 分批调仓计划

## 数据回退
| 不可用 | 回退 |
|--------|------|
| fred | stock-scanner sentiment_fear_greed + WebSearch |
| coingecko | stock-scanner 内置 crypto_quote |

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
