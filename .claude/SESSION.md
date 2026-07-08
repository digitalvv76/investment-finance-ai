# 当前工作状态

> 最后更新: 2026-07-08 15:05 CST

## ✅ 本次完成 (V1 修改窗口)

### 内容过滤重构
- 中文分层：国际=满分，纯国内=×0.4，CCP宣传=×0.15
- 新增极端事件绕过：熔断/宣战/指数暴跌>4%/油价暴涨
- _has_us_market_signal 扩充至 50+ 关键词

### 采集修复
- MarketWatch web scraper 关闭 (401 anti-bot)
- Sina web scraper 恢复 (URL 域名变更，0→20条)

### LLM urgency 替代公式分类
- prompt 新增 7 个输出字段，4 个 urgency 级别
- classify() 改为 urgency-first 路由，公式降级为 fallback
- e2e 测试 4/4 通过：FLASH(美伊开战)/ALERT(NVDA财报)/INFO(A股)/INFO(研报)

## 📋 下一步

1. 等美股开盘时段观察推送效果
2. 验证 LLM urgency 在实际事件上的表现
3. 积累校准数据 (ImpactOutcome → ImpactLearner)

## 📊 系统健康

| 组件 | 状态 |
|------|------|
| ECS 4C8G | ✅ healthy |
| news-monitor | ✅ healthy |
| Sina scraper | ✅ 20 items |
| MarketWatch RSS | ✅ 10 items |
| LLM urgency | ✅ e2e tested |
