---
name: credential-architecture
description: Complete credential architecture — single source of truth, loading flow, recovery procedures
metadata:
  type: reference
  updated: 2026-07-03
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

| Variable | Required | Purpose | Module |
|----------|----------|---------|--------|
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot | `bot/telegram_bot.py`, `main.py` |
| `DEEPSEEK_API_KEY` | Yes* | LLM deep analysis (primary) | `engine/deep_lane.py`, `engine/curator.py`, `engine/trainer.py` |
| `ANTHROPIC_API_KEY` | Yes* | LLM deep analysis (fallback) | `engine/deep_lane.py` |
| `PUSHOVER_APP_TOKEN` | Recommended | Pushover emergency push | `engine/alert_dispatcher.py` |
| `PUSHOVER_USER_KEY` | Recommended | Pushover user identifier | `engine/alert_dispatcher.py` |
| `FRED_API_KEY` | Optional | FRED macro data | `collector/api_fetcher.py` |
| `ALPHA_VANTAGE_API_KEY` | Optional | Stock fundamentals | `collector/api_fetcher.py` |

*At least one LLM key required. DeepSeek preferred.

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
