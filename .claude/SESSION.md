# 当前工作状态

> 最后更新: 2026-07-16 10:50。Futu 标准迁移完成。

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `2e57b57`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ✅
- **Futu OpenD**: ECS systemd 自启，`0.0.0.0:11111` ✅
- **东财代理**: 已废弃 ❌

## ✅ 本次会话交付

### 1. Futu OpenD 完整部署
- ECS `/opt/Futu_OpenD_10.9.6908_Ubuntu18.04/`，systemd 自启 + 会话缓存
- 安全：纯行情权限（未解锁交易），设备锁+富途令牌双重保护
- Docker 容器通过 `172.18.0.1:11111` 连接 OpenD

### 2. 订单分类标准迁移 — 东财→富途
- **futu_fetcher.py**: FundFlowDay 字段注释改为 Futu 标准，明确标注主力 ≠ 特大+大
- **fund_flow_v2.txt**: 全面重写 — 锚点从「特大单」→「主力」，移除固定金额阈值，新增法则 D
- **models.py / fund_flow_collector.py**: 注释 + 推送文案同步更新
- **全链路测试**: AAPL/00700/batch 均通过

### 3. 东财数据通道诊断
- 确认东财 API 全线被封（push2his/push2/ff，直连+Clash 都不通）
- 已修正 `eastmoney_proxy.py` 但最终废弃

## 📋 下一步
- 🔔 **P1 ATR 波动率阈值** — 替代固定 ±10%
- 🔔 **P1 因子有效性回测** — 富途数据 → 超额收益相关性
- 📊 观察富途版资金流信号生产推送质量

## ⚠️ 本次踩坑
- 东财 `push2his` API 路径被 IP 级封杀 → 已切换富途
- Clash `verge-mihomo` 系统代理拦截 → Python socket 需清 env vars
- ECS docker0 是 `172.18.0.1` 非 `172.17.0.1`
- `pkill -f FutuOpenD` 导致 SSH 断开 → 用 `kill $(pgrep FutuOpenD)`
- `git stash pop` 与远端冲突 → `git checkout --theirs` + 手动修复
- Docker 重建后代码才生效（代码在镜像内非 volume）
