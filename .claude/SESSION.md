# 当前工作状态

> 最后更新: 2026-07-06 21:00 CST

## 🟢 进行中

- [x] **推送规则完善** ✅ 关注名单阈值 0.35 / 非关注不推手机 / StrategicDetector 误报修复
- [x] **Finnhub 新闻源** ✅ 21 个 watchlist 标的每 5 分钟轮询
- [x] **深度分析 v2** ✅ 简洁快报 (400字) + 真实价格 + watchlist 上下文
- [x] **ECS 稳定运行** ✅ 3GB 内存，Twitter 恢复，Docker 代理修复
- [x] **AnySearch MCP** ✅ 已安装，按需深挖用
- [x] **会话管理** ✅ SESSION.md + TROUBLESHOOTING.md + chat_id 自检

## 📋 下一步

1. 观察推送质量，验证新规则生效
2. 跑一次 Edge Pipeline 完整流程
3. 设置周六策略审查 cron

## 🔑 部署检查清单 (每次部署必做)

- [ ] `scp .env` 到 ECS（Key 变更时）
- [ ] `scp` 修改的代码文件
- [ ] Docker rebuild (`docker compose up -d --build`)
- [ ] 验证：`docker logs news-monitor | grep 'chat_id\|Monitor running'`
- [ ] 新 Key 同步：`.env` → `.env.example` → `settings.json`

## 📊 系统健康

| 组件 | 状态 | 备注 |
|------|------|------|
| ECS (47.76.50.77) | ✅ 运行中 | 3.4GB, Docker 39% |
| Telegram Bot | ✅ 正常 | chat_id 自检 + DB 持久化 |
| Pushover | ✅ 正常 | 深度分析链接可用 |
| ZeroHedge | ✅ 1min | heartbeat 采集 |
| Twitter | ✅ 5min | 6 账号正常运行 |
| Finnhub | ✅ 5min | 21 标的个股新闻 |
| RSS + 中文源 | ✅ 15min | CNBC/WSJ/MarketWatch/SA + 华尔街见闻 |
| DeepSeek API | ✅ 正常 | 主 LLM |
| AnySearch | ✅ 已装 | 按需使用，不接自动管道 |
