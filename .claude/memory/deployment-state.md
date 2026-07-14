---
name: deployment-state
description: Project deployment info — GitHub repo and Vercel production URLs
metadata:
  type: project
---

# Deployment State

> 最后更新: 2026-07-13 早

## ECS 生产 (47.76.50.77)

- **运行版本**: V2 (origin/main)
- **最后部署**: 2026-07-12 晚 (event_driven 时效性修复 + R0 event_decisions 落库表)
- **看门狗**: healthy, 8条/时采集, Pushover 心跳正常
- **监控**: UptimeRobot (id=803451600)
- **部署脚本**: `deploy-main.sh` — git checkout origin/main → 重建容器, 内置回滚 tag + UptimeRobot 暂停

## GitHub

- **仓库**: [digitalvv76/investment-finance-ai](https://github.com/digitalvv76/investment-finance-ai)
- **主分支**: `main` (V2, 开发主线)
- **历史分支**: `v1-stable` (已重置为干净 main + 军事冲突关键词原型, 已偏离 main)
- **GitHub 用户**: digitalvv76

## Vercel

- **首页**: https://class1-cyan.vercel.app
- **时钟页面**: https://class1-cyan.vercel.app/datetime
- **健康检查**: https://class1-cyan.vercel.app/health
- **Vercel 项目**: cc-1/class1
- **Dashboard**: https://vercel.com/cc-1/class1
- **代理链**: Vercel → ECS:8080 (手机 API 必须走 Vercel HTTPS)

## 安全

- `.claude/settings.json` 已加入 `.gitignore`（含 API keys，不可公开推送）
- `.env` 已在 `.gitignore`
- 模板文件 `.claude/settings.example.json` 使用占位符代替真实 keys

## 项目主页内容

- `index.html` — 星空主题落地页，展示 4 大核心能力 + 链接到时钟页
- `datetime.html` — 全屏实时时钟（中文界面）
- `vercel.json` — 静态站点配置，clean URLs，`/datetime` 映射到 `/datetime.html`

Last deployed: 2026-07-12
