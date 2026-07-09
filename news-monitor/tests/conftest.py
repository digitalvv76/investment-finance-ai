"""Shared pytest fixtures and configuration."""
import os
import sys
from pathlib import Path

# Ensure project root (news-monitor/) is in path for test discovery from any CWD
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Force UTF-8 on Windows
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
