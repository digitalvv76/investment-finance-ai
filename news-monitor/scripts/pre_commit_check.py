#!/usr/bin/env python3
"""Pre-commit validation gate — triggered by PreToolUse hook on 'git commit'.

Checks:
  1. Runs targeted tests for staged source modules
  2. Warns if related_scripts are stale
  3. Warns if HISTORY.md is not staged

Exit 1 if tests fail (blocks commit). Exit 0 with warnings otherwise (allows commit).
Skip tests via [skip-tests] in commit message (coupling check still runs).
"""
import json
import os
import re
import subprocess
import sys
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

VALID_TYPES = ["feat", "fix", "refactor", "test", "docs", "chore"]
VALID_PATTERN = re.compile(r'^(feat|fix|refactor|test|docs|chore)(\(.+?\))?:\s.+')


def run_git(*args: str) -> str:
    """Run a git command, return stdout or empty string."""
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


def get_staged_files() -> list[str]:
    """Return list of staged files (relative to repo root)."""
    out = run_git("diff", "--cached", "--name-only")
    if not out:
        return []
    return [f.strip() for f in out.split("\n") if f.strip()]


def get_commit_message() -> str:
    """Try to extract commit message from hook arguments or prepared file."""
    # PreToolUse passes $ARGUMENTS which includes -m "msg"
    args = os.environ.get("ARGUMENTS", "")
    # Try to extract message from -m flag
    m_match = re.search(r'-m\s+"([^"]*)"', args)
    if m_match:
        return m_match.group(1)
    m_match = re.search(r"-m\s+'([^']*)'", args)
    if m_match:
        return m_match.group(1)
    m_match = re.search(r"-m\s+(\S+)", args)
    if m_match:
        return m_match.group(1)
    # Check if there's a prepared commit message file
    commit_msg_file = PROJECT_ROOT / ".git" / "COMMIT_EDITMSG"
    if commit_msg_file.exists():
        try:
            return commit_msg_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return ""


def check_commit_format(msg: str) -> tuple[bool, str]:
    """Check commit message follows conventional format. Returns (valid, reason)."""
    if not msg:
        return True, "empty (skipped)"
    if "[skip-tests]" in msg or "[quick-fix]" in msg:
        # Strip skip markers and check the rest
        clean = msg.replace("[skip-tests]", "").replace("[quick-fix]", "").strip()
        if VALID_PATTERN.match(clean):
            return True, "valid (with skip marker)"
        return False, f"invalid format after skip marker: '{clean[:60]}'"
    if VALID_PATTERN.match(msg):
        return True, "valid"
    return False, f"invalid format: '{msg[:60]}'. Must be: type: description (types: {', '.join(VALID_TYPES)})"


def load_manifests() -> dict:
    """Load all __manifest__.json files from news-monitor subdirectories."""
    all_modules = {}
    for manifest_path in NEWS_MONITOR.glob("*/__manifest__.json"):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                data = json.load(f)
            mods = data.get("modules", {})
            all_modules.update(mods)
        except Exception:
            pass
    return all_modules


