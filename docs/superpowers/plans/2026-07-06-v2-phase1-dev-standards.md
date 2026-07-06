# V2 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build automated safety nets for the development process — every code change runs tests, every commit follows format, every session ends cleanly.

**Architecture:** Extend the existing `.claude/settings.json` hook system (SessionStart + PreToolUse). Add Python manifest files per module for self-registration. Update `pre_commit_check.py` to gate on manifests and commit format. Add a PreToolUse push-protection hook. Session-end is enforced via memory-based checklist (already written).

**Tech Stack:** Python 3.12, Claude Code hooks, existing pytest infrastructure

## Global Constraints

- Zero changes to production code (news-monitor modules unchanged)
- All hooks must exit 0 for warnings, 1 only for hard blocks
- `[skip-tests]` escape hatch remains for emergency fixes
- `module_registry.json` kept as fallback, not deleted
- All manifests live alongside their modules in `__manifest__.json`

---

### Task 1: Create `__manifest__.json` for all 12 module groups

**Files:**
- Create: `news-monitor/engine/__manifest__.json`
- Create: `news-monitor/bot/__manifest__.json`
- Create: `news-monitor/collector/__manifest__.json`
- Create: `news-monitor/config/__manifest__.json`
- Create: `news-monitor/storage/__manifest__.json`
- Create: `news-monitor/web/__manifest__.json`
- Create: `news-monitor/scripts/__manifest__.json`
- Create: `news-monitor/tests/__manifest__.json`
- Create: `news-monitor/main.py` → entry in root manifest (or include in engine/)

**Interfaces:**
- Produces: `__manifest__.json` files with structure `{"modules": {"path": {"tests": [...], "related_scripts": [...], "also_tests": [...]}}}`

Each manifest file covers all `.py` files in its directory. Format:
```json
{
  "modules": {
    "engine/alert_dispatcher.py": {
      "tests": ["tests/test_alert_dispatcher.py"],
      "related_scripts": ["scripts/test_phone_alert.py"],
      "also_tests": []
    },
    "engine/deep_lane.py": {
      "tests": ["tests/test_deep_lane.py"],
      "related_scripts": ["scripts/acceptance_test.py"],
      "also_tests": ["tests/test_fast_lane.py"]
    },
    ...
  }
}
```

- [ ] **Step 1: Gather module-to-test mapping from existing module_registry.json**

Read `news-monitor/config/module_registry.json` as baseline. Map existing entries to new manifest format.

- [ ] **Step 2: Gather additional modules not in registry**

Use Glob: `news-monitor/**/*.py` (exclude `tests/`, `scripts/`, `__init__.py`). For each module not in the registry, determine tests by naming convention (`test_<module>.py`) or mark as `"tests": []`.

- [ ] **Step 3: Write each `__manifest__.json` file**

Write manifests for: `engine/`, `bot/`, `collector/`, `config/`, `storage/`, `web/`. One manifest per directory, covering all modules within.

