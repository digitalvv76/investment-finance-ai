---
name: deployment-checklist
description: |-
  Pre-deployment safety checklist. Use before ANY deploy (Vercel, git push, service restart).
  Chains verify_env → acceptance_test → backup → security → rollback plan into a single pass.
metadata:
  type: project
  triggers:
    - deploy
    - deployment
    - 上线
    - 发布
    - release
    - ship
    - before push
    - 推送前
---

# Deployment Checklist Skill

## Rule

**Never deploy without running this checklist.** All 5 gates must pass.
If any gate fails, fix it before proceeding. No exceptions.

---

## Gate 1: State Integrity

```bash
python news-monitor/scripts/verify_env.py
```

Must show: `RESULT: ALL CHECKS PASSED`

What it checks:
- `.env` exists, all critical credentials set
- `.claude/settings.json` exists, `env` section in sync with `.env`
- Telegram + Pushover API reachable

If failed: missing credentials will cause silent production failures.

---

## Gate 2: Test Suite

```bash
cd news-monitor && python -m pytest tests/ -q --tb=short
```

Must show: **0 failed** (6 ChromaDB errors allowed — known Windows issue)

What to check:
- If any test FAILED that was previously passing → STOP, investigate
- If new code has NO tests → add at least smoke tests
- Coverage for changed modules: run `pytest tests/ -k "<module_name>" -v`

---

## Gate 3: Code Quality

```bash
# Check for obvious issues
grep -r "TODO\|FIXME\|HACK\|XXX" news-monitor/ --include="*.py" | grep -v test | grep -v ".git"

# Check for leftover debug prints
grep -r "print(" news-monitor/ --include="*.py" | grep -v test | grep -v ".git" | grep -v "logger\|logging"
```

Red flags:
- `TODO` / `FIXME` in production code (must document why it's acceptable)
- `print()` statements instead of `logger.info()` (noise in production)
- Commented-out code blocks (remove or explain)
- Hardcoded credentials or IPs (must come from env vars)

---

## Gate 4: Security Scan

```
[ ] .env is in .gitignore?                   → grep "\.env" .gitignore
[ ] .claude/settings.json is in .gitignore?  → grep "settings.json" .gitignore
[ ] No API keys in staged files?             → git diff --cached | grep -i "sk-\|token\|key\|secret"
[ ] No .db files with sensitive data staged? → git diff --cached --name-only | grep "\.db$"
```

Run secret scanning on staged changes:
```bash
git diff --cached | grep -iE "(sk-[a-zA-Z0-9]{20,}|[a-zA-Z0-9]{32,}:=|token.*[a-zA-Z0-9]{20,})"
```

---

## Gate 5: Rollback Plan

Answer these before deploying:

| Question | Answer |
|----------|--------|
| What is the rollback command? | e.g. `git revert <commit>` or `vercel rollback` |
| What data could be lost? | e.g. "no data loss — read-only change" or "news.db schema change — backup exists" |
| How long does rollback take? | e.g. "< 1 minute" or "~5 minutes (DB migration reversal)" |
| Who needs to know? | e.g. "just me" or "Telegram channel subscribers" |

---

## Pre-Deploy Runbook

Execute in order. Stop on first failure.

```bash
# 1. Backup state
python news-monitor/scripts/backup_state.py

# 2. Verify environment
python news-monitor/scripts/verify_env.py
# Must pass before continuing

# 3. Run tests
cd news-monitor && python -m pytest tests/ -q --tb=short
# Must have 0 failures

# 4. Git status check
git status
# Should show only intended changes

# 5. Secret scan
git diff --cached | grep -iE "(sk-[a-zA-Z0-9]{20,}|token.*[a-zA-Z0-9]{20,}|key.*[a-zA-Z0-9]{20,})"
# Should return NOTHING

# 6. Deploy
# Vercel: npx vercel --prod
# Git:    git push origin main
```

---

## Post-Deploy Verification

```bash
# 1. Verify the deployed URL responds
curl -s -o /dev/null -w "%{http_code}" https://class1-cyan.vercel.app
# Should return 200

# 2. Verify Telegram bot responds
# Send /start to @NewsmoniBbot

# 3. Check logs after 5 minutes
# Look for errors in the deployed environment
```

---

## Integration with Other Skills

- **Before deploy**, also check [[db-migration]] if schema changed
- If frontend changed, read `DESIGN.md` to verify visual consistency
- After deploy, update `HISTORY.md` with deploy timestamp and version
