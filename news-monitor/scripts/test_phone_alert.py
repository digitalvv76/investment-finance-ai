#!/usr/bin/env python3
"""Phone alert signal test - dry-run + optional live Telegram push.

Usage:
    python scripts/test_phone_alert.py          # dry-run only
    python scripts/test_phone_alert.py --live   # send actual Telegram test
"""

import os
import sys
import io
from pathlib import Path

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Load .env from project root
env_file = Path(__file__).resolve().parents[2] / ".env"
if env_file.exists():
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.alert_dispatcher import AlertDispatcher, AlertLevel
from engine.strategic_detector import StrategicDetector
from engine.priority import PriorityScorer
from storage.models import NewsItem


# Test items: (title, tickers, macro_tags, expected_level)
TEST_ITEMS = [
    (
        "BREAKING: Fed emergency 75bp rate hike to fight inflation",
        "SPY,QQQ,IWM",
        "monetary_policy,federal_reserve",
        AlertLevel.CRITICAL,
    ),
    (
        "US govt injects $8.5B into Intel via CHIPS Act for new fabs",
        "INTC,NVDA,AMD",
        "gov_policy,chips_act,semiconductor",
        AlertLevel.CRITICAL,
    ),
    (
        "NVIDIA beats earnings, Q2 revenue +122% YoY, data center doubles",
        "NVDA",
        "earnings,earnings_beat",
        AlertLevel.IMPORTANT,
    ),
    (
        "Apple announces quarterly dividend $0.25/share",
        "AAPL",
        "dividends",
        AlertLevel.NORMAL,
    ),
    (
        "Analyst commentary: tech sector outlook remains positive",
        "",
        "market_commentary",
        AlertLevel.NORMAL,
    ),
]


def sep(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def main(live: bool = False):
    sep("PHONE ALERT SIGNAL TEST")

    # ---- Init -----------------------------------------------------------
    print("\n  Initializing modules...")
    dispatcher = AlertDispatcher()
    strategic = StrategicDetector()
    scorer = PriorityScorer()
    print("  [OK] AlertDispatcher")
    print("  [OK] StrategicDetector")
    print("  [OK] PriorityScorer")

    # ---- Channel status -------------------------------------------------
    sep("CHANNEL STATUS")

    pushover_ok = dispatcher.pushover_available
    telegram_ok = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
    mask = os.environ.get("TELEGRAM_BOT_TOKEN", "")[:15] + "..." if telegram_ok else "N/A"

    print(f"  Pushover:  {'[CONFIGURED]' if pushover_ok else '[MISSING] ($5 one-time at pushover.net)'}")
    print(f"  Telegram:  {'[CONFIGURED] ' + mask if telegram_ok else '[MISSING] (need TELEGRAM_BOT_TOKEN)'}")

    if not pushover_ok and not telegram_ok:
        print("\n  [WARN] No channels available - dry-run only")

    # ---- Classification -------------------------------------------------
    sep("CLASSIFICATION TEST (5 simulated headlines)")

    from engine.alert_dispatcher import CRITICAL_PRIORITY, IMPORTANT_PRIORITY, STRATEGIC_CRITICAL_CONF
    print(f"  Thresholds: CRITICAL>={CRITICAL_PRIORITY}, IMPORTANT>={IMPORTANT_PRIORITY}, STRAT_CONF>={STRATEGIC_CRITICAL_CONF}")

    results = []
    for i, (title, tickers, macro, expected) in enumerate(TEST_ITEMS):
        print(f"\n--- Item {i+1}: {title[:65]}")

        # 1. Strategic detection
        matches = strategic.detect(title)
        for m in matches:
            print(f"    [STRAT] {m.category} conf={m.confidence:.2f} - {m.text[:60]}")

        # 2. Priority scoring
        news_item = NewsItem(
            title=title, url="https://example.com/test", source="TEST",
            tickers_found=tickers, macro_tags=macro,
        )
        ticker_set = set(tickers.split(",")) if tickers else set()
        macro_set = set(macro.split(",")) if macro else set()
        score = scorer.score(news_item, tickers=ticker_set, macro_tags=macro_set)
        print(f"    [SCORE] {score:.2f}")

        # 3. Classify
        level, reason = dispatcher.classify(score, matches)

        # 4. Predicted channels
        channels = []
        if level == AlertLevel.CRITICAL:
            if pushover_ok:
                channels.append("pushover_emergency (siren, repeats 60s)")
            if telegram_ok:
                channels.append("telegram_triple (3x 500ms apart)")
            if not pushover_ok and not telegram_ok:
                channels.append("(dry-run) pushover_emergency + telegram_triple")
        elif level == AlertLevel.IMPORTANT:
            if pushover_ok:
                channels.append("pushover_high (persistent)")
            if telegram_ok:
                channels.append("telegram_alert (sound+vibrate)")
            if not pushover_ok and not telegram_ok:
                channels.append("(dry-run) pushover_high + telegram_alert")
        else:
            if telegram_ok:
                channels.append("telegram_silent (no notification)")
            else:
                channels.append("(dry-run) telegram_silent")

        label = {AlertLevel.CRITICAL: "[CRIT]", AlertLevel.IMPORTANT: "[IMPT]",
                 AlertLevel.NORMAL: "[NORM]"}[level]
        print(f"    {label} reason={reason}")
        print(f"    Channels: {', '.join(channels)}")

        results.append((title, level, expected, channels))

    # ---- Summary --------------------------------------------------------
    sep("SUMMARY")

    passed = sum(1 for _, actual, expected, _ in results if actual == expected)
    for title, actual, expected, channels in results:
        status = "PASS" if actual == expected else "MISMATCH"
        ch = channels[0] if channels else "none"
        print(f"  [{status}] {actual.value:10s} | {ch[:35]:35s} | {title[:50]}")

    print(f"\n  Accuracy: {passed}/{len(results)}")

    # ---- Live push test ------------------------------------------------
    if live and telegram_ok:
        sep("LIVE PUSH TEST")
        print("  Sending test message to Telegram...")
        print("  [WARN] Requires bot running + user has sent /start to register chat_id")
    elif live and not telegram_ok:
        sep("LIVE PUSH TEST")
        print("  [SKIP] Telegram not configured")

    sep("TEST COMPLETE")
    print(f"\n  To activate Pushover: https://pushover.net (one-time $5)")
    print(f"  To activate Telegram: set TELEGRAM_BOT_TOKEN in .env")
    print(f"  Full push needs: bot running + user /start\n")


if __name__ == "__main__":
    live = "--live" in sys.argv
    main(live=live)