Example `news-monitor/engine/__manifest__.json`:
```json
{
  "modules": {
    "engine/alert_dispatcher.py": {
      "tests": ["tests/test_alert_dispatcher.py"],
      "related_scripts": ["scripts/test_phone_alert.py"],
      "also_tests": []
    },
    "engine/deep_lane.py": {
      "tests": ["tests/test_deep_lane.py"],
      "related_scripts": [],
      "also_tests": ["tests/test_fast_lane.py"]
    },
    "engine/fast_lane.py": {
      "tests": ["tests/test_fast_lane.py"],
      "related_scripts": ["scripts/acceptance_test.py"],
      "also_tests": []
    },
    "engine/priority.py": {
      "tests": ["tests/test_priority.py"],
      "related_scripts": [],
      "also_tests": ["tests/test_fast_lane.py", "tests/test_deep_lane.py"]
    },
    "engine/strategic_detector.py": {
      "tests": ["tests/test_strategic_detector.py"],
      "related_scripts": ["scripts/score_training_cases.py", "scripts/backtest_training_docx.py"],
      "also_tests": []
    },
    "engine/relevance.py": {
      "tests": ["tests/test_impact_push.py"],
      "related_scripts": ["scripts/score_all_events.py", "scripts/backtest_signal.py"],
      "also_tests": []
    },
    "engine/entity_extractor.py": {
      "tests": ["tests/test_entity_extractor.py"],
      "related_scripts": ["scripts/acceptance_test.py"],
      "also_tests": []
    },
    "engine/impact_evaluator.py": {
      "tests": ["tests/test_impact_evaluator.py"],
      "related_scripts": ["scripts/acceptance_test.py"],
      "also_tests": []
    },
    "engine/impact_collector.py": {
      "tests": ["tests/test_impact_push.py"],
      "related_scripts": ["scripts/calibrate_thresholds.py"],
      "also_tests": []
    },
    "engine/impact_learner.py": {
      "tests": [],
      "related_scripts": [],
      "also_tests": []
    },
    "engine/sentiment.py": {
      "tests": ["tests/test_sentiment.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "engine/cluster.py": {
      "tests": ["tests/test_cluster.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "engine/curator.py": {
      "tests": ["tests/test_curator.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "engine/learner.py": {
      "tests": ["tests/test_learner.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "engine/event_matcher.py": {
      "tests": ["tests/test_event_matcher.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "engine/content_filter.py": {
      "tests": ["tests/test_content_filter.py"],
      "related_scripts": [],
      "also_tests": []
    },
    "engine/actionability_review.py": {
      "tests": [],
      "related_scripts": [],
      "also_tests": []
    },
    "engine/trainer.py": {
      "tests": [],
      "related_scripts": [],
      "also_tests": []
    }
  }
}
```

- [ ] **Step 4: Write remaining manifests**

`news-monitor/bot/__manifest__.json` — telegram_bot, handlers, formatters, translator, digest
`news-monitor/collector/__manifest__.json` — scheduler, rss_fetcher, twitter_fetcher, chinese_fetcher, finnhub_fetcher, playwright_fetcher, api_fetcher, dedup, exchange_calendar
`news-monitor/config/__manifest__.json` — loader
`news-monitor/storage/__manifest__.json` — database, models, vector_store
`news-monitor/web/__manifest__.json` — server, routes, auth, sse_manager

- [ ] **Step 5: Commit all manifests**

```bash
git add news-monitor/*/__manifest__.json
git commit -m "feat: add __manifest__.json for all 12 module groups

Each module directory now self-registers its test dependencies.
Replaces manual module_registry.json maintenance.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Update pre_commit_check.py — commit format + manifest gate

**Files:**
- Modify: `news-monitor/scripts/pre_commit_check.py`

**Interfaces:**
- Consumes: `__manifest__.json` files from each module directory
- Produces: Updated check that loads manifests instead of `module_registry.json`

- [ ] **Step 1: Add commit message format validation**

Add a function `check_commit_format(msg: str) -> tuple[bool, str]`:
```python
VALID_TYPES = ["feat", "fix", "refactor", "test", "docs", "chore"]
VALID_PATTERN = re.compile(r'^(feat|fix|refactor|test|docs|chore)(\(.+?\))?:\s.+')

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
```

Call this in `main()` after getting `commit_msg`. If format is invalid, print error and `return 1`.

- [ ] **Step 2: Add manifest loading function**

```python
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
```

- [ ] **Step 3: Update `load_registry()` to try manifests first, fall back to module_registry.json**

```python
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
```

- [ ] **Step 4: Add manifest gate — refuse commit if changed modules have no manifest**

In `main()`, after identifying `module_keys`:
```python
# --- 0. Manifest gate ---
if not skip_tests:
    registry = load_registry()
    modules = registry.get("modules", {})
    unregistered = [k for k in module_keys if k not in modules]
    if unregistered:
        print(f"\n  ❌ 未注册模块 (缺少 __manifest__.json):")
        for u in unregistered:
            print(f"      - {u}")
        print(f"\n  请创建对应目录的 __manifest__.json 并注册此模块。")
        print(f"  紧急绕过: 使用 [skip-tests] 标记")
        return 1
