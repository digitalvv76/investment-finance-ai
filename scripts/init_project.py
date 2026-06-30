"""
Investment Finance AI Agent — One-shot Project Initialization

Usage: python scripts/init_project.py

Creates all data directories and template files if they don't exist.
Safe to run multiple times — will not overwrite existing data.
"""
import os
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ── Directory structure ──────────────────────────────────────────
DIRS = [
    "data/watchlists",
    "data/portfolios",
    "data/signals",
    "data/briefings",
    "data/reports",
    "data/cache",
    "data/theses",
    "config",
    "scripts",
    ".claude/memory",
    ".claude/logs",
]


def ensure_dirs():
    """Create missing directories."""
    print("Creating directories...")
    for d in DIRS:
        p = ROOT / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            print(f"  + {d}/")
        else:
            print(f"  · {d}/ (exists)")


# ── Template files ───────────────────────────────────────────────
TEMPLATES = {
    "data/watchlists/default.json": {
        "name": "default",
        "created": NOW,
        "updated": NOW,
        "tickers": {
            "US": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"],
            "CN": ["600519", "000858", "300750", "601318"],
            "HK": ["0700", "9988", "3690"],
            "crypto": ["BTC", "ETH", "SOL"],
        },
        "indices": [
            "^GSPC", "^IXIC", "^DJI",
            "000001.SS", "399001.SZ", "000300.SS",
            "^HSI", "^HSTECH",
        ],
    },
    "data/portfolios/current.json": {
        "date": TODAY,
        "currency": "USD",
        "holdings": [],
        "cash": {"USD": 50000.00, "CNY": 0, "HKD": 0},
        "targetAllocation": {
            "US_equities": 50, "CN_equities": 20,
            "HK_equities": 10, "crypto": 10, "cash": 10,
        },
        "constraints": {
            "max_per_stock_pct": 5, "max_per_etf_crypto_major_pct": 10,
            "max_sector_concentration_pct": 30, "min_cash_reserve_pct": 5,
            "crypto_max_pct": 10,
        },
    },
    "data/signals/active.json": {
        "generated": NOW, "active": [], "closed": [],
    },
    "data/signals/history.jsonl": "",
    "data/reports/ARCHIVE.md": (
        "# 📁 研究报告归档索引\n\n"
        "| 日期 | 代码 | 市场 | 评级 | 目标价 | 核心逻辑 |\n"
        "|------|------|------|------|--------|----------|\n"
        "| — | — | — | — | — | 待首次研究 |\n"
    ),
}


def write_template(path, content):
    """Write a template file if it doesn't exist yet."""
    p = ROOT / path
    if p.exists():
        print(f"  · {path} (exists, skipping)")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        p.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        p.write_text(content, encoding="utf-8")
    print(f"  + {path}")


def ensure_templates():
    """Create missing template files."""
    print("\nCreating template files...")
    for path, content in TEMPLATES.items():
        write_template(path, content)


def main():
    print("=" * 60)
    print("Investment Finance AI Agent — Project Initialization")
    print(f"Root: {ROOT}")
    print("=" * 60)

    ensure_dirs()
    ensure_templates()

    print("\n" + "=" * 60)
    print("[OK] Project initialized successfully.")
    print("   Next steps:")
    print("   1. Copy .env.example to .env and add your API keys")
    print("   2. Edit data/watchlists/default.json with your tickers")
    print("   3. Edit data/portfolios/current.json with your holdings")
    print("   4. Run: python scripts/verify_mcp.py")
    print("   5. Start using skills: /daily-briefing, /stock-research, etc.")
    print("=" * 60)


if __name__ == "__main__":
    main()
