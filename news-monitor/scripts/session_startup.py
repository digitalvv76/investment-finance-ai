#!/usr/bin/env python3
"""Session startup summary — git-driven, replacing the old awk HISTORY.md banner.

Shows:
  1. Today's commits (from git log)
  2. HISTORY.md sync status (missing entries warning)
  3. Dirty git state from previous session
  4. Stale related scripts for recently changed modules

Always exits 0 — informational only, never blocks session start.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# UTF-8 setup
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NEWS_MONITOR = PROJECT_ROOT / "news-monitor"
REGISTRY_PATH = NEWS_MONITOR / "config" / "module_registry.json"


def run_git(*args: str) -> str:
    """Run a git command and return its stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_today_commits() -> list[tuple[str, str, str]]:
    """Return [(hash, subject, relative_time), ...] for today's commits."""
    today = datetime.now().strftime("%Y-%m-%d")
    out = run_git("log", f"--since={today} 00:00", "--format=%h|%s|%ar")
    if not out:
        return []
    commits = []
    for line in out.split("\n"):
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append((parts[0], parts[1], parts[2]))
    return commits


def get_recent_commits(n: int = 10) -> list[tuple[str, str, str]]:
    """Return last N commits if no today commits exist."""
    out = run_git("log", f"-{n}", "--format=%h|%s|%ar")
    if not out:
        return []
    commits = []
    for line in out.split("\n"):
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append((parts[0], parts[1], parts[2]))
    return commits


def check_history_md(commits: list[tuple[str, str, str]]) -> list[str]:
    """Check if today's commits appear in today's HISTORY.md section.
    Returns list of commit subjects missing from HISTORY.md.
    """
    history_path = PROJECT_ROOT / "HISTORY.md"
    if not history_path.exists():
        return [c[1] for c in commits]

    try:
        content = history_path.read_text(encoding="utf-8")
    except Exception:
        return [c[1] for c in commits]

    today = datetime.now().strftime("%Y-%m-%d")
    # Find today's section in HISTORY.md
    today_header = f"## {today}"
    idx = content.find(today_header)
    if idx == -1:
        return [c[1] for c in commits]

    # Extract today's section content
    section = content[idx:]
    next_section = section.find("\n## ", len(today_header))
    if next_section != -1:
        section = section[:next_section]

    missing = []
    for _, subject, _ in commits:
        # Check if the commit subject or its key words appear in the section
        # Use the first 30 chars of the subject as a search key
        key = subject[:30]
        if key not in section:
            # Also check commit hash
            if subject not in section:
                missing.append(subject)
    return missing


def check_dirty_state() -> list[str]:
    """Check for uncommitted changes from previous session."""
    out = run_git("status", "--short")
    if not out:
        return []
    lines = [l.strip() for l in out.split("\n") if l.strip()]
    # Filter to only show modified/deleted files, not untracked
    changed = [l for l in lines if not l.startswith("??")]
    return changed


def get_recently_changed_modules(n: int = 5) -> list[str]:
    """Get modules changed in last N commits, relative to news-monitor/."""
    out = run_git("diff", "--stat", f"HEAD~{n}..HEAD", "--", "news-monitor/")
    if not out:
        return []
    modules = []
    for line in out.split("\n"):
        if "|" in line:
            file_path = line.split("|")[0].strip()
            if file_path.endswith(".py") and "test" not in file_path.lower():
                # Convert full path to relative path from news-monitor/
                rel = file_path.replace("news-monitor/", "")
                modules.append(rel)
    return modules


