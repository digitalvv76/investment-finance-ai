"""Install Financial News Monitor as a Windows service using NSSM.

Usage:
    python scripts/install_service.py install    # Install the service
    python scripts/install_service.py remove     # Remove the service
    python scripts/install_service.py status     # Check service status

Requirements:
    - NSSM (Non-Sucking Service Manager) installed and in PATH
      Download: https://nssm.cc/download
      Or: winget install nssm
    - Run as Administrator
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

SERVICE_NAME = "NewsMonitor"
PROJECT_DIR = Path(__file__).resolve().parent.parent
MAIN_SCRIPT = PROJECT_DIR / "main.py"
PYTHON_EXE = sys.executable


def check_admin() -> bool:
    """Check if script is running with admin privileges."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def check_nssm() -> bool:
    """Check if nssm is available."""
    try:
        subprocess.run(["nssm", "version"], capture_output=True, timeout=5, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install():
    """Install the News Monitor as a Windows service."""
    if not check_admin():
        print("ERROR: This script must be run as Administrator.")
        print("Right-click Command Prompt/PowerShell → Run as Administrator")
        sys.exit(1)

    if not check_nssm():
        print("ERROR: NSSM not found. Install it first:")
        print("  winget install nssm")
        print("  Or download from: https://nssm.cc/download")
        sys.exit(1)

    print(f"Installing {SERVICE_NAME} service...")
    print(f"  Python: {PYTHON_EXE}")
    print(f"  Working dir: {PROJECT_DIR}")
    print(f"  Entry point: {MAIN_SCRIPT}")

    # Remove existing service if present
    subprocess.run(["nssm", "stop", SERVICE_NAME], capture_output=True)
    subprocess.run(["nssm", "remove", SERVICE_NAME, "confirm"], capture_output=True)

    # Install
    subprocess.run(
        ["nssm", "install", SERVICE_NAME, PYTHON_EXE, str(MAIN_SCRIPT)],
        check=True,
    )

    # Configure service
    app_dir = str(PROJECT_DIR)
    configs = {
        "AppDirectory": app_dir,
        "AppStdout": str(PROJECT_DIR / "logs" / "stdout.log"),
        "AppStderr": str(PROJECT_DIR / "logs" / "stderr.log"),
        "AppRotateFiles": "1",
        "AppRotateOnline": "1",
        "AppRotateBytes": "10485760",  # 10 MB
        "Description": "Financial News Monitor — 24/7 news collection and analysis",
        "Start": "SERVICE_AUTO_START",
        "AppRestartDelay": "10000",  # 10 seconds
        "AppExit": "Default Restart",
    }

    # Load .env from project root BEFORE collecting env vars
    try:
        from dotenv import load_dotenv, find_dotenv
        _env_path = find_dotenv(usecwd=True)
        if _env_path:
            load_dotenv(_env_path)
            print(f"  Loaded .env from {_env_path}")
    except ImportError:
        print("  WARNING: python-dotenv not installed, using only system env vars")

    # Collect ALL environment variables needed by the service
    required_env_vars = [
        "TELEGRAM_BOT_TOKEN",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "TWITTER_AUTH_TOKEN",
        "FRED_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "PUSHOVER_APP_TOKEN",
        "PUSHOVER_USER_KEY",
        "PUSHOVER_USER_KEY_2",
        "TELEGRAM_CHAT_ID_2",  # Second Telegram account
        "TELEGRAM_CHAT_ID_3",  # Third Telegram account
        "WEB_PORT",          # Enable web dashboard (8080)
    ]

    env_lines = []
    for env_key in required_env_vars:
        val = os.environ.get(env_key, "")
        if val:
            env_lines.append(f"{env_key}={val}")
            print(f"  Env: {env_key}=***set***")
        else:
            if env_key == "WEB_PORT":
                # Default WEB_PORT to 8080 for 24/7 service
                env_lines.append("WEB_PORT=8080")
                print(f"  Env: WEB_PORT=8080 (default)")
            else:
                print(f"  Env: {env_key}=<not set, skipping>")

    if env_lines:
        # NSSM AppEnvironmentExtra sets all env vars at once (newline-separated)
        subprocess.run(
            ["nssm", "set", SERVICE_NAME, "AppEnvironmentExtra", "\n".join(env_lines)],
            check=True,
        )
        print(f"  Total: {len(env_lines)} environment variables configured")

    for key, value in configs.items():
        subprocess.run(["nssm", "set", SERVICE_NAME, key, value], check=True)

    print(f"\nService '{SERVICE_NAME}' installed successfully!")
    print(f"\nStart it now? Run:")
    print(f"  nssm start {SERVICE_NAME}")
    print(f"\nOr via Services GUI:")
    print(f"  services.msc  → find '{SERVICE_NAME}' → Start")


def remove():
    """Remove the News Monitor service."""
    if not check_admin():
        print("ERROR: This script must be run as Administrator.")
        sys.exit(1)

    print(f"Removing {SERVICE_NAME} service...")
    subprocess.run(["nssm", "stop", SERVICE_NAME], capture_output=True)
    subprocess.run(["nssm", "remove", SERVICE_NAME, "confirm"], check=True)
    print(f"Service '{SERVICE_NAME}' removed.")


def status():
    """Check service status."""
    try:
        result = subprocess.run(
            ["nssm", "status", SERVICE_NAME],
            capture_output=True, text=True, timeout=5,
        )
        print(f"Service '{SERVICE_NAME}': {result.stdout.strip()}")
    except FileNotFoundError:
        print("NSSM not installed.")
    except subprocess.TimeoutExpired:
        print("NSSM status check timed out.")


def main():
    parser = argparse.ArgumentParser(description="News Monitor Windows Service Manager")
    parser.add_argument(
        "action", choices=["install", "remove", "status"],
        help="Action to perform",
    )
    args = parser.parse_args()

    if args.action == "install":
        install()
    elif args.action == "remove":
        remove()
    elif args.action == "status":
        status()


if __name__ == "__main__":
    main()
