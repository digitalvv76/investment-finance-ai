# /daily-briefing — 每日市场简报

生成每日盘前/盘后市场概览，含宏观环境、持仓更新和风险预警。

## 触发词
- `/daily-briefing`
- "早报"
- "日报"
- "briefing"
- "market update"

## 简报内容

### 1. 宏观概览
- 主要指数表现 (S&P 500/NASDAQ/DJI/CSI 300/HSI)
- VIX 恐慌指数
- Fear & Greed 指数
- 美债收益率 (2Y/10Y)
- 汇率 (USD/CNY, USD/HKD)

### 2. 经济日历
- 今日/本周即将发布的重要数据
- 美联储日程
- 财报日历

### 3. 关注列表更新
- 自选股涨跌幅
- 关键位触及提醒
- 异常波动检测

### 4. 持仓检查
- 组合整体表现
- 个股盈亏
- 止损/止盈预警

### 5. 情绪与资金
- Reddit 热门讨论
- 期权市场异动
- 板块轮动

## 输出格式
- Markdown 格式报告
- 保存到 `data/briefings/briefing_[date].md`
- 支持 `--quick` 快速模式（精简版）

## 定时触发
```
# 工作日盘前 (美东 8:57 AM = 北京 20:57)
/cron 57 8 * * 1-5 /daily-briefing
```

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
