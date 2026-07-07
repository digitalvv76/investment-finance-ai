#!/usr/bin/env python3
"""Environment verification — run at session start to check credential integrity.

Checks:
  - .env and settings.json exist
  - Critical env vars are set (TELEGRAM, DEEPSEEK, PUSHOVER)
  - .env and settings.json["env"] stay in sync
  - Optional: connectivity check to Telegram / Pushover (5s timeout)

Exit 0 = clean, 1 = issues found.
"""

import io
import json
import logging
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s", stream=sys.stdout)
log = logging.getLogger("verify_env")

CRITICAL_VARS = ["TELEGRAM_BOT_TOKEN", "DEEPSEEK_API_KEY"]
RECOMMENDED_VARS = ["PUSHOVER_APP_TOKEN", "PUSHOVER_USER_KEY", "PUSHOVER_USER_KEY_2", "TELEGRAM_CHAT_ID_2"]
OPTIONAL_VARS = ["FRED_API_KEY", "ALPHA_VANTAGE_API_KEY", "ANTHROPIC_API_KEY"]


def find_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse .env key=value pairs into a dict."""
    if not env_path.is_file():
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


def check_connectivity() -> list[str]:
    """Quick reachability tests. Returns list of warnings."""
    warnings = []
    import urllib.request

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        try:
            url = f"https://api.telegram.org/bot{token}/getMe"
            req = urllib.request.Request(url)
            urllib.request.urlopen(req, timeout=5)
            log.info("  [OK] Telegram API reachable")
        except Exception as e:
            msg = f"Telegram API unreachable: {e}"
            log.warning("  [WARN] %s", msg)
            warnings.append(msg)

    pushover_token = os.environ.get("PUSHOVER_APP_TOKEN", "")
    pushover_users = [
        (os.environ.get("PUSHOVER_USER_KEY", ""), "PUSHOVER_USER_KEY"),
        (os.environ.get("PUSHOVER_USER_KEY_2", ""), "PUSHOVER_USER_KEY_2"),
    ]
    for user_key, var_name in pushover_users:
        if pushover_token and user_key:
            try:
                import urllib.parse
                data = urllib.parse.urlencode({
                    "token": pushover_token, "user": user_key
                }).encode()
                req = urllib.request.Request(
                    "https://api.pushover.net/1/users/validate.json", data=data
                )
                urllib.request.urlopen(req, timeout=5)
                log.info("  [OK] Pushover API reachable (%s)", var_name)
            except Exception as e:
                msg = f"Pushover API unreachable ({var_name}): {e}"
                log.warning("  [WARN] %s", msg)
                warnings.append(msg)

    return warnings


def main() -> int:
    root = find_project_root()
    issues = 0

    log.info("=" * 50)
    log.info("  STATE INTEGRITY CHECK")
    log.info("=" * 50)

    # 1. Check .env
    env_path = root / ".env"
    if env_path.is_file():
        log.info("[OK] .env exists")
    else:
        log.error("[FAIL] .env not found at %s", env_path)
        issues += 1

    # 2. Check settings.json
    settings_path = root / ".claude" / "settings.json"
    settings = {}
    if settings_path.is_file():
        log.info("[OK] settings.json exists")
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if "env" not in settings:
                log.warning("[WARN] settings.json missing 'env' section")
            if "hooks" not in settings:
                log.warning("[WARN] settings.json missing 'hooks' section")
        except json.JSONDecodeError as e:
            log.error("[FAIL] settings.json is malformed JSON: %s", e)
            issues += 1
    else:
        log.error("[FAIL] settings.json not found at %s", settings_path)
        issues += 1

    # 3. Check critical env vars
    log.info("--- Critical credentials ---")
    for var in CRITICAL_VARS:
        val = os.environ.get(var, "")
        if val:
            mask = val[:10] + "..." if len(val) > 10 else "***"
            log.info("  [OK] %s = %s", var, mask)
        else:
            log.error("  [FAIL] %s not set", var)
            issues += 1

    # 4. Check recommended env vars
    log.info("--- Recommended credentials ---")
    for var in RECOMMENDED_VARS:
        val = os.environ.get(var, "")
        if val:
            mask = val[:10] + "..." if len(val) > 10 else "***"
            log.info("  [OK] %s = %s", var, mask)
        else:
            log.warning("  [WARN] %s not set", var)

    # 5. Check optional env vars
    log.info("--- Optional credentials ---")
    for var in OPTIONAL_VARS:
        val = os.environ.get(var, "")
        if val:
            mask = val[:10] + "..." if len(val) > 10 else "***"
            log.info("  [OK] %s = %s", var, mask)
        else:
            log.info("  [--] %s not set (optional)", var)

    # 6. Sync check: .env vs settings.json["env"]
    if env_path.is_file() and settings.get("env"):
        log.info("--- Sync check (.env vs settings.json) ---")
        env_keys = set(k for k, v in parse_env_file(env_path).items() if v)  # skip empty
        settings_env_keys = set(k for k, v in settings["env"].items() if v)  # skip empty
        env_only = env_keys - settings_env_keys
        settings_only = settings_env_keys - env_keys
        if env_only:
            log.warning("  [WARN] In .env but NOT in settings.json: %s", ", ".join(sorted(env_only)))
        if settings_only:
            log.warning("  [WARN] In settings.json but NOT in .env: %s", ", ".join(sorted(settings_only)))
        if not env_only and not settings_only:
            log.info("  [OK] .env and settings.json env section are in sync (%d keys)", len(env_keys))
        if env_only or settings_only:
            issues += 1

    # 7. Connectivity (optional, non-blocking)
    log.info("--- Connectivity ---")
    check_connectivity()

    log.info("=" * 50)
    if issues == 0:
        log.info("  RESULT: ALL CHECKS PASSED")
    else:
        log.warning("  RESULT: %d issue(s) found", issues)
    log.info("=" * 50)

    return 0 if issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
