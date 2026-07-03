"""Score all 51 historical events and show push/no-push decision."""

import sys
from pathlib import Path
_pkg = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_pkg))

from scripts.backtest_signal import parse_events, backtest

IMPACT_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# Push thresholds (from settings.yaml impact_push)
CRITICAL_THRESHOLD = 0.50  # composite >= 0.50 → CRITICAL push
IMPORTANT_THRESHOLD = 0.35  # composite >= 0.35 → IMPORTANT push

def push_level(composite: float) -> str:
    if composite >= CRITICAL_THRESHOLD:
        return "CRITICAL"
    elif composite >= IMPORTANT_THRESHOLD:
        return "IMPORTANT"
    else:
        return "SILENT"

events = parse_events()
results = backtest(events)

# Sort by human impact level, then by composite within each level
results.sort(key=lambda r: (r["impact_num"], r["composite"]), reverse=True)

print(f"{'#':>3} {'Label':>8} {'comp':>6} {'push':>9} {'t':>4} {'n':>4} {'rel':>4} {'dir':>12}  Description")
print("-" * 130)

for r in results:
    push = push_level(r["composite"])
    marker = "!!!" if push == "CRITICAL" else ("!" if push == "IMPORTANT" else "  ")
    print(f"{r['id']:3d} {r['impact']:>8} {r['composite']:6.3f} {push:>9} {marker} "
          f"{r['timeliness']:4.2f} {r['novelty']:4.2f} {r['relevance']:4.2f} "
          f"{r['direction']:>12s}  {r['description'][:85]}")

# Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

for lv in IMPACT_ORDER:
    lv_results = [r for r in results if r["impact"] == lv]
    pushed = [r for r in lv_results if push_level(r["composite"]) != "SILENT"]
    critical = [r for r in lv_results if push_level(r["composite"]) == "CRITICAL"]
    if lv_results:
        avg = sum(r["composite"] for r in lv_results) / len(lv_results)
        print(f"  {lv:10s}: {len(lv_results):2d} events, avg={avg:.3f}, "
              f"{len(pushed)} pushed ({len(critical)} CRITICAL)")

total = len(results)
pushed_total = len([r for r in results if push_level(r["composite"]) != "SILENT"])
crit_total = len([r for r in results if push_level(r["composite"]) == "CRITICAL"])
print(f"\n  Total: {total} events, {pushed_total} pushed, {crit_total} CRITICAL")
print(f"  Push rate: {pushed_total}/{total} = {pushed_total/total*100:.0f}%")
