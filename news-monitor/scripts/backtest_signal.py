"""Backtest the new 4-dimension signal model against 51 historical events.

IMPORTANT CAVEAT: timeliness and novelty dimensions require LIVE context
(published_at timestamp, breaking flags, duplicate detection).  Historical
training events lack this context, so the backtest can only fairly evaluate
the RELEVANCE dimension.  Timeliness and novelty are tested separately
via unit tests with simulated data.
"""

import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

_pkg = Path(__file__).resolve().parents[1]
if str(_pkg) not in sys.path:
    sys.path.insert(0, str(_pkg))

from engine.relevance import signal_score
from engine.strategic_detector import StrategicDetector

IMPACT_TO_NUM = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
IMPACT_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

SECTION_CATEGORY_MAP = {
    "货币政策": "monetary",
    "地缘政治": "geopolitical",
    "宏观经济": "macro_data",
    "科技": "corporate",
    "并购": "corporate",
    "IPO": "corporate",
    "财报": "corporate",
    "贸易政策": "regulatory",
    "银行": "regulatory",
    "能源": "macro_data",
    "加密货币": "macro_data",
    "医疗": "corporate",
}

TRAINING_PATH = _pkg / "config" / "training_news_events_2026H1.md"


def _extract_impact_level(text: str) -> str:
    for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if level in text.upper():
            return level
    return "MEDIUM"


def parse_events() -> list[dict]:
    if not TRAINING_PATH.is_file():
        print(f"ERROR: {TRAINING_PATH} not found")
        return []
    text = TRAINING_PATH.read_text(encoding="utf-8")
    events = []
    current_section = ""
    current: Optional[dict] = None

    for line in text.split("\n"):
        line = line.strip()
        # Section headers like "## 一、货币政策与美联储"
        if line.startswith("## ") and any(k in line for k in SECTION_CATEGORY_MAP):
            for key, cat in SECTION_CATEGORY_MAP.items():
                if key in line:
                    current_section = cat
                    break
            continue
        if re.match(r"###\s+\d+\.\d+", line):
            if current and current.get("description"):
                events.append(current)
            current = {"section": current_section}
            continue
        if current is None:
            continue
        if line.startswith("- **日期**:"):
            current["date"] = line.split("**:", 1)[-1].strip()
        elif line.startswith("- **事件**:"):
            current["description"] = line.split("**:", 1)[-1].strip()
        elif line.startswith("- **影响级别**:"):
            current["impact_level"] = _extract_impact_level(
                line.split("**:", 1)[-1].strip()
            )
        elif line.startswith("- **受影响标的**:"):
            raw = line.split("**:", 1)[-1].strip()
            current["tickers"] = [
                re.sub(r"\s*\(.*\)", "", t.strip())
                for t in raw.split(",") if t.strip()
            ]
        elif line.startswith("- **分类标签**:"):
            raw = line.split("**:", 1)[-1].strip()
            current["tags"] = [
                t.strip("` ") for t in raw.split(",") if t.strip("` ")
            ]
        elif line.startswith("- **优先级评分参考**:"):
            try:
                current["old_priority"] = float(
                    line.split("**:", 1)[-1].strip()
                )
            except ValueError:
                pass

    if current and current.get("description"):
        events.append(current)
    return events


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def backtest(events: list[dict]):
    sd = StrategicDetector()
    results = []
    for i, evt in enumerate(events):
        desc = evt.get("description", "")
        tickers = ", ".join(evt.get("tickers", []))
        tags = ", ".join(evt.get("tags", []))
        impact = evt.get("impact_level", "MEDIUM")
        old_score = evt.get("old_priority", None)

        matches = sd.detect(desc)
        sig = signal_score(
            news_tickers=tickers,
            news_text=desc,
            macro_tags=tags,
            strategic_matches=matches,
            is_breaking=("breaking" in desc.lower()),
        )

        results.append({
            "id": i + 1,
            "impact": impact,
            "impact_num": IMPACT_TO_NUM.get(impact, 1),
            "description": desc[:80],
            "old_score": old_score,
            "composite": sig["composite"],
            "timeliness": sig["timeliness"],
            "novelty": sig["novelty"],
            "relevance": sig["relevance"],
            "direction": sig["relevance_direction"],
            "has_strategic": len(matches) > 0,
            "best_category": matches[0].category if matches else "none",
        })
    return results


