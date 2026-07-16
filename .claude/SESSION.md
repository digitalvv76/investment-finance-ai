# 当前工作状态

# 当前工作状态

> 最后更新: 2026-07-16 续。MacroAgent 推送空洞已诊断，V2 已修 (`adc5429`)。main 已合并同步。

## ⚠️ V1/V2 分工（用户 2026-07-14 定）
- **V1**：投资决策 + 业务方向 + 需求优先级 + 推送验收
- **V2**：架构 + 代码 + 测试 + 部署（全权）
- **V1 不能改代码和部署**，发现问题 → 告诉 V2 → V2 动手
- CLAUDE.md 角色分工表是唯一权威

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ✅
- **Futu OpenD**: systemd 自启，行情+资金流+新闻+快照+板块五合一 ✅
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动，四通道正常 ✅
- **TG 重复推送**: 已修复 ✅ — IngestStage 跳过 INSERT OR IGNORE 条目 + 启动 URL 缓存

## 📋 下一步

| # | 事项 | 状态 |
|---|------|:---:|
| ✅ | **MacroAgent 推送空洞** — V2 已修 (`adc5429`), V1 已合并同步 | ✅ |
| 🔴 | **富途 P0 防封禁** — 已执行 (semaphore 5→1, sleep 0.3s→1.0s) | ✅ |
| 🟡 | **富途 P1-P3** — 实时快照 + 板块轮动 + 经纪商队列 | 进行中 |
| 🟡 | **训练体系 L1-L4** — 反馈+对抗+Wiki驱动+Prompt校准 | V2 |
| 🔔 | **P1 ATR 波动率阈值 / 因子有效性回测** | V2 |
| 👀 | **观察推送质量** — 中文管道 + MacroAgent 生效后的推送变化 | 持续 |

## ⚠️ 踩坑

- **同模型 agent 共享盲点**: 对着代码/测试证伪，别信单轮共识
- **去重误杀宏观新闻**: PPI 被 dedup 吃掉 → MacroAgent 已部署修复
- **中文管道全链路英文盲**: 华尔街见闻零推送 → 已部署修复
- **东财 API 全线被封**: → 切换富途 OpenD ✅
- **ECS .env 残留 Clash 代理**: DeepSeek/HTTPS 全断 → 已修复
- **Telegram Conflict**: 不能同时两个 bot 实例 polling
- **线程耗尽**: 重复 ApplicationBuilder 初始化 → 已修复
- **确认偏误**: V1 读旧代码诊断 MacroAgent 空洞，V2 实际已修 → memory [[verify-before-escalating]]
