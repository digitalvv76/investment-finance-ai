"""V2 local test runner — isolated from production ECS.

Runs the full news monitor pipeline locally with:
  - Separate test database (data/v2_test.db)
  - All push channels disabled (Telegram + Pushover)
  - Web dashboard disabled
  - Console logging at INFO level
  - Ctrl+C to stop, or auto-stop after --duration seconds

Usage:
  python scripts/run_v2_local.py                 # Run until Ctrl+C
  python scripts/run_v2_local.py --duration 600  # Auto-stop after 10 min
  python scripts/run_v2_local.py -v              # DEBUG level logging
"""
import argparse
import os
import sys
import asyncio
from pathlib import Path

# Ensure we can import from news-monitor
_pkg_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_pkg_root))


def _monkey_patch_db_path(test_db_path: str):
    """Override ConfigLoader.load_settings to use a test database path.

    This avoids modifying settings.yaml on disk — no restore needed.
    """
    from config.loader import ConfigLoader

    _original_load_settings = ConfigLoader.load_settings

    def _patched_load_settings(self):
        settings = _original_load_settings(self)
        settings.setdefault("storage", {})["sqlite_path"] = test_db_path
        return settings

    ConfigLoader.load_settings = _patched_load_settings


async def run_v2_test(duration_sec: int = 0) -> None:
    """Run the V2 monitor locally. duration_sec=0 means run forever."""
    from main import NewsMonitor

    monitor = NewsMonitor()
    try:
        await monitor.start()

        if duration_sec > 0:
            print(f"\n{'=' * 60}")
            print(f"  V2 LOCAL TEST — running for {duration_sec}s")
            print(f"  Push: DISABLED | Web: DISABLED")
            print(f"  Ctrl+C to stop earlier")
            print(f"{'=' * 60}\n")
            await asyncio.sleep(duration_sec)
        else:
            print(f"\n{'=' * 60}")
            print(f"  V2 LOCAL TEST — running until Ctrl+C")
            print(f"  Push: DISABLED | Web: DISABLED")
            print(f"{'=' * 60}\n")
            while True:
                await asyncio.sleep(60)

    except KeyboardInterrupt:
        print("\n⏹  Stopping V2 test...")
    finally:
        await monitor.stop()
        print("V2 test stopped.")


def main():
    parser = argparse.ArgumentParser(description="V2 local test runner")
    parser.add_argument(
        "--duration", type=int, default=0,
        help="Auto-stop after N seconds (0 = run forever)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging",
    )
    parser.add_argument(
        "--keep-db", action="store_true",
        help="Don't delete test DB on exit",
    )
    args = parser.parse_args()

    # ── Isolation: disable all push channels ──
    os.environ["TELEGRAM_BOT_TOKEN"] = ""
    os.environ["PUSHOVER_APP_TOKEN"] = ""
    os.environ["PUSHOVER_USER_KEY"] = ""
    os.environ["PUSHOVER_USER_KEY_2"] = ""
    os.environ["WEB_PORT"] = "0"

    # ── Test database path ──
    test_db = str(_pkg_root / "data" / "v2_test.db").replace("\\", "/")
    os.environ["V2_TEST_DB"] = test_db

    # ── Monkey-patch DB path before importing main ──
    _monkey_patch_db_path(test_db)

    # ── Logging level ──
    if args.verbose:
        os.environ["LOG_LEVEL"] = "DEBUG"
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        asyncio.run(run_v2_test(duration_sec=args.duration))
    finally:
        # Clean up test DB
        if not args.keep_db:
            db_file = Path(test_db)
            if db_file.exists():
                db_file.unlink()
                print(f"[clean] Cleaned up {test_db}")
            for suffix in ["-wal", "-shm"]:
                wal = Path(test_db + suffix)
                if wal.exists():
                    wal.unlink()
        else:
            print(f"[saved] Test DB kept at {test_db}")

    print("Done.")


if __name__ == "__main__":
    main()
