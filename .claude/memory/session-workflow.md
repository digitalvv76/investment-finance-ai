---
name: session-workflow
description: Every dev session MUST end with dev_checklist.py + git push to GitHub
metadata:
  type: feedback
---

Every development session must end with these steps:

1. **Run dev checklist** — `python news-monitor/scripts/dev_checklist.py`
   - Checks: git clean, tests pass, HISTORY.md updated, env valid, remote synced
   - If any check fails, fix it BEFORE ending the session.

2. **Push to GitHub** — `git push origin main`
   - If HTTPS is blocked, use SSH (`git@github.com:digitalvv76/investment-finance-ai.git`)
   - If push fails, inform the user and retry

3. **Verify HISTORY.md** — ensure today's section documents all key commits and decisions

**Why:** The user had sessions where work was done but HISTORY.md was not updated and code was not pushed, and test scripts rotted because module changes weren't tracked. The dev workflow tools (session_startup.py, pre_commit_check.py, dev_checklist.py) prevent recurrence.

**How to apply:**
- Before ending any session, run `python news-monitor/scripts/dev_checklist.py`
- Fix any ❌ or ⚠️ issues reported
- Push to GitHub
- The pre_commit_check.py hook runs automatically on every `git commit` — don't bypass it unless it's an emergency (`[skip-tests]`)
