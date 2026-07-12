---
name: credential-architecture
description: Complete credential architecture — single source of truth, loading flow, recovery procedures
metadata:
  type: reference
  updated: 2026-07-13
---

# Credential Architecture

## Single Source of Truth

`.env` at repo root (`D:/class1/.env`) is the **single source of truth** for ALL credentials.
All other credential stores derive from it.

## Credential Flow

```
.env (source of truth)
  │
  ├─→ python-dotenv (load_dotenv in main.py / all entry points)
  │     └─→ os.environ → all modules read os.environ.get()
  │
  ├─→ sync_env_to_settings.py (manual, run after editing .env)
  │     └─→ .claude/settings.json env section
  │           └─→ Claude Code harness injects at session start
  │
  └─→ Docker compose (reads from host env or .env file)
```

## Credential Inventory

### LLM / AI

| Variable | Required | Purpose | Module |
|----------|----------|---------|--------|
| `DEEPSEEK_API_KEY` | ✅ 必须 | 主力 LLM (评估+分析+训练+对抗核实) | `news-monitor/engine/`, `news-monitor/pipeline/` |

### 推送通道

| Variable | Required | Purpose | Module |
|----------|----------|---------|--------|
| `TELEGRAM_BOT_TOKEN` | ✅ 必须 | Telegram Bot | `news-monitor/bot/telegram_bot.py` |
| `TELEGRAM_CHAT_ID` | ✅ 必须 | TG 频道 1 |同上|
| `TELEGRAM_CHAT_ID_2` | 可选 | TG 频道 2 (双手机) |同上|
| `TELEGRAM_CHAT_ID_3` | 可选 | TG 频道 3 |同上|
| `PUSHOVER_APP_TOKEN` | ✅ 必须 | Pushover 推送 | `news-monitor/engine/alert_dispatcher.py` |
| `PUSHOVER_USER_KEY` | ✅ 必须 | Pushover 用户 1 |同上|
| `PUSHOVER_USER_KEY_2` | 可选 | Pushover 用户 2 |同上|

### 行情数据

| Variable | Required | Purpose | Module |
|----------|----------|---------|--------|
| `ALPHA_VANTAGE_API_KEY` | 推荐 | 美股基本面 | `news-monitor/collector/api_fetcher.py` |
| `FINNHUB_API_KEY` | 推荐 | 美股实时/基本面 |同上|
| `FRED_API_KEY` | 可选 | 宏观经济数据 |同上|
| `BINANCE_API_KEY` | 可选 | 币安行情 | `news-monitor/collector/` |
| `BINANCE_SECRET_KEY` | 可选 | 币安签名 |同上|

### 数据源

| Variable | Required | Purpose | Module |
|----------|----------|---------|--------|
| `TWITTER_AUTH_TOKEN` | 可选 | Twitter/X 采集 | `news-monitor/collector/` |

### 基础设施

| Variable | Required | Purpose | Module |
|----------|----------|---------|--------|
| `WEB_USERNAME` / `WEB_PASSWORD` | ✅ 必须 | Web 面板认证 | `news-monitor/web/` |
| `WEB_PORT` | 可选 | Web 端口 (默认 8080) | `news-monitor/main.py` |
| `WEB_DASHBOARD_URL` | 推荐 | 面板外网地址 | `news-monitor/web/` |
| `UPTIMEROBOT_API_KEY` | 推荐 | 部署时暂停/恢复监控 | `deploy-main.sh` |
| `HTTPS_PROXY` / `HTTP_PROXY` | 按需 | 国内访问外网代理 | 全模块 |
| `PYTHONIOENCODING` | 必须 | UTF-8 编码 |启动时|

## Verification

```bash
# Runs automatically at every session start (SessionStart hook)
python news-monitor/scripts/verify_env.py

# Manual run
cd D:/class1 && python news-monitor/scripts/verify_env.py
```

Checks: file existence, credential presence, .env ↔ settings.json sync, API connectivity.

## Backup & Recovery

**Automatic backup**: Every session start backs up to `.claude/backups/state/YYYY-MM-DD_HHMMSS/`
- `.env`, `settings.json`, `HISTORY.md`, `.claude/memory/*.md`
- Rolling 10 copies, oldest auto-deleted
- Directory is gitignored (contains secrets)

**Manual backup**:
```bash
python news-monitor/scripts/backup_state.py
```

**Recovery**: Copy the needed file from the latest backup directory:
```bash
cp .claude/backups/state/2026-07-03_081507/.env .env
```

## Adding a New Credential

1. Add `KEY=value` to `.env`
2. Run `python news-monitor/scripts/sync_env_to_settings.py`
3. Add to `CRITICAL_VARS` / `RECOMMENDED_VARS` / `OPTIONAL_VARS` in `verify_env.py`
4. Update the table above

## Why .env is the Source of Truth

- `.env` is the universal standard for environment configuration
- `python-dotenv` loads it automatically, works from any CWD
- Works with Docker, systemd, NSSM, and direct terminal execution
- `.claude/settings.json` is Claude Code-specific; .env is universal

## Why settings.json is Still Needed

Claude Code harness reads `settings.json["env"]` and injects vars into the session
BEFORE any Python code runs. This is essential for MCP servers and hooks to have
access to API keys. `sync_env_to_settings.py` keeps it in sync with .env.

## Session Integrity Checklist

At session start (automatic):
1. `backup_state.py` — snapshot all state files
2. `verify_env.py` — check all credentials present and synced
3. Session log + HISTORY.md header

At session end (agent responsibility, per [[session-workflow]]):
1. Append all operations to HISTORY.md
2. Run `verify_env.py` to confirm nothing broke
3. `git push` if changes were committed
