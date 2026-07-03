#!/usr/bin/env python3
"""State backup — copy critical files to .claude/backups/state/ with rotation.

Runs at session start (SessionStart hook). Keeps last 10 backups.
"""

import io
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s", stream=sys.stdout)
log = logging.getLogger("backup_state")

KEEP = 10


def find_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_source_map(root: Path) -> dict:
    mem_dir = root / ".claude" / "memory"
    memory_files = sorted(mem_dir.glob("*.md")) if mem_dir.is_dir() else []
    return {
        ".env": root / ".env",
        "settings.json": root / ".claude" / "settings.json",
        "HISTORY.md": root / "HISTORY.md",
        "memory_files": memory_files,
    }


def create_backup_dir(backup_root: Path, timestamp: str) -> Path | None:
    dest = backup_root / timestamp
    try:
        dest.mkdir(parents=True, exist_ok=False)
        return dest
    except FileExistsError:
        return None
    except PermissionError:
        raise


def backup_file(src: Path, dst_dir: Path) -> bool:
    if not src.is_file():
        log.warning("Skipping %s (file not found)", src.name)
        return False
    try:
        shutil.copy2(src, dst_dir / src.name)
        log.info("  + %s", src.name)
        return True
    except (OSError, PermissionError) as e:
        log.warning("Failed to copy %s: %s", src.name, e)
        return False


def rotate_backups(backup_root: Path, keep: int = KEEP) -> int:
    if not backup_root.exists():
        return 0
    dirs = sorted(
        [d for d in backup_root.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )
    to_delete = dirs[:-keep] if len(dirs) > keep else []
    deleted = 0
    for d in to_delete:
        try:
            shutil.rmtree(d)
            log.info("  - rotated: %s", d.name)
            deleted += 1
        except (OSError, PermissionError) as e:
            log.error("Failed to rotate %s: %s", d.name, e)
    return deleted


def main() -> int:
    root = find_project_root()
    source_map = build_source_map(root)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_root = root / ".claude" / "backups" / "state"

    try:
        dst = create_backup_dir(backup_root, timestamp)
    except PermissionError:
        log.error("No write permission for %s", backup_root)
        return 1

    if dst is None:
        log.info("Backup already exists for this minute, skipping.")
        return 0

    copied = 0
    for label in [".env", "settings.json", "HISTORY.md"]:
        if backup_file(source_map[label], dst):
            copied += 1

    mem_files = source_map["memory_files"]
    if mem_files:
        for mf in mem_files:
            if backup_file(mf, dst):
                copied += 1
    else:
        log.warning("No memory files found to back up.")

    if copied == 0:
        log.warning("No files backed up — all sources missing.")

    rotate_backups(backup_root, keep=KEEP)
    log.info("Backup complete: %d files -> %s", copied, dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