```

- [ ] **Step 5: Add missing test check**

After the manifest gate:
```python
# --- 0.5 Missing test warning ---
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
```

This is a warning (doesn't block commit), but makes the gap visible.

- [ ] **Step 6: Run existing tests to verify no regression**

```bash
cd news-monitor && python -m pytest tests/test_config.py -q
```

- [ ] **Step 7: Commit**

```bash
git add news-monitor/scripts/pre_commit_check.py
git commit -m "feat: add commit format check + manifest gate to pre-commit

- Validate commit message format (feat/fix/refactor/test/docs/chore)
- Load __manifest__.json instead of module_registry.json
- Block commit for unregistered modules
- Warn on modules without tests

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Update session_startup.py — manifest scan + deprecation warning

**Files:**
- Modify: `news-monitor/scripts/session_startup.py`

- [ ] **Step 1: Add manifest consistency scan**

Add a function that compares actual `.py` files on disk against `__manifest__.json` entries:
```python
def scan_manifests() -> list[str]:
    """Scan for manifest inconsistencies. Returns warning messages."""
    import json as _json
    warnings = []
    news_root = Path(__file__).resolve().parent.parent
    
    # Check each directory with a manifest
    for manifest_path in sorted(news_root.glob("*/__manifest__.json")):
        dir_name = manifest_path.parent.name
        if dir_name in ("tests", "__pycache__"):
            continue
        try:
            with open(manifest_path, encoding="utf-8") as f:
                data = _json.load(f)
        except Exception as e:
            warnings.append(f"{manifest_path}: 无法解析 — {e}")
            continue
        
        registered = set(data.get("modules", {}).keys())
        
        # Find actual .py files in this directory (excluding __init__.py)
        actual = set()
        for py_file in manifest_path.parent.glob("*.py"):
            if py_file.name.startswith("__"):
                continue
            rel = f"{dir_name}/{py_file.name}"
            actual.add(rel)
        
        # Also check subdirectories (e.g., bot/ has formatters.py, handlers.py, etc.)
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
```

Call this during session startup and display any warnings.

- [ ] **Step 2: Add module_registry.json deprecation check**

If `module_registry.json` is newer than any `__manifest__.json`, warn:
```python
def check_registry_deprecation() -> list[str]:
    """Check if legacy registry is still being updated."""
    warnings = []
    reg_path = Path(__file__).resolve().parent.parent / "config" / "module_registry.json"
    if not reg_path.exists():
        return warnings
    
    reg_mtime = os.path.getmtime(str(reg_path))
    manifest_times = []
    for mf in (Path(__file__).resolve().parent.parent).glob("*/__manifest__.json"):
        manifest_times.append(os.path.getmtime(str(mf)))
    
    newest_manifest = max(manifest_times) if manifest_times else 0
    if reg_mtime > newest_manifest:
        warnings.append("module_registry.json 有更新但 __manifest__.json 未同步 — 迁移后应废弃 registry")
    
    return warnings
```

- [ ] **Step 3: Add autofix command note**

If warnings are found, display:
```
  提示: 运行 python news-monitor/scripts/dev_checklist.py --fix-manifests 自动修复
```

