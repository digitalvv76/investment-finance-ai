# 当前工作状态

> 最后更新: 2026-07-06 17:00 CST
> 会话: 下午 — 推送质量验证 + 工作流改进

## 🟢 进行中

- [ ] **推送阈值校准** — bootstrap 网格搜索完成 (F1=0.857, 16 samples)，等更多真实推送数据验证
- [ ] **ECS 瘦身部署** — 2GB 内存，已关 Dashboard/Twitter/Playwright，稳定运行中
- [ ] **Edge Pipeline 集成** — 4 个 skill 已装好，尚未实战使用

## 📋 下一步 (按优先级)

1. **验证推送质量** (等周一股市开盘) — 观察新闻推送是否合理：该推的推了、不该推的没推、中文翻译准确、分析师笔记有用
2. **ECS 升级** (可选，等验证通过后) — 升级到 4GB 以恢复 Twitter 采集 (6 账号，5 分钟频率)
3. **Edge Pipeline 首跑** — 用 `/edge-candidate` 扫一次市场，走通 discovery → design → review → tracking 全流程
4. **设置定时任务** — 工作日早盘简报 cron + 周六策略审查 cron

## ⏸️ 暂缓

- **ECS Docker 部署** — 当前 Python 直跑够用，Docker 等升级 4GB 后再考虑
- **A 股数据源** — cn-finance MCP 包不存在，TradingView SHA/SHE 扫描回退方案可用但未实测
- **Crypto trading** — Binance API key 未配置

## 🔑 部署检查清单 (每次部署必做)

- [ ] `scp .env` 到 ECS（Key 变更时）
- [ ] `scp` 修改的代码文件
- [ ] Docker rebuild (`docker compose up -d --build`)
- [ ] 验证：`docker logs news-monitor | grep 'chat_id\|Monitor running'`
- [ ] 新 Key 同步：`.env` → `.env.example` → `settings.json`

## ⚠️ 上次踩坑 (本次会话已修复)

- HISTORY.md 漏写 7/4-7/5 共 8 个 commits → 已补全
- 伊朗非美政治新闻差点漏过 → geo_market_filter 已加固 (geo_mult > 0.2 检查)
- 黄金新闻正确分类为 NORMAL → 管道验证通过
- `模块注册表漏更新` → SessionStart 会警告未注册模块

## 📊 系统健康

| 组件 | 状态 | 备注 |
|------|------|------|
| ECS (47.76.50.77) | ✅ 运行中 | 2GB, 负载 0.07, 内存 465MB |
| Telegram Bot | ✅ 正常 | chat_id 已绑定 |
| Pushover | ✅ 正常 | 双通道验证通过 |
| DeepSeek API | ✅ 正常 | 主 LLM provider |
| Anthropic API | ❌ 未配置 | 备用 LLM，不影响运行 |
| ChromaDB | ⚠️ Windows 已知问题 | ECS 上不影响 |
| Twitter 采集 | ⚠️ ECS 上已暂停 | 等 4GB 升级后恢复 |
| Web Dashboard | ⚠️ 已关闭 | ECS 端口 8080 仅本地 |

## 🔧 本次会话改动

- 补全 HISTORY.md (7/4 内容过滤 + 7/5 推送格式升级)
- 创建 TROUBLESHOOTING.md (20+ 条踩坑记录)
- 创建 SESSION.md (本文件)
- 增强 SessionStart hook (自动读 SESSION.md + TROUBLESHOOTING.md)
- 验证 Edge Pipeline 4 个 skill 状态 → 全部已安装

## 下次会话计划

- [ ] 检查周一股市开盘后的推送效果
- [ ] 校准阈值是否需要微调
- [ ] 跑一次 Edge Pipeline 完整流程