def load_registry() -> dict:
    """Load module_registry.json."""
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def scan_manifests() -> list[str]:
    """Scan for manifest inconsistencies. Returns warning messages.

    Checks:
      - .py files on disk that are missing from __manifest__.json
      - manifest entries that reference files that don't exist
    """
    warnings: list[str] = []
    news_root = NEWS_MONITOR

    for manifest_path in sorted(news_root.glob("*/__manifest__.json")):
        dir_name = manifest_path.parent.name
        if dir_name in ("tests", "__pycache__"):
            continue
        try:
            with open(manifest_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            warnings.append(f"{manifest_path.relative_to(news_root)}: 无法解析 — {e}")
            continue

        registered = set(data.get("modules", {}).keys())

        # Find actual .py files in this directory (excluding __init__.py)
        actual: set[str] = set()
        for py_file in manifest_path.parent.glob("*.py"):
            if py_file.name.startswith("__"):
                continue
            rel = f"{dir_name}/{py_file.name}"
            actual.add(rel)

        # Also check subdirectories
        for subdir in manifest_path.parent.iterdir():
            if subdir.is_dir() and not subdir.name.startswith("__"):
                for py_file in subdir.glob("*.py"):
                    if py_file.name.startswith("__"):
                        continue
                    rel = f"{dir_name}/{subdir.name}/{py_file.name}"
                    actual.add(rel)

        # Files on disk but not in manifest
        missing = actual - registered
        for m in sorted(missing):
            warnings.append(f"{m}: 文件存在但未在 __manifest__.json 注册")

        # Files in manifest but not on disk
        stale = registered - actual
        for s in sorted(stale):
            warnings.append(f"{s}: 已在 manifest 注册但文件不存在")

    return warnings


def check_registry_deprecation() -> list[str]:
    """Check if legacy registry is still being updated independently of manifests."""
    warnings: list[str] = []
    reg_path = NEWS_MONITOR / "config" / "module_registry.json"
    if not reg_path.exists():
        return warnings

    reg_mtime = os.path.getmtime(str(reg_path))
    manifest_times = []
    for mf in NEWS_MONITOR.glob("*/__manifest__.json"):
        try:
            manifest_times.append(os.path.getmtime(str(mf)))
        except Exception:
            pass

    newest_manifest = max(manifest_times) if manifest_times else 0
    if reg_mtime > newest_manifest:
        warnings.append(
            "module_registry.json 有更新但 __manifest__.json 未同步 — "
            "迁移完成后 registry 应废弃"
        )

    return warnings


def check_stale_scripts(registry: dict, recent_modules: list[str]) -> list[str]:
    """For recently changed modules, check if related_scripts are older."""
    import os as _os
    warnings = []
    modules = registry.get("modules", {})
    for mod in recent_modules:
        if mod not in modules:
            continue
        entry = modules[mod]
        related = entry.get("related_scripts", [])
        if not related:
            continue

        mod_path = NEWS_MONITOR / mod
        if not mod_path.exists():
            continue
        mod_mtime = _os.path.getmtime(str(mod_path))

        for script_rel in related:
            script_path = NEWS_MONITOR / script_rel
            if not script_path.exists():
                continue
            script_mtime = _os.path.getmtime(str(script_path))
            if mod_mtime > script_mtime:
                delta_hours = (mod_mtime - script_mtime) / 3600
                warnings.append(
                    f"{script_rel} (依赖 {mod}, 落后 {delta_hours:.0f}h)"
                )
    return warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    today_str = datetime.now().strftime("%Y-%m-%d")
    print()
    print("=" * 55)
    print(f"  📋 会话启动摘要 — {today_str}")
    print("=" * 55)

    # --- 1. Git commits ---
    commits = get_today_commits()
    if not commits:
        commits = get_recent_commits(10)
        print(f"\n  今日无新提交，最近 {len(commits)} 次:")
    else:
        print(f"\n  今日提交 ({len(commits)}):")

    for h, s, t in commits[:15]:
        # Truncate long subjects
        display = s[:72] + "…" if len(s) > 72 else s
        print(f"    {h}  {display}")
        print(f"         {t}")

    # --- 2. HISTORY.md sync check ---
    missing = check_history_md(commits)
    if missing:
        print()
        print(f"  ⚠️  HISTORY.md 缺少 {len(missing)} 个提交的记录:")
        for m in missing[:5]:
            display = m[:70] + "…" if len(m) > 70 else m
            print(f"      - {display}")
        if len(missing) > 5:
            print(f"      ... 及其他 {len(missing) - 5} 条")

    # --- 3. Dirty state ---
    dirty = check_dirty_state()
    if dirty:
        print()
        print(f"  ⚠️  Git 工作区有 {len(dirty)} 个未提交变更:")
        for d in dirty[:10]:
            print(f"      {d}")
        if len(dirty) > 10:
            print(f"      ... 及其他 {len(dirty) - 10} 个文件")

    # --- 4. Stale scripts ---
    registry = load_registry()
    if registry:
        recent_modules = get_recently_changed_modules(5)
        stale = check_stale_scripts(registry, recent_modules)
        if stale:
            print()
            print(f"  ⚠️  {len(stale)} 个相关脚本可能过时:")
            for s in stale:
                print(f"      - {s}")

    # --- 4.5. Manifest consistency scan ---
    manifest_warnings = scan_manifests()
    if manifest_warnings:
        print()
        print(f"  ⚠️  __manifest__.json 不一致 ({len(manifest_warnings)}):")
        for w in manifest_warnings[:8]:
            print(f"      - {w}")
        if len(manifest_warnings) > 8:
            print(f"      ... 及其他 {len(manifest_warnings) - 8} 条")

    # --- 4.6. Registry deprecation check ---
    registry_warnings = check_registry_deprecation()
    if registry_warnings:
        print()
        print(f"  ⚠️  注册表弃用警告:")
        for w in registry_warnings:
            print(f"      - {w}")

    # --- 5. SESSION.md — current work state ---
    session_path = PROJECT_ROOT / ".claude" / "SESSION.md"
    if session_path.exists():
        try:
            content = session_path.read_text(encoding="utf-8")
            print()
            print("  📍 当前工作状态 (SESSION.md):")
            header_icons = {"进行中": "🟢", "下一步": "📋", "上次踩坑": "⚠️"}

            for section_name in ["进行中", "下一步", "上次踩坑"]:
                # Find section header: "## ... 进行中 ..."
                found = False
                in_section = False
                lines_out = []
                for line in content.split("\n"):
                    stripped = line.strip()
                    # Check if this line is the target section header
                    if stripped.startswith("##") and section_name in stripped:
                        in_section = True
                        found = True
                        continue
                    # Stop at the next section header or separator
                    if in_section and (stripped.startswith("##") or stripped.startswith("---")):
                        break
                    if in_section and stripped and not stripped.startswith(">"):
                        if len(lines_out) >= 4:
                            lines_out.append("...")
                            break
                        lines_out.append(stripped)

                if found and lines_out:
                    icon = header_icons.get(section_name, "•")
                    print(f"    {icon} {section_name}:")
                    for lo in lines_out:
                        print(f"      {lo}")
        except Exception:
            pass

    # --- 6. TROUBLESHOOTING.md — recent pitfalls ---
    trouble_path = PROJECT_ROOT / ".claude" / "TROUBLESHOOTING.md"
    if trouble_path.exists():
        try:
            content = trouble_path.read_text(encoding="utf-8")
            # Count total entries
            entry_count = content.count("### ")
            if entry_count > 0:
                print()
                print(f"  🩹 踩坑记录: {entry_count} 条已收录 (TROUBLESHOOTING.md)")
        except Exception:
            pass

    # --- 7. Summary ---
    print()
    print("=" * 55)
    issues = (
        len(missing)
        + (1 if dirty else 0)
        + len(check_stale_scripts(registry, get_recently_changed_modules(5)))
        + len(manifest_warnings)
        + len(registry_warnings)
    )
    if issues == 0:
        print("  ✅ 一切正常，可以开始工作")
    else:
        print(f"  ⚠️  {issues} 个问题需要关注")
    print("=" * 55)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
