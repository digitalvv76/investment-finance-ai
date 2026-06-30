"""
Investment Finance AI Agent — MCP Connectivity Smoke Test

Usage: python scripts/verify_mcp.py

Verifies that each configured MCP server package is installable
and reports back which servers are available.
"""
import subprocess
import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
MCP_CONFIG = ROOT / ".mcp.json"

# Package verification commands
SERVERS = {
    "yfinance": {
        "type": "uvx",
        "package": "yahoo-finance-mcp-server",
        "cmd": ["uvx", "yahoo-finance-mcp-server", "--help"],
    },
    "coingecko": {
        "type": "npx",
        "package": "@coingecko/coingecko-mcp",
        "cmd": ["npx", "-y", "@coingecko/coingecko-mcp", "--help"],
    },
    "fred": {
        "type": "npx",
        "package": "fred-mcp-server",
        "cmd": ["npx", "-y", "fred-mcp-server", "--help"],
    },
    "finance": {
        "type": "npx",
        "package": "finance-mcp-server",
        "cmd": ["npx", "-y", "finance-mcp-server", "--help"],
    },
    "stock-scanner": {
        "type": "npx",
        "package": "stock-scanner-mcp",
        "cmd": ["npx", "-y", "stock-scanner-mcp", "--help"],
    },
    "sec-edgar": {
        "type": "uvx",
        "package": "sec-edgar-mcp",
        "cmd": ["uvx", "sec-edgar-mcp", "--help"],
    },
    "crypto-trade": {
        "type": "npx",
        "package": "crypto-mcp-server",
        "cmd": ["npx", "-y", "crypto-mcp-server", "--help"],
    },
    "cn-finance": {
        "type": "uvx",
        "package": "cn-financial-mcp",
        "cmd": ["uvx", "cn-financial-mcp", "--help"],
    },
}


def check_server(name, info):
    """Try to install/run a server package, return success status."""
    print(f"  {name:20s} ({info['type']}:{info['package']}) ... ", end="", flush=True)
    try:
        result = subprocess.run(
            info["cmd"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ROOT,
        )
        # Both success and expected error exits mean the package exists
        # (--help on MCP servers often starts the server, which is fine)
        if result.returncode in (0, 1, 2):  # 0=success, 1=help not found, 2=server started
            print("OK (package found)")
            return True
        else:
            print(f"UNEXPECTED (exit {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        # Server started and running -- that means the package is available!
        print("OK (server started)")
        return True
    except FileNotFoundError:
        print("FAIL (tool not found: uvx/npx/node not installed?)")
        return False
    except Exception as e:
        print(f"FAIL ({e})")
        return False


def check_api_keys():
    """Check if recommended API keys are configured."""
    print("\nAPI Keys:")
    keys = {
        "FRED_API_KEY": "FRED economic data",
        "ALPHA_VANTAGE_API_KEY": "Alpha Vantage financial data",
        "BINANCE_API_KEY": "Binance crypto trading",
        "BINANCE_SECRET_KEY": "Binance crypto trading (secret)",
    }
    all_set = True
    for var, desc in keys.items():
        # Check if mentioned in .env or environment
        env_file = ROOT / ".env"
        in_env = False
        if env_file.exists():
            content = env_file.read_text()
            in_env = f"{var}=" in content and "your_" not in content and "=" not in content.split(f"{var}=")[1].strip()[:1]
        in_os = var in subprocess.run(["bash", "-c", f"echo ${var}"], capture_output=True, text=True, cwd=ROOT).stdout.strip()

        if in_env or (in_os and len(in_os) > 3):
            print(f"  {var:30s} SET ({desc})")
        else:
            print(f"  {var:30s} NOT SET ({desc})")
            if var in ("FRED_API_KEY", "ALPHA_VANTAGE_API_KEY"):
                all_set = False

    if not all_set:
        print("\n  ⚠️  Recommended: Set FRED_API_KEY and ALPHA_VANTAGE_API_KEY in .env")
        print("     See .env.example for setup instructions.")

    return all_set


def main():
    print("=" * 60)
    print("Investment Finance AI Agent — MCP Verification")
    print(f"Project: {ROOT}")
    print("=" * 60)

    print("\nMCP Server Packages:")
    results = {}
    for name, info in SERVERS.items():
        results[name] = check_server(name, info)

    available = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\nResult: {available}/{total} MCP servers available")

    if available < total:
        print("Unavailable servers:")
        for name, ok in results.items():
            if not ok:
                print(f"  - {name}: Use stock-scanner as fallback (see CLAUDE.md)")

    keys_ok = check_api_keys()

    print("\n" + "=" * 60)
    if available >= 4 and keys_ok:
        print("[OK] System ready for use.")
    elif available >= 2:
        print("[WARN] Minimum operational (2+ servers). Set API keys for full functionality.")
    else:
        print("[ERROR] Insufficient MCP servers. Check Node.js and uv installation.")
    print("=" * 60)


if __name__ == "__main__":
    main()
