---
name: deployment-state
description: Project deployment info — GitHub repo and Vercel production URLs
metadata:
  type: project
---

# Deployment State

## GitHub

- **仓库**: [digitalvv76/investment-finance-ai](https://github.com/digitalvv76/investment-finance-ai)
- **分支**: `main`
- **GitHub 用户**: digitalvv76

## Vercel

- **首页**: https://class1-cyan.vercel.app
- **时钟页面**: https://class1-cyan.vercel.app/datetime
- **Vercel 项目**: cc-1/class1
- **Dashboard**: https://vercel.com/cc-1/class1
- **自动部署**: GitHub push 到 main 分支后自动触发

## 安全

- `.claude/settings.json` 已加入 `.gitignore`（含 API keys，不可公开推送）
- `.env` 已在 `.gitignore`
- 模板文件 `.claude/settings.example.json` 使用占位符代替真实 keys

## 项目主页内容

- `index.html` — 星空主题落地页，展示 4 大核心能力 + 链接到时钟页
- `datetime.html` — 全屏实时时钟（中文界面）
- `vercel.json` — 静态站点配置，clean URLs，`/datetime` 映射到 `/datetime.html`

Last deployed: 2026-06-30
