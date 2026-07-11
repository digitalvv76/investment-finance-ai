#!/usr/bin/env python3
"""Session-end development checklist — self-audit before wrapping up.

Run manually at session end. Checks:
  1. Git clean state
  2. Tests passing
  3. HISTORY.md updated
  4. Environment credentials valid
  5. Stale related scripts
  6. Remote sync status

Non-blocking — produces a human-readable checklist. Use exit code to detect issues.
"""
import json
import os
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


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kwargs)


def check(label: str, passed: bool, detail: str = "") -> str:
    """Format a checklist line."""
    icon = "✅" if passed else "❌"
    line = f"  [{icon}] {label}"
    if detail:
        line += f" — {detail}"
    return line


def warn(label: str, detail: str = "") -> str:
    """Format a warning line."""
    line = f"  [⚠️] {label}"
    if detail:
        line += f" — {detail}"
    return line


def todo(label: str) -> str:
    """Format a to-do line."""
    return f"  [⬜] {label}"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_git_clean() -> tuple[bool, str]:
    """Check if working tree is clean."""
    r = run(["git", "status", "--short"], cwd=str(PROJECT_ROOT))
    if r.returncode != 0:
        return False, "git 命令失败"
    lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
    changed = [l for l in lines if not l.startswith("??")]
    if not changed:
        return True, "工作区干净"
    return False, f"{len(changed)} 个未提交文件"


def check_tests() -> tuple[bool, str]:
    """Run full test suite (with generous timeout for 313 tests)."""
    # --tb=no for fast output; -rE prints one "ERROR path::test - reason" line per
    # errored test so we can verify EACH error is the tolerated ChromaDB one
    # (not a blanket substring match that would swallow a real error co-occurring
    # with a vector_store error — V1 gate-hygiene concern, 2026-07-11).
    r = run(
        ["python", "-m", "pytest", "tests/", "-q", "--tb=no", "-rE"],
        cwd=str(NEWS_MONITOR),
        timeout=600,  # 10 minutes — full suite takes ~200s
    )
    output = r.stdout.strip() + "\n" + r.stderr.strip()
    # Parse result line like "313 passed in 200s"
    for line in output.split("\n"):
        stripped = line.strip()
        if "passed" in stripped:
            if "failed" in stripped:
                return False, stripped
            # ChromaDB vector_store errors on Windows are a known platform issue.
            # Tolerate ONLY when EVERY errored test is test_vector_store — a real
            # error elsewhere must still fail the gate even if a vector_store
            # error is also present.
            if "error" in stripped:
                error_nodes = [
                    l.strip() for l in output.split("\n")
                    if l.strip().startswith("ERROR ")
                ]
                non_vs = [l for l in error_nodes if "test_vector_store" not in l]
                if non_vs or not error_nodes:
                    # non_vs: a real error slipped in. not error_nodes: errors
                    # reported in the summary but no per-node lines to vet → don't
                    # blindly tolerate.
                    detail = "; ".join(non_vs[:3]) if non_vs else "error nodes unresolved"
                    return False, f"{stripped} | non-vector_store errors: {detail}"
            if "passed" in stripped and ("in" in stripped or "s " in stripped):
                return True, stripped
    # Fallback: check return code
    if r.returncode == 0:
        return True, f"全部通过 (exit 0)"
    return False, "无法解析测试结果"


def check_history_updated() -> tuple[bool, str]:
    """Check if HISTORY.md has been modified today."""
    history_path = PROJECT_ROOT / "HISTORY.md"
    if not history_path.exists():
        return False, "HISTORY.md 不存在"

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        content = history_path.read_text(encoding="utf-8")
        if today in content:
            # Count lines in today's section
            idx = content.find(f"## {today}")
            section = content[idx:]
            next_section = section.find("\n## ", len(f"## {today}"))
            if next_section != -1:
                section = section[:next_section]
            # Count non-empty, non-header lines
            content_lines = [l for l in section.split("\n") if l.strip() and not l.startswith("##")]
            if len(content_lines) >= 3:
                return True, f"今日已记录 ({len(content_lines)} 行)"
            else:
                return False, f"今日内容过少 ({len(content_lines)} 行)"
        else:
            return False, "今日无记录"
    except Exception as e:
        return False, f"读取失败: {e}"

    # Check file modification time
    mtime = os.path.getmtime(str(history_path))
    mtime_dt = datetime.fromtimestamp(mtime)
    hours_ago = (datetime.now() - mtime_dt).total_seconds() / 3600
    if hours_ago < 2:
        return True, f"最后修改 {hours_ago:.1f} 小时前"
    return False, f"最后修改 {hours_ago:.1f} 小时前"