def load_registry() -> dict:
    """Load module registry — manifests first, legacy registry as fallback."""
    modules = load_manifests()
    if modules:
        return {"modules": modules}
    # Fallback to legacy registry
    if REGISTRY_PATH.exists():
        try:
            with open(REGISTRY_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def staged_to_modules(staged: list[str]) -> list[str]:
    """Convert staged file paths to module keys (relative to news-monitor/)."""
    modules = []
    for f in staged:
        if f.startswith("news-monitor/") and f.endswith(".py"):
            rel = f.replace("news-monitor/", "")
            if "/test" not in rel and "scripts/" not in rel:
                modules.append(rel)
    return modules


def get_tests_for_modules(registry: dict, module_keys: list[str]) -> set[str]:
    """Get the union of all test files for given modules. '__ALL__' means full suite."""
    modules = registry.get("modules", {})
    tests = set()
    for key in module_keys:
        entry = modules.get(key, {})
        mod_tests = entry.get("tests", [])
        for t in mod_tests:
            if t == "__ALL__":
                return {"__ALL__"}
            tests.add(t)
        # Also run tests from also_tests
        also = entry.get("also_tests", [])
        for a in also:
            if a == "__ALL__":
                return {"__ALL__"}
            # also_tests can reference other modules whose tests we should run
            other_entry = modules.get(a, {})
            other_tests = other_entry.get("tests", [])
            for ot in other_tests:
                if ot == "__ALL__":
                    return {"__ALL__"}
                tests.add(ot)
    return tests


def check_stale_scripts(registry: dict, module_keys: list[str]) -> list[str]:
    """Check if related_scripts for changed modules are older than the module."""
    import os as _os
    warnings = []
    modules = registry.get("modules", {})
    for key in module_keys:
        entry = modules.get(key, {})
        related = entry.get("related_scripts", [])
        if not related:
            continue
        mod_path = NEWS_MONITOR / key
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
                warnings.append(f"{script_rel} (落后 {delta_hours:.0f}h)")
    return warnings


def run_tests(test_files: set[str]) -> tuple[bool, str]:
    """Run pytest on the given test files. Returns (passed, output_summary)."""
    if not test_files:
        return True, "无测试文件"

    if "__ALL__" in test_files:
        cmd = ["python", "-m", "pytest", "tests/", "-q", "--tb=short", "-x"]
    else:
        test_list = [str(NEWS_MONITOR / t) for t in sorted(test_files)]
        cmd = ["python", "-m", "pytest"] + test_list + ["-q", "--tb=short", "-x"]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(NEWS_MONITOR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        output = result.stdout.strip() + "\n" + result.stderr.strip()
        # Get last few lines for summary
        lines = [l for l in output.split("\n") if l.strip()]
        summary = "\n".join(lines[-8:]) if len(lines) > 8 else "\n".join(lines)
        return result.returncode == 0, summary
    except subprocess.TimeoutExpired:
        return False, "测试超时 (120s)"
    except Exception as e:
        return False, f"测试执行失败: {e}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    staged = get_staged_files()
    if not staged:
        print("[pre-commit] 无暂存文件，跳过检查")
        return 0

    commit_msg = get_commit_message()
    skip_tests = "[skip-tests]" in commit_msg or "[quick-fix]" in commit_msg

    # --- 0. Commit format check ---
    if not skip_tests:
        fmt_valid, fmt_reason = check_commit_format(commit_msg)
        if not fmt_valid:
            print("=" * 50)
            print("  Pre-Commit 检查")
            print("=" * 50)
            print(f"\n  ❌ 提交信息格式错误: {fmt_reason}")
            print(f"  合法类型: {', '.join(VALID_TYPES)}")
            print(f"  格式: type: description")
            print(f"  示例: feat: add momentum strategy module")
            print(f"  紧急绕过: 使用 [skip-tests] 标记")
            return 1

    module_keys = staged_to_modules(staged)
    if not module_keys:
        if skip_tests:
            print("[pre-commit] 无源码变更 (仅脚本/配置)，跳过")
        return 0

    print("=" * 50)
    print("  Pre-Commit 检查")
    print("=" * 50)
    print(f"  暂存模块: {', '.join(module_keys[:5])}")
    if len(module_keys) > 5:
        print(f"            ... 及其他 {len(module_keys) - 5} 个")

    registry = load_registry()
    warnings = []

    # --- 0. Manifest gate ---
    if not skip_tests:
        modules = registry.get("modules", {})
        unregistered = [k for k in module_keys if k not in modules]
        if unregistered:
            print(f"\n  ❌ 未注册模块 (缺少 __manifest__.json):")
            for u in unregistered:
                print(f"      - {u}")
            print(f"\n  请创建对应目录的 __manifest__.json 并注册此模块。")
            print(f"  紧急绕过: 使用 [skip-tests] 标记")
            return 1

    # --- 0.5 Missing test warning ---
    if not skip_tests:
        modules = registry.get("modules", {})
        missing_tests = []
        for k in module_keys:
            entry = modules.get(k, {})
            tests = entry.get("tests", [])
            if not tests:
                missing_tests.append(k)
        if missing_tests:
            print(f"\n  ⚠️  以下模块无注册测试:")
            for m in missing_tests:
                print(f"      - {m}")
            print(f"  建议添加测试并更新 __manifest__.json")

    # --- 1. Run tests ---
    if skip_tests:
        print("\n  ⏭️  跳过测试 ([skip-tests])")
    else:
        tests = get_tests_for_modules(registry, module_keys)
        print(f"\n  运行测试: {'全部' if '__ALL__' in tests else ', '.join(sorted(tests)[:5])}")
        passed, output = run_tests(tests)
        if not passed:
            print(f"\n  ❌ 测试失败!")
            print(f"  {output}")
            print("\n  提示: 使用 [skip-tests] 标记跳过 (仅限紧急修复)")
            return 1
        print("  ✅ 测试通过")

    # --- 2. Stale scripts check ---
    stale = check_stale_scripts(registry, module_keys)
    if stale:
        print(f"\n  ⚠️  相关脚本可能过时:")
        for s in stale:
            print(f"      - {s}")
        warnings.extend(stale)

    # --- 3. HISTORY.md check ---
    history_staged = any("HISTORY.md" in f for f in staged)
    if not history_staged and len(module_keys) >= 2:
        print("\n  ⚠️  HISTORY.md 未在暂存区 (建议记录本次变更)")
        warnings.append("HISTORY.md 未更新")

    # --- Summary ---
    print()
    if warnings:
        print(f"  ⚠️  {len(warnings)} 个警告 (不阻塞提交)")
    else:
        print("  ✅ 全部检查通过")

    return 0


if __name__ == "__main__":
    sys.exit(main())
