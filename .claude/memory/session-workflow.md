---
name: session-workflow
description: Every dev session MUST end with HISTORY.md update + git push to GitHub
metadata:
  type: feedback
---

Every development session must end with three mandatory steps:

1. **Update HISTORY.md** — document all key operations, commits, outputs, and discoveries from this session. Append only, never overwrite previous history.

2. **Verify credentials** — run `python news-monitor/scripts/verify_env.py`. If any check fails, fix BEFORE closing the session. Credentials lost in one session cannot be recovered in the next.

3. **Push to GitHub** — `git push origin main` to ensure work continuity. If HTTPS is blocked, use SSH (`git@github.com:digitalvv76/investment-finance-ai.git`).

**Why:** The user had sessions where work was done but HISTORY.md was not updated and code was not pushed, causing discontinuity. The user explicitly requested: "以后要记得更新HISTORY和推送github，要保证开发工作的连续性和可靠性"

**How to apply:**
- Before ending any session, verify `git status` is clean
- Read HISTORY.md to verify session is documented
- Push to GitHub (try HTTPS first, fallback to MCP API)
- If push fails, inform the user and keep retrying
- Network issues are common — GitHub MCP `push_files` bypasses git protocol
