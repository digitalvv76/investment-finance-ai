"""Quick smoke-test for new Twitter + Chinese news fetchers.

Usage:
    cd news-monitor && python scripts/test_new_fetchers.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure package is importable
_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from collector.twitter_fetcher import TwitterFetcher
from collector.chinese_fetcher import ChineseNewsFetcher


async def test_chinese():
    """Test Chinese news fetcher with default channels."""
    print("=" * 60)
    print("TEST: Chinese News Fetcher (新浪财经 + 华尔街见闻)")
    print("=" * 60)

    config = {
        "max_items_per_source": 5,
        "request_delay_seconds": 1.0,
        "sina_channels": [
            {"name": "综合快讯", "lid": 2509, "category": "macro"},
            {"name": "全球财经", "lid": 2510, "category": "global"},
        ],
        "wallstreetcn_channels": [
            {"channel": "global", "name": "全球快讯"},
            {"channel": "us-stock", "name": "美股"},
        ],
    }

    fetcher = ChineseNewsFetcher(config)
    try:
        items = await fetcher.fetch_all()
        print(f"\nTotal items: {len(items)}\n")
        for i, item in enumerate(items[:10]):
            print(f"{i+1}. [{item.source}] {item.title[:80]}")
            if item.content_snippet:
                print(f"   {item.content_snippet[:100]}")
        print(f"\n... ({len(items)} total)")
    finally:
        await fetcher.close()


async def test_twitter():
    """Test Twitter fetcher (will only work if Nitter is reachable)."""
    print("\n" + "=" * 60)
    print("TEST: Twitter Fetcher (via Nitter RSS proxy)")
    print("=" * 60)

    config = {
        "nitter_base_url": "https://nitter.net",
        "max_items_per_account": 3,
        "request_delay_seconds": 2.0,
        "accounts": ["@elerianm", "@Newsquawk"],
    }

    fetcher = TwitterFetcher(config)
    try:
        # First check instance availability
        instance = await fetcher._find_working_instance()
        if not instance:
            print("\n[WARN] No working Nitter instance found.")
            print("   Twitter feeds are unreachable from this network.")
            print("   To enable: self-host Nitter on a VPS or use VPN.")
            return

        items = await fetcher.fetch_all()
        print(f"\nTotal items: {len(items)}\n")
        for i, item in enumerate(items[:6]):
            print(f"{i+1}. [{item.source}] {item.title[:80]}")
    finally:
        await fetcher.close()


async def main():
    await test_chinese()
    await test_twitter()

    print("\n" + "=" * 60)
    print("DONE. Chinese sources should return news items.")
    print("Twitter sources depend on Nitter instance availability.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