(Don't implement the autofix yet — Phase 2)

- [ ] **Step 4: Commit**

```bash
git add news-monitor/scripts/session_startup.py
git commit -m "feat: add manifest consistency scan to session startup

Detects: unregistered modules, stale manifest entries,
and registry/manifest sync drift. Runs at session start.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Add PreToolUse hook for push protection (v1-stable)

**Files:**
- Modify: `.claude/settings.json`

- [ ] **Step 1: Add push-protection script**

Create `news-monitor/scripts/pre_push_check.py`:
```python
#!/usr/bin/env python3
"""Pre-push check — triggered on 'git push'. Protects v1-stable from direct pushes."""
import os
import sys

def main() -> int:
    args = os.environ.get("ARGUMENTS", "")
    
    # Only check pushes (not force-push or delete)
    if "push" not in args.lower():
        return 0
    
    # Check if pushing to v1-stable directly
    if "v1-stable" in args and "fix/" not in os.environ.get("GIT_BRANCH", ""):
        print("=" * 50)
        print("  ⛔ v1-stable 保护")
        print("=" * 50)
        print()
        print("  不允许直接推送到 v1-stable 分支。")
        print("  V1 生产修复流程:")
        print("    1. git checkout v1-stable")
        print("    2. git checkout -b fix/<description>")
        print("    3. 在 fix 分支上修改 + 提交")
        print("    4. git push origin fix/<description>")
        print("    5. 创建 PR 合入 v1-stable")
        print()
        print("  紧急绕过: export ALLOW_V1_PUSH=1")
        
        if os.environ.get("ALLOW_V1_PUSH") == "1":
            print()
            print("  ⚠️  ALLOW_V1_PUSH=1 — 已绕过保护")
            return 0
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Register hook in settings.json**

Add to `.claude/settings.json` under `hooks.PreToolUse`:
```json
{
  "matcher": "Bash(git push:*)",
  "hooks": [
    {
      "type": "command",
      "command": "python news-monitor/scripts/pre_push_check.py"
    }
  ]
}
```

- [ ] **Step 3: Commit**

```bash
git add news-monitor/scripts/pre_push_check.py .claude/settings.json
git commit -m "feat: add pre-push hook protecting v1-stable branch

Blocks direct pushes to v1-stable. Fixes must go through
fix/* branches. ALLOW_V1_PUSH=1 override for emergencies.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Add module_registry.json deprecation notice

**Files:**
- Modify: `news-monitor/config/module_registry.json`

- [ ] **Step 1: Add deprecation notice to registry**

Add a top-level key:
```json
{
  "_deprecated": "This file is deprecated as of 2026-07-06. Use __manifest__.json files in each module directory instead. See docs/superpowers/specs/2026-07-06-v2-phase1-dev-standards-design.md",
  "_migration_status": "Keeping for backward compatibility during Phase 1 transition.",
  "modules": {
    ...existing content unchanged...
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add news-monitor/config/module_registry.json
git commit -m "chore: deprecate module_registry.json in favor of __manifest__.json

Migration to per-directory manifests. Registry kept as fallback
during Phase 1 transition period.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end verification

- [ ] **Step 1: Test commit format check**

```bash
# Should FAIL (invalid format)
cd D:/class1 && git add deploy.sh && git commit -m "added deploy script" 2>&1
# Expect: pre-commit_check fails with "invalid format: 'added deploy script'"

# Should PASS
git commit -m "feat: add deploy script" 2>&1
# Expect: pre-commit_check passes
```

Reset with `git reset HEAD~1` after test if needed.

- [ ] **Step 2: Test manifest gate**

Create a temporary test module without manifest:
```bash
echo "# test" > news-monitor/engine/_test_ungated.py
git add news-monitor/engine/_test_ungated.py
git commit -m "feat: test unregistered module" 2>&1
# Expect: FAIL — "未注册模块"
```

Cleanup: `rm news-monitor/engine/_test_ungated.py && git reset HEAD`

- [ ] **Step 3: Test push protection**

```bash
# Should BLOCK direct push to v1-stable
# (test by attempting push, verify check triggers)
echo "test" > /tmp/test_push.txt
```

- [ ] **Step 4: Run full test suite**

```bash
cd news-monitor && python -m pytest tests/ -q 2>&1
# Expect: all pass (or pre-existing skips)
```

- [ ] **Step 5: Commit verification results to HISTORY.md**

---
