# 当前工作状态

> 最后更新: 2026-07-16 00:30。关机同步。

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `ccf7e3d`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ✅
- **东财代理**: 需用户手动启动 `tools\start.vbs`

## ✅ 本次会话交付

### 资金流信号系统 V2.1
- P0 数据口径: 超大单 → 主力(特大单+大单)合计
- P0 推送语义: 买入/卖出 → 重点关注/风险预警
- P0 财报静默: 财报后5日不推送
- 分批采集: 71只/4批/5min冷却/~36min跑完
- 双窗口: 收盘 17:00ET + 盘前 05:00ET
- LLM 分析: Prompt v2 自动生成主要观点
- 评估文档: `docs/资金流信号方案-综合评估-V2.1.md`

### MacroAgent 宏观独立通道
- 去重豁免: 宏观新闻白名单自动跳过去重
- MacroAgent: 15个指标×中英文变体 + LLM Tier×偏离评估
- 管道: Ingest → MacroStage → Screen → Evaluate → Dispatch

### 基础设施
- 代理隧道开机自启 (start.vbs + Startup 快捷方式)
- 关注股 ~71只 自动从 watchlist-state.md 读取

## 📋 下一步
- 🔔 **P1 ATR 波动率阈值** — 替代固定 ±10%（见 [[fund-flow-v2.1-plan]]）
- 🔔 **P1 因子有效性回测** — 东财数据 → 超额收益相关性
- 📊 观察 MacroAgent 生产推送质量
- 🖥️ 用户开机后隧道自动启动，验证首次自动采集

## ⚠️ 本次踩坑
- 东财 IP 封禁（22只连续请求触发），已修：间隔12s + 分批 + 断连不重试
- start.bat 双击找不到 Python（Explorer PATH 不含），已修：绝对路径 + VBS 静默启动
- ECS Docker 容器无法访问宿主 127.0.0.1，需 GatewayPorts + FUND_FLOW_PROXY
