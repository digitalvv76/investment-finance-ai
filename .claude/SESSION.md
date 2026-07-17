# 当前工作状态

> 最后更新: 2026-07-17。推送门槛全面提高已部署。

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `d6a3da7`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ✅
- **Futu OpenD**: systemd 自启，行情+资金流+新闻+快照+板块五合一 ✅
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动，四通道正常 ✅
- **资金流 DB**: 72 标的，1451 行（最新 07-16）

## 📱 推送门槛调整 (2026-07-17 已部署)

### 手机 Pushover
- 仅 3 种情况震手机：战略规则(STRATEGIC_*) > 宏观≥92 > CRITICAL
- 关注股 IMPORTANT 新闻 → TG only（不再震手机）
- 去重 6h→24h，快照 extreme ±5%→±7%

### TG
- IMPORTANT 阈值 0.45→0.50，每周期封顶 5→4 条

### 资金流
- 背离+STANDARD→skip，仅 STRONG 推送

### 对抗核实
- 发现 classify() auto-CRITICAL 死代码，改为 _phone_threshold_ok 显式战略绕过
- `fast_lane.py` 打的 STRATEGIC_* 标签第一优先级检查

## 📋 下一步
- OpenD systemd 重启循环修复（cron 已排期 06:00 CST）
- P1 ATR 波动率阈值 + 因子有效性回测
- 观察推送频率变化

## ✅ 本次会话交付 (~18 个提交)

### 1. 资金流推送重构
- 移除手机 Pushover 推送，走 TG only
- `_push_strong` guard 补全 `._app` 检查

### 2. v2 推送标准
- 信号类型 × 强度 × 主力占比 × 特殊模式 四维决策矩阵
- 背离+STRONG+extreme → 有声TG / 背离+STANDARD → 静默 / 其余 → skip
- 黄金坑/散户陷阱 升一档

### 3. Futu main_in_flow 集成
- 纳入 Futu 官方"主力大单净流入"替代自行计算的 super+big
- 回退兼容：旧数据 main_in_flow=0 时使用 super+big

### 4. DB close_price + change_pct 修复
- fund_flow 表加 close_price 列，采集时写入
- K-line max_count 不足导致最新日期被截断 → 改为 days*2+10
- K-line 异常不再静默吞掉
- LLM 分析提示中 change_pct 补全所有日期（之前仅补最后3日）

### 5. /ff 命令
- TG 内 `/ff TICKER` 查看资金流完整深度分析，实时调用 LLM

### 6. 配置
- settings.yaml 写入 71 只关注标的（容器内无需读 watchlist-state.md）
- 4 个 Futu 模块注册到 collector/__manifest__.json

### 7. 全量数据采集
- 72 标的资金流数据全量入库（MRAAY/SATS/PXD 不支持）
- ASTS 黄金坑 + ACHR 底背离 已推送 TG

## 📋 下一步
- 今晚 17:00 ET 盘后采集按 71 标的自动运行
- 明早 ~05:00 ET 盘前分析 v2 标准生效
- OpenD systemd 重启循环修复（cron 已排期 06:00 CST）
- Playwright/Twitter/WebScraper 浏览器 OOM（P3，暂不修）
- P1 ATR 波动率阈值 + 因子有效性回测

## ⚠️ 踩坑记录
- K-line max_count=25 不足，Futu 截断最新日期而非最旧
- 东财 eastmoney_fetcher 是死代码但测试仍在引用
- Docker 容器内读不到 .claude/memory/watchlist-state.md → settings.yaml 直配
- price_change_3d 已废弃但 _format_tg_message 仍在用 → 改为 cum_price_3d
- MRAAY (OTC)/SATS (未知)/PXD (已退市) Futu 不支持
