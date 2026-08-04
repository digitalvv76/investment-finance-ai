# 当前工作状态

> 最后更新: 2026-08-04T23:10。管线健康，Watchdog 分源健康检查已上线。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | —

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `e884cdf`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一，v4-pro (核心评估) + v4-flash (噪音过滤)
- **Futu OpenD**: ✅ 已复活 — 第 3 次僵死，kill -9 重启
- **管线**: 全链路健康，采集量 228-435 条/周期
- **Watchdog**: 已加入分源健康检查 — 核心源(Futu/Finnhub/Twitter/RSS)连续 3 周期连接错误 → 告警

## 📱 推送门槛
- **Geo-tier**: 非美宏观 ×0.25 基本不推
- **Graham 审查**: 5 问题清单降级/拦截噪音
- **手机**: 战略规则 > 宏观≥92 > CRITICAL
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条

## 🔧 最近完成
- 管线瘫痪诊断 + 修复（Futu OpenD 僵死 + 容器长运行退化）
- Watchdog 分源健康检查（scheduler 分源计数 + watchdog source_stall 检测）
- 区分连接错误 vs 健康空返回（避免假阳性）

## ⚠️ 踩坑记录
- Futu OpenD 僵死：每 1-2 天发作一次，进程存活+LISTEN 但 SYN 无响应
- Watchdog 盲区：只看总量→4 个 scraper 活着就 HEALTHY，其他源全死不告警
- 容器长运行（25h+）→ Playwright Chromium 上下文损坏 + HTTP 连接池耗尽