def check_env() -> tuple[bool, str]:
    """Run verify_env.py."""
    script = NEWS_MONITOR / "scripts" / "verify_env.py"
    if not script.exists():
        return False, "verify_env.py 不存在"
    r = run(["python", str(script)], cwd=str(PROJECT_ROOT), timeout=15)
    if r.returncode == 0:
        return True, "凭证完整"
    # Get last meaningful line
    lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
    last = lines[-1] if lines else "未知错误"
    # Truncate
    if len(last) > 60:
        last = last[:57] + "..."
    return False, last


def check_remote() -> tuple[bool, str]:
    """Check if local is ahead/behind remote."""
    r = run(["git", "rev-list", "--count", "HEAD..origin/main"], cwd=str(PROJECT_ROOT))
    if r.returncode != 0:
        return False, "无法连接远程"
    ahead = r.stdout.strip()
    if ahead and ahead != "0":
        return False, f"本地领先 {ahead} 个提交 (需推送)"

    r2 = run(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=str(PROJECT_ROOT))
    behind = r2.stdout.strip()
    if behind and behind != "0":
        return False, f"本地落后 {behind} 个提交 (需拉取)"

    return True, "已同步"


def check_stale_scripts() -> list[str]:
    """Check for stale related scripts across all changed modules."""
    # Get files changed in working tree vs HEAD
    r = run(["git", "diff", "--name-only", "HEAD"], cwd=str(PROJECT_ROOT))
    changed = [f.strip() for f in r.stdout.split("\n") if f.strip() and f.startswith("news-monitor/")]

    if not REGISTRY_PATH.exists():
        return []

    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            registry = json.load(f)
    except Exception:
        return []

    modules = registry.get("modules", {})
    warnings = []
    for f in changed:
        # Convert to module key
        if not f.endswith(".py") or "test" in f or "scripts/" in f:
            continue
        key = f.replace("news-monitor/", "")
        entry = modules.get(key, {})
        related = entry.get("related_scripts", [])
        if not related:
            continue

        mod_path = NEWS_MONITOR / key
        if not mod_path.exists():
            continue
        mod_mtime = os.path.getmtime(str(mod_path))

        for script_rel in related:
            script_path = NEWS_MONITOR / script_rel
            if not script_path.exists():
                continue
            script_mtime = os.path.getmtime(str(script_path))
            if mod_mtime > script_mtime:
                delta_hours = (mod_mtime - script_mtime) / 3600
                warnings.append(f"{script_rel} (依赖 {key}, 落后 {delta_hours:.0f}h)")

    return warnings


def check_unmapped_files() -> list[str]:
    """Detect source files not in the registry."""
    if not REGISTRY_PATH.exists():
        return []

    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            registry = json.load(f)
    except Exception:
        return []

    modules = registry.get("modules", {})
    registered = set(modules.keys())
    unmapped = []

    # Scan news-monitor/ for .py files that should be in registry
    for py_file in NEWS_MONITOR.glob("**/*.py"):
        if py_file.name.startswith("_"):
            continue
        rel = str(py_file.relative_to(NEWS_MONITOR)).replace("\\", "/")
        # Skip tests, scripts, __init__, and already registered
        if "tests/" in rel or "scripts/" in rel or rel.startswith("__"):
            continue
        if rel not in registered:
            unmapped.append(rel)

    return unmapped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print()
    print("=" * 50)
    print("  会话结束检查清单")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)
    print()

    issues = 0

    # Git clean
    clean, detail = check_git_clean()
    print(check("Git 工作区", clean, detail))
    if not clean:
        issues += 1

    # Tests
    tests_ok, detail = check_tests()
    print(check("测试套件", tests_ok, detail))
    if not tests_ok:
        issues += 1

    # HISTORY.md
    hist_ok, detail = check_history_updated()
    print(check("HISTORY.md", hist_ok, detail))
    if not hist_ok:
        issues += 1

    # Env
    env_ok, detail = check_env()
    print(check("环境凭证", env_ok, detail))
    if not env_ok:
        issues += 1

    # Stale scripts
    stale = check_stale_scripts()
    if stale:
        for s in stale:
            print(warn(s))
        issues += len(stale)

    # Unmapped files
    unmapped = check_unmapped_files()
    if unmapped:
        print()
        print(f"  [⚠️] {len(unmapped)} 个模块未在 registry 中注册:")
        for u in unmapped[:5]:
            print(f"      - {u}")
        if len(unmapped) > 5:
            print(f"      ... 及其他 {len(unmapped) - 5} 个")

    # Remote sync
    remote_ok, detail = check_remote()
    if remote_ok:
        print(check("远程同步", True, detail))
    else:
        print(todo(f"远程同步 — {detail}"))

    # Summary
    print()
    print("=" * 50)
    if issues == 0:
        print("  ✅ 全部就绪，可以结束会话")
    else:
        print(f"  ⚠️  {issues} 个问题待解决")
    print("=" * 50)
    print()

    return min(issues, 1)  # 0 or 1


if __name__ == "__main__":
    sys.exit(main())
