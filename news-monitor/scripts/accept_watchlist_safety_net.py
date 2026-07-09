#!/usr/bin/env python
"""End-to-end acceptance for the watchlist/portfolio safety net.

Runs the REAL EventDrivenEvaluator (real LLM, no mocks) against the exact
regression headlines from prod, then applies the real decision gate
(watchlist_safety_net + get_tracked_tickers) and checks each outcome.

Positive: a substantive action on a tracked name (is_event=false) must fire
the silent-TG safety net. Negative: noise that previously mis-tagged (El Nino
-> "ARM", Teva -> "ARM") and off-watchlist names must NOT fire.

Usage:  python scripts/accept_watchlist_safety_net.py
Requires DEEPSEEK_API_KEY (or ANTHROPIC_API_KEY) in .env.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root)
sys.path.insert(0, root)
# Load .env from repo root (two levels up from news-monitor/)
load_dotenv(os.path.join(os.path.dirname(root), ".env"))
load_dotenv(os.path.join(root, ".env"))

from storage.models import NewsItem
from engine.event_driven_evaluator import EventDrivenEvaluator, watchlist_safety_net
from engine.relevance import get_tracked_tickers

# (title, content_snippet, expect_safety_net_fires)
CASES = [
    ("Tesla Stock Gets Stunning Price Target Hike From UBS on AI Bull Case",
     "UBS raised its Tesla price target sharply, citing the AI and robotaxi opportunity.", True),
    ("MU, AMD, MRVL, QCOM Stocks Surge — Bernstein's Stacy Rasgon Turns Bullish on Memory",
     "Marvell (MRVL) and peers rallied after a notable analyst upgrade on the AI memory cycle.", True),
    ("Strongest El Nino In 75 Years Sets Off Food Supply-Chain Alarm",
     "Meteorologists warn the El Nino pattern could disrupt global food supply chains.", False),
    ("Teva Pharmaceutical Industries Limited (TEVA) Discusses Anti-Inflammatory Pipeline",
     "Teva presented clinical-stage data on its anti-inflammatory drug pipeline.", False),
    ("Kylian Mbappe scores his 20th career World Cup goal",
     "The striker reached a milestone in international football.", False),
]


async def main():
    tracked = get_tracked_tickers()
    print(f"Tracked tickers ({len(tracked)}): {sorted(tracked)}\n")
    ev = EventDrivenEvaluator()
    if not ev._available_providers():
        print("FAIL: no LLM provider (DEEPSEEK_API_KEY/ANTHROPIC_API_KEY missing)")
        return 1

    fails = 0
    for title, snippet, expect in CASES:
        item = NewsItem(title=title, content_snippet=snippet, url="http://x", source="acceptance")
        ea = await ev.evaluate(item)
        fired = watchlist_safety_net(ea, tracked)
        ok = (fired == expect)
        fails += (not ok)
        print(f"[{'PASS' if ok else 'FAIL'}] fire={fired} expect={expect} "
              f"is_event={ea.is_event} notable={ea.notable} tickers={ea.ticker_hint}")
        print(f"        {title[:70]}")
        print(f"        reason={ea.filter_reason[:80]}\n")

    print("=" * 56)
    print(f"{'ALL PASS' if fails == 0 else f'{fails} FAILED'} ({len(CASES) - fails}/{len(CASES)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