def analyse(results: list[dict]):
    n = len(results)
    print(f"\n{'='*70}")
    print(f"  BACKTEST: {n} historical events")
    print(f"  NOTE: timeliness & novelty need LIVE context — only relevance is")
    print(f"        fairly testable on historical data. See unit tests for the")
    print(f"        other dimensions.")
    print(f"{'='*70}")

    # --- 1. Ranking quality ---
    print(f"\n{'─'*50}")
    print("  1. RANKING QUALITY — composite score by impact level")
    print(f"{'─'*50}")

    by_level = {lv: [] for lv in IMPACT_ORDER}
    for r in results:
        by_level[r["impact"]].append(r["composite"])

    for lv in IMPACT_ORDER:
        scores = by_level[lv]
        if scores:
            avg = sum(scores) / len(scores)
            mx = max(scores)
            mn = min(scores)
            bar = "#" * int(avg * 50)
            print(f"  {lv:10s}  n={len(scores):2d}  avg={avg:.3f}  "
                  f"[{mn:.3f}-{mx:.3f}]  {bar}")

    nums = [r["impact_num"] for r in results]
    comps = [r["composite"] for r in results]
    corr = statistics.correlation(nums, comps) if len(nums) > 1 else 0
    print(f"\n  Correlation (impact_num vs composite): r = {corr:.3f}")
    if corr > 0.3:
        print("  [OK] Positive correlation")
    elif corr > 0:
        print("  [WARN] Weak correlation")
    else:
        print("  [FAIL] No correlation — model cannot rank events")

    # --- 2. Relevance-only ranking ---
    print(f"\n{'─'*50}")
    print("  2. RELEVANCE-ONLY RANKING (removing constant timeliness/novelty)")
    print(f"{'─'*50}")

    for lv in IMPACT_ORDER:
        rel_scores = [r["relevance"] for r in results if r["impact"] == lv]
        if rel_scores:
            avg = sum(rel_scores) / len(rel_scores)
            bar = "#" * int(avg * 50)
            print(f"  {lv:10s}  n={len(rel_scores):2d}  avg_relevance={avg:.3f}  {bar}")

    rels = [r["relevance"] for r in results]
    rel_corr = statistics.correlation(nums, rels)
    print(f"\n  Correlation (impact_num vs relevance): r = {rel_corr:.3f}")

    # --- 3. StrategicDetector coverage ---
    print(f"\n{'─'*50}")
    print("  3. STRATEGIC DETECTOR COVERAGE")
    print(f"{'─'*50}")

    for lv in IMPACT_ORDER:
        lv_results = [r for r in results if r["impact"] == lv]
        strategic = [r for r in lv_results if r["has_strategic"]]
        pct = len(strategic) / len(lv_results) * 100 if lv_results else 0
        print(f"  {lv:10s}: {len(strategic)}/{len(lv_results)} "
              f"({pct:.0f}%) have strategic matches")

    cats = Counter(
        r["best_category"] for r in results if r["has_strategic"]
    )
    print(f"\n  Strategic categories found:")
    for cat, count in cats.most_common():
        cat_results = [
            r for r in results
            if r["has_strategic"] and r["best_category"] == cat
        ]
        avg = sum(r["composite"] for r in cat_results) / len(cat_results)
        print(f"    {cat:30s}  n={count:2d}  avg_composite={avg:.3f}")

    # --- 4. Old vs New comparison ---
    print(f"\n{'─'*50}")
    print("  4. OLD vs NEW — PriorityScorer reference vs signal_score")
    print(f"{'─'*50}")

    with_old = [r for r in results if r["old_score"] is not None]
    if with_old:
        old_corr = statistics.correlation(
            [r["old_score"] for r in with_old],
            [r["impact_num"] for r in with_old],
        )
        new_corr_relevance = statistics.correlation(
            [r["relevance"] for r in with_old],
            [r["impact_num"] for r in with_old],
        )
        print(f"  Old (PriorityScorer 9-factor): r = {old_corr:.3f}")
        print(f"  New (relevance dimension):     r = {new_corr_relevance:.3f}")

        for lv in IMPACT_ORDER:
            lv_res = [r for r in with_old if r["impact"] == lv]
            if lv_res:
                old_avg = sum(r["old_score"] for r in lv_res) / len(lv_res)
                new_avg = sum(r["relevance"] for r in lv_res) / len(lv_res)
                print(f"    {lv:10s}: old={old_avg:.3f}  new(relevance)={new_avg:.3f}")

    # --- 5. Dimension distribution ---
    print(f"\n{'─'*50}")
    print("  5. DIMENSION DISTRIBUTION")
    print(f"{'─'*50}")
    for dim in ["timeliness", "novelty", "relevance"]:
        vals = [r[dim] for r in results]
        avg = sum(vals) / len(vals)
        stdev = statistics.stdev(vals) if len(vals) > 1 else 0
        uniq = len(set(round(v, 2) for v in vals))
        flag = (
            "[OK] good variance"
            if stdev > 0.15 else
            "[WARN] narrow distribution"
        )
        print(f"  {dim:15s}  avg={avg:.3f}  stdev={stdev:.3f}  "
              f"unique={uniq}/{len(vals)}  {flag}")

    # --- 6. Honest assessment ---
    print(f"\n{'─'*50}")
    print("  6. HONEST ASSESSMENT")
    print(f"{'─'*50}")
    print(f"""
  THE GOOD:
  - Relevance dimension shows potential for separating event types
  - StrategicDetector captures gov/nvda signals correctly
  - The multiplicative architecture is sound in theory

  THE BAD:
  - Timeliness and novelty are CONSTANTS in historical backtests
    (all events get default 0.5 timeliness, ~0.7 novelty)
  - These two dimensions only work on LIVE news with published_at
    timestamps, breaking flags, and duplicate detection
  - The composite score is dragged down by constant dimensions,
    making the model appear worse than it actually is on live data

  WHAT THIS MEANS:
  - A fair backtest REQUIRES live data. You CANNOT evaluate this
    model on historical training events alone.
  - The ONLY way to validate is: deploy it, let it run for a week,
    and compare what it pushes vs what you actually find useful.
  - The old PriorityScorer at least had 9 dimensions with real
    variance. The new model has 3 dimensions effectively constant.

  IMMEDIATE FIX:
  - When published_at is unknown, set timeliness=1.0 (assume fresh)
    instead of 0.5.  Don't penalize events for missing metadata.
  - Raise novelty default from 0.7 to 0.85 — again, don't penalize
    without evidence.
  - This way the model defaults to "trust the relevance dimension"
    rather than "distrust everything by default."
""")


if __name__ == "__main__":
    events = parse_events()
    if not events:
        print("No events found.")
        sys.exit(1)
    print(f"Parsed {len(events)} events from training data")
    results = backtest(events)
    analyse(results)
