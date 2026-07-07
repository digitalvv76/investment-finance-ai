#!/usr/bin/env python
"""Threshold calibration — grid-search optimal push-decision thresholds.

Uses historical feedback (thumbs_up/down/ignore) and impact outcomes as
ground-truth labels, then searches for the threshold combination that
maximises F1 score.

Usage:
    python scripts/calibrate_thresholds.py          # grid search
    python scripts/calibrate_thresholds.py --apply   # apply best thresholds
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Add news-monitor to path so imports work from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.database import Database

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ground truth construction
# ---------------------------------------------------------------------------


def build_labels(db: Database) -> list[dict]:
    """Build labelled dataset from feedback and impact outcomes.

    Each entry: {priority_score, impact_score, should_push: bool, source: str}
    """
    labelled = []

    # Source 1: explicit user feedback
    with db._get_conn() as conn:
        rows = conn.execute("""
            SELECT n.priority_score, f.reaction, f.timestamp
            FROM feedback f
            JOIN news n ON n.id = f.news_id
            WHERE n.priority_score IS NOT NULL
            ORDER BY f.timestamp DESC
            LIMIT 500
        """).fetchall()

    for row in rows:
        reaction = row["reaction"] or ""
        if reaction in ("thumbs_up",):
            labelled.append({
                "priority_score": row["priority_score"],
                "should_push": True,
                "source": "feedback_thumbs_up",
            })
        elif reaction in ("thumbs_down", "ignore"):
            labelled.append({
                "priority_score": row["priority_score"],
                "should_push": False,
                "source": "feedback_thumbs_down",
            })

    # Source 2: impact outcomes (actual market movement)
    with db._get_conn() as conn:
        rows = conn.execute("""
            SELECT n.priority_score, a.impact_score,
                   MAX(o.actual_score) as actual_score
            FROM impact_outcomes o
            JOIN impact_assessments a ON a.id = o.assessment_id
            JOIN news n ON n.id = a.news_id
            WHERE n.priority_score IS NOT NULL
              AND o.actual_score >= 0
            GROUP BY a.id
            ORDER BY o.collected_at DESC
            LIMIT 500
        """).fetchall()

    for row in rows:
        actual = row["actual_score"] or 0
        if actual >= 50:
            labelled.append({
                "priority_score": row["priority_score"],
                "should_push": True,
                "source": f"outcome_high_impact({actual:.0f})",
            })
        elif actual < 20:
            # Low actual impact + was pushed → false positive
            labelled.append({
                "priority_score": row["priority_score"],
                "should_push": False,
                "source": f"outcome_low_impact({actual:.0f})",
            })

    # Dedup: if same priority_score has conflicting labels, keep the
    # most recent (last in list = most recent since we sort DESC).
    # Actually, keep all — different items can have the same priority_score.
    # We just need a clean dataset.

    return labelled


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------


def simulate_decision(priority_score: float, thresholds: dict) -> bool:
    """Would the system push this item with the given thresholds?

    Replicates the alert_dispatcher.classify() logic (simplified).
    """
    crit = thresholds["critical"]
    imp = thresholds["important"]
    if priority_score >= crit:
        return True  # CRITICAL → push
    if priority_score >= imp:
        return True  # IMPORTANT → push
    return False     # NORMAL → archive


def evaluate(labels: list[dict], thresholds: dict) -> dict:
    """Compute precision, recall, F1 for a threshold combination."""
    tp = fp = tn = fn = 0

    for item in labels:
        predicted_push = simulate_decision(item["priority_score"], thresholds)
        actual_push = item["should_push"]

        if predicted_push and actual_push:
            tp += 1
        elif predicted_push and not actual_push:
            fp += 1
        elif not predicted_push and not actual_push:
            tn += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def grid_search(labels: list[dict]) -> list[dict]:
    """Search threshold space for best F1."""
    if len(labels) < 5:
        logger.warning("Too few labelled samples (%d) — results unreliable", len(labels))
        return []

    results = []

    # Search space
    for critical in [round(x, 2) for x in [v / 100 for v in range(55, 81, 5)]]:
        for important in [round(x, 2) for x in [v / 100 for v in range(35, min(61, int(critical * 100)), 5)]]:
            if important >= critical:
                continue

            thresholds = {"critical": critical, "important": important}
            metrics = evaluate(labels, thresholds)
            metrics["thresholds"] = thresholds
            results.append(metrics)

    # Sort by F1 descending
    results.sort(key=lambda r: (r["f1"], r["precision"]), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Calibrate push-decision thresholds")
    parser.add_argument("--apply", action="store_true",
                        help="Apply the best thresholds to alert_dispatcher.py")
    parser.add_argument("--top", type=int, default=10,
                        help="Number of top results to show (default: 10)")
    parser.add_argument("--bootstrap", action="store_true",
                        help="Bootstrap from score distribution when labels are sparse")
    args = parser.parse_args()

    db_path = Path(__file__).resolve().parents[1] / "data" / "news.db"
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    db = Database(str(db_path))
    labels = build_labels(db)

    if not labels:
        logger.warning("No labelled data found. Calibration needs user feedback or impact outcomes.")
        logger.info("Tip: use the Telegram feedback buttons (👍/👎) or wait for impact outcomes to accumulate.")
        return

    pos = sum(1 for l in labels if l["should_push"])
    neg = sum(1 for l in labels if not l["should_push"])
    logger.info("Labelled dataset: %d items (%d push, %d skip)", len(labels), pos, neg)

    # Current thresholds for comparison
    current = {"critical": 0.65, "important": 0.55}
    current_metrics = evaluate(labels, current)
    logger.info(
        "Current thresholds (crit=%.2f, imp=%.2f): precision=%.3f, recall=%.3f, F1=%.3f",
        current["critical"], current["important"],
        current_metrics["precision"], current_metrics["recall"], current_metrics["f1"],
    )

    results = grid_search(labels)

    # If too few labels, bootstrap from score distribution
    if (not results or len(results) < 5) and args.bootstrap:
        logger.info("Bootstrapping from score distribution...")
        boot_labels = bootstrap_labels(db, labels)
        pos = sum(1 for l in boot_labels if l["should_push"])
        neg = sum(1 for l in boot_labels if not l["should_push"])
        logger.info("Bootstrapped dataset: %d items (%d push, %d skip)", len(boot_labels), pos, neg)
        results = grid_search(boot_labels)

    if not results:
        _print_score_distribution(db)
        return

    print(f"\n{'Rank':<5} {'Critical':<10} {'Important':<10} {'Precision':<11} {'Recall':<9} {'F1':<8} {'TP':<5} {'FP':<5} {'TN':<5} {'FN':<5}")
    print("-" * 80)

    for i, r in enumerate(results[:args.top]):
        t = r["thresholds"]
        marker = " ← BEST" if i == 0 else ""
        print(
            f"{i+1:<5} {t['critical']:<10.2f} {t['important']:<10.2f} "
            f"{r['precision']:<11.3f} {r['recall']:<9.3f} {r['f1']:<8.3f} "
            f"{r['tp']:<5} {r['fp']:<5} {r['tn']:<5} {r['fn']:<5}"
            f"{marker}"
        )

    if args.apply and results:
        best = results[0]
        _apply_thresholds(best["thresholds"])


def bootstrap_labels(db: Database, existing_labels: list[dict]) -> list[dict]:
    """Augment sparse labels using score distribution heuristics.

    When we have too few human labels, we add synthetic ones from the
    PROCESSED items (non-zero scores that went through the full pipeline).
    Unprocessed (pending, score=0) items are excluded — they're noise.

    Heuristics:
      - Top 5% of processed scores    → should_push (these are the best candidates)
      - Bottom 20% of processed scores → should_skip (weak/no signal)
    """
    labels = list(existing_labels)

    with db._get_conn() as conn:
        rows = conn.execute("""
            SELECT priority_score FROM news
            WHERE priority_score IS NOT NULL
              AND priority_score > 0
              AND status != 'pending'
            ORDER BY id DESC LIMIT 1000
        """).fetchall()

    if not rows:
        logger.info("Bootstrap: no processed items with non-zero scores")
        return labels

    scores = sorted([r["priority_score"] for r in rows], reverse=True)

    # Top 5% → should_push, bottom 20% → should_skip
    top_idx = max(int(len(scores) * 0.05), 1)
    bot_idx = int(len(scores) * 0.80)

    added = 0
    for i, score in enumerate(scores):
        if i <= top_idx:
            labels.append({"priority_score": score, "should_push": True, "source": "bootstrap_top5pct"})
            added += 1
        elif i >= bot_idx:
            labels.append({"priority_score": score, "should_push": False, "source": "bootstrap_bottom20pct"})
            added += 1

    logger.info("Bootstrap: added %d synthetic labels from %d processed items", added, len(scores))
    return labels


def _print_score_distribution(db: Database):
    """Print the priority_score distribution to guide manual threshold selection."""
    with db._get_conn() as conn:
        rows = conn.execute("""
            SELECT priority_score FROM news
            WHERE priority_score IS NOT NULL
            ORDER BY id DESC LIMIT 2000
        """).fetchall()

    if not rows:
        print("No scored news items in database.")
        return

    scores = sorted([r["priority_score"] for r in rows], reverse=True)
    percentiles = [0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10]

    print(f"\nPriority score distribution ({len(scores)} items):")
    print(f"  Max:   {scores[0]:.2f}")
    print(f"  Min:   {scores[-1]:.2f}")
    print(f"  Mean:  {sum(scores)/len(scores):.2f}")
    print(f"\n  Percentile | Score")
    print(f"  -----------|-------")
    for p in percentiles:
        idx = int(len(scores) * p)
        if idx >= len(scores):
            idx = len(scores) - 1
        print(f"  P{p*100:3.0f}       | {scores[idx]:.2f}")

    # Suggest thresholds that would push ~10-15% of news as CRITICAL,
    # ~20-25% as IMPORTANT (common healthy ratios for push notifications).
    p10_idx = int(len(scores) * 0.10)
    p25_idx = int(len(scores) * 0.25)
    p10_score = scores[p10_idx] if p10_idx < len(scores) else scores[-1]
    p25_score = scores[p25_idx] if p25_idx < len(scores) else scores[-1]

    print(f"\n  Suggested (targeting ~10%% CRITICAL, ~25%% CRITICAL+IMPORTANT):")
    print(f"  CRITICAL_PRIORITY = {p10_score:.2f}")
    print(f"  IMPORTANT_PRIORITY = {p25_score:.2f}")
    print(f"\nRun with --bootstrap to search around these values.")


def _apply_thresholds(thresholds: dict):
    """Write the best thresholds to alert_dispatcher.py."""
    dispatcher_path = Path(__file__).resolve().parents[1] / "engine" / "alert_dispatcher.py"
    content = dispatcher_path.read_text(encoding="utf-8")

    replacements = {
        r"CRITICAL_PRIORITY = 0.65": f"CRITICAL_PRIORITY = {thresholds['critical']:.2f}",
        r"IMPORTANT_PRIORITY = 0.55": f"IMPORTANT_PRIORITY = {thresholds['important']:.2f}",
        r"STRATEGIC_CRITICAL_CONF = 0.70": f"STRATEGIC_CRITICAL_CONF = {thresholds.get('strategic_critical_conf', 0.70):.2f}",
    }

    applied = 0
    for old, new in replacements.items():
        import re
        if re.search(old, content):
            content = re.sub(old, new, content)
            applied += 1

    if applied:
        dispatcher_path.write_text(content, encoding="utf-8")
        logger.info("Applied %d threshold changes to %s", applied, dispatcher_path)
    else:
        logger.warning("No threshold patterns matched — manual review needed")


if __name__ == "__main__":
    main()
