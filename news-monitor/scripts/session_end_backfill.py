#!/usr/bin/env python3
"""SessionEnd backfill — append git commits missing from HISTORY.md.

Layer 1 of the memory-durability design: at session end, any *recent* commit
whose short hash is not yet cited in HISTORY.md is appended *with its full
body*.  Because well-written commit messages carry the WHY (root cause,
tradeoffs, verification), this mechanically preserves both WHAT and WHY for
code-change decisions — even when a session ends abruptly (restart, kill).

Matching key is the commit SHORT HASH, not the subject: HISTORY.md is written
as human narrative (e.g. "根因修复") and rarely repeats commit subjects
verbatim, but entries do cite the hash like ``(87fbf35)``.  Convention: every
HISTORY entry cites its commit hash.

Bounded backfill: walk commits newest→oldest and stop at the first one whose
hash is already cited (the high-water mark).  Only commits newer than that —
this session's un-recorded tail — are appended.  This keeps the tool from
re-narrating old, already-logged history.

Properties:
  - Idempotent: once appended, the hash is cited, so re-runs stop immediately.
  - Append-only: never rewrites existing HISTORY.md content.
  - Never blocks: always exits 0.
  - Quiet: writes/prints nothing when there is no gap.

Not covered (Layer 2): decisions that produced no commit (skips,
confirmations, direction changes) still need in-session recording.
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HISTORY_PATH = PROJECT_ROOT / "HISTORY.md"

# How many recent commits to scan back for the high-water mark.
SCAN_N = 40

# Sync commits are the HISTORY bookkeeping themselves — never backfill them.
SKIP_PREFIXES = ("docs: sync", "docs: session sync")


def run_git(*args: str) -> str:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def recent_commits(n: int) -> list[tuple[str, str, str]]:
    """[(short_hash, subject, iso_date), ...] newest first."""
    out = run_git("log", f"-{n}", "--format=%h%x1f%s%x1f%ad",
                  "--date=format:%Y-%m-%dT%H:%M")
    commits = []
    for line in out.split("\n"):
        parts = line.split("\x1f")
        if len(parts) == 3:
            commits.append((parts[0], parts[1], parts[2]))
    return commits


def commit_body(h: str) -> str:
    return run_git("show", "-s", "--format=%b", h).strip()


def main() -> int:
    if not HISTORY_PATH.exists():
        return 0

    content = HISTORY_PATH.read_text(encoding="utf-8")
    commits = recent_commits(SCAN_N)

    # Walk newest→oldest, collecting un-cited commits until we hit the first
    # commit whose hash is already recorded (the high-water mark).
    to_backfill: list[tuple[str, str, str]] = []
    for h, subj, date in commits:
        if h in content:
            break  # high-water mark reached — everything older is recorded
        if subj.startswith(SKIP_PREFIXES):
            continue  # sync commit — skip but keep walking
        to_backfill.append((h, subj, date))

    if not to_backfill:
        return 0

    # Oldest-first so the appended block reads chronologically.
    to_backfill.reverse()

    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    blocks = [
        f"\n## {stamp} · 🤖 会话结束自动补账\n",
        "> SessionEnd hook 自动补录 git log 中未记入 HISTORY 的提交"
        "（按 commit hash 去重，含 body 作为 WHY）。\n",
    ]
    for h, subj, date in to_backfill:
        blocks.append(f"### {h} · {date} · {subj}\n")
        body = commit_body(h)
        if body:
            lines = [ln for ln in body.splitlines()
                     if not ln.startswith("Co-Authored-By:")]
            trimmed = "\n".join(lines).strip()
            if trimmed:
                blocks.append(trimmed + "\n")
        blocks.append("---\n")

    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write("\n".join(blocks))

    print(f"[session-end] backfilled {len(to_backfill)} commit(s) into HISTORY.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
