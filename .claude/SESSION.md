# 当前工作状态

> 最后更新: 2026-07-15 19:50。Collector 集成完成，待部署。

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `4a4765e`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ✅
- **东财代理**: 需用户手动启动 `tools\start.bat`（代理 + SSH 隧道）

## ✅ 本会话交付

### 📊 资金流分析 Prompt v2 (下午)
- 核心重构为"背离信号"锚点架构
- 保存位置: `E:\分析报告\美股港股资金流分析专家 Prompt.md`

### 🔧 东财 Collector 管线集成 (晚上)
- **新建** `fund_flow_collector.py` — 每日美东17:00自动采集资金流数据
- **新建** `fund_flow` 数据库表 — ticker+date 唯一索引，upsert 幂等
- **接入 main.py** — 独立后台循环（对标 ImpactCollector 模式）
- **信号推送** — extreme → Pushover 铃声 + TG；strong → TG 静默
- **配置** — settings.yaml 含 22 只关注股，每 30 分钟检查是否该跑
- **注册** — manifest.json 已注册 eastmoney_fetcher + fund_flow_collector
- **docker** — 移除 compose 中 HTTP_PROXY 硬覆盖，改由 .env 控制
- **测试** — +33 tests (18 collector + 7 database + 已有回归 576 pass)

### 📈 NBIS 资金流分析
- 两份数据源（东财 + 富途）结论一致：底背离信号确认

## 📋 下一步
- 📦 **部署到 ECS**：commit + push → deploy-main.sh → ECS 手动更新 settings.yaml + .env
- 🖥️ **启动代理隧道**：用户运行 `tools\start.bat`
- 📊 **回归验证**：观察手机推送双规则 + 资金流首次自动采集

## ⚠️ 本次踩坑
- 东财 `push2his` API IP 封禁 → 本地 HTTP 代理 + SSH 反向隧道
- 东财数据金额比富途大 2-5x → 阈值已上调校准
- 富途 OpenD 已取消，东财从临时→永久方案
