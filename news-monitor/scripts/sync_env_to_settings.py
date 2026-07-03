#!/usr/bin/env python3
"""Sync .env to settings.json — .env is the single source of truth.

Usage:
    python scripts/sync_env_to_settings.py          # sync, warn on removals
    python scripts/sync_env_to_settings.py --dry-run # show diff, no write

Reads .env keys -> updates settings.json["env"] section -> writes back.
Preserves all other sections (permissions, hooks, etc.) untouched.
"""

import io
import json
import logging
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s", stream=sys.stdout)
log = logging.getLogger("sync_env_to_settings")


def find_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.is_file():
        log.warning(".env not found at %s", env_path)
        return {}
    result: dict[str, str] = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            result[key] = value
    return result


def load_settings(settings_path: Path) -> dict | None:
    if not settings_path.is_file():
        log.error("settings.json not found at %s", settings_path)
        return None
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log.error("settings.json is malformed JSON: %s", e)
        return None


def sync_env_section(env_vars: dict[str, str], settings: dict) -> tuple[dict, list[str]]:
    old_env = settings.get("env", {})
    removed_keys = [k for k in old_env if k not in env_vars]
    settings["env"] = dict(env_vars)  # shallow copy
    return settings, removed_keys


def write_settings(settings: dict, settings_path: Path) -> bool:
    tmp_path = settings_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp_path.replace(settings_path)  # atomic on same filesystem
        log.info("Wrote settings.json (%d top-level keys)", len(settings))
        return True
    except PermissionError as e:
        log.error("Permission denied writing settings.json: %s", e)
        return False
    except Exception as e:
        log.error("Failed to write settings.json: %s", e)
        return False


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    root = find_project_root()
    env_path = root / ".env"
    settings_path = root / ".claude" / "settings.json"

    log.info("=" * 50)
    log.info("  SYNC .env -> settings.json")
    log.info("=" * 50)

    env_vars = parse_env_file(env_path)
    if not env_vars:
        log.warning(".env is empty or missing. settings.json env section would be cleared.")

    settings = load_settings(settings_path)
    if settings is None:
        return 1

    updated_settings, removed_keys = sync_env_section(env_vars, settings)

    log.info("Keys to write to settings.json[env]: %d", len(env_vars))
    if removed_keys:
        for k in removed_keys:
            log.warning("  [REMOVE] '%s' exists in settings.json but not .env", k)

    # Preserve critical sections
    for section in ["permissions", "hooks"]:
        if section not in updated_settings:
            log.warning("settings.json is missing '%s' section!", section)

    if dry_run:
        log.info("Dry-run mode -- no changes written.")
        log.info("Would set settings.json[env] to: %s",
                  json.dumps(env_vars, indent=2, ensure_ascii=False))
        return 0

    if write_settings(updated_settings, settings_path):
        log.info("Sync complete. %d keys in settings.json[env].", len(env_vars))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
