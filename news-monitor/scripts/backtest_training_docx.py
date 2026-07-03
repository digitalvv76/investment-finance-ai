"""Backtest the 21 training cases from .docx through the 4-dimension signal model.

These are the MOST IMPORTANT cases — government investment (11 cases) and
Jensen Huang/NVIDIA (10 cases). They were used to validate StrategicDetector.
"""

import re
import sys
from pathlib import Path

_pkg = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_pkg))

from engine.relevance import signal_score
from engine.strategic_detector import StrategicDetector

DOCX_PATH = Path(r"C:\Users\nycr\OneDrive\Desktop\训练资料.docx")

# ---------------------------------------------------------------------------
# Parse the docx
# ---------------------------------------------------------------------------

def parse_training_docx(path: Path) -> list[dict]:
    """Extract individual cases from the training docx."""
    try:
        import docx
    except ImportError:
        print("python-docx not installed. pip install python-docx")
        return []

    doc = docx.Document(str(path))
    full_text = "\n".join(p.text for p in doc.paragraphs)

    cases = []
    # Each case starts with "### 案例N："
    sections = re.split(r"### 案例\d+[：:]", full_text)
    for sec in sections[1:]:  # first split is preamble
        lines = [l.strip() for l in sec.split("\n") if l.strip()]
        if not lines:
            continue

        # Title is the first line
        title = lines[0]

        # Extract fields
        desc_parts = []
        market_reaction = ""
        tickers = []

        for line in lines:
            if "**市场反应**" in line or "**市場反應**" in line:
                market_reaction = line.split("**", 2)[-1].strip("：:").strip()
            elif "**受影响标的**" in line or "**受影響標的**" in line:
                raw = line.split("**", 2)[-1].strip("：:").strip()
                tickers = [t.strip() for t in re.split(r"[、,，]", raw) if t.strip()]
            elif line.startswith("**") and "**" in line[2:]:
                desc_parts.append(line)
            elif line == title:
                continue
            elif desc_parts or market_reaction:
                pass  # already collecting

        # Build description from title + key fields
        description = title
        for part in desc_parts[:3]:  # first 3 key fields
            clean = re.sub(r"\*\*.*?\*\*[：:]?\s*", "", part).strip()
            if clean and len(clean) > 5:
                description += " " + clean

        if description:
            cases.append({
                "title": title[:100],
                "description": description[:500],
                "market_reaction": market_reaction[:200],
                "tickers": tickers,
            })

    return cases


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def backtest(cases: list[dict]):
    sd = StrategicDetector()
    results = []

    for i, c in enumerate(cases):
        desc = c["description"]
        tickers_str = ", ".join(c.get("tickers", []))
        market = c.get("market_reaction", "")

        # Detect strategic matches
        matches = sd.detect(desc)
        has_strategic = len(matches) > 0
        best_cat = matches[0].category if matches else "none"
        best_conf = matches[0].confidence if matches else 0

        # Determine if this is gov or nvidia from title
        is_gov = "政府" in c["title"] or "gov" in c["title"].lower() or any(
            kw in c["title"] for kw in ["Intel", "MP Materials", "L3Harris",
                                         "通用汽车", "U.S. Steel", "芯片法案",
                                         "关键矿产", "核能", "煤炭", "量子"]
        )
        is_nvda = "黄仁勋" in c["title"] or "英伟达" in c["title"] or "NVIDIA" in c["title"] or any(
            kw in c["title"] for kw in ["Marvell", "Nokia", "SK海力士",
                                         "高通", "Adobe", "机器人",
                                         "AMD", "艾默生", "摩根"]
        )

        # 4-dimension signal
        sig = signal_score(
            news_tickers=tickers_str,
            news_text=desc,
            macro_tags="",
            strategic_matches=matches,
            is_breaking=False,
        )

        results.append({
            "id": i + 1,
            "title": c["title"][:80],
            "type": "gov" if is_gov else ("nvda" if is_nvda else "other"),
            "has_strategic": has_strategic,
            "best_category": best_cat,
            "best_conf": best_conf,
            "composite": sig["composite"],
            "timeliness": sig["timeliness"],
            "novelty": sig["novelty"],
            "relevance": sig["relevance"],
            "direction": sig["relevance_direction"],
            "tickers": tickers_str[:60],
            "market": c.get("market_reaction", "")[:80],
        })

    return results


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def display(results: list[dict]):
    CRITICAL = 0.50
    IMPORTANT = 0.35

    def push_level(c):
        if c >= CRITICAL: return "CRITICAL"
        if c >= IMPORTANT: return "IMPORTANT"
        return "SILENT"

    print(f"{'#':>2} {'Type':>4} {'comp':>6} {'push':>9} {'strat':>8} {'rel':>4}  Title")
    print("-" * 120)

    for r in results:
        push = push_level(r["composite"])
        strat = f"{r['best_category']}:{r['best_conf']:.0%}" if r["has_strategic"] else "none"
        marker = "!!!" if push == "CRITICAL" else (" ! " if push == "IMPORTANT" else "   ")
        print(f"{r['id']:2d} {r['type']:>4} {r['composite']:6.3f} {push:>9} {marker} "
              f"{strat[:8]:>8} {r['relevance']:4.2f}  {r['title'][:75]}")

    # Summary
    gov = [r for r in results if r["type"] == "gov"]
    nvda = [r for r in results if r["type"] == "nvda"]
    strategic = [r for r in results if r["has_strategic"]]
    pushed = [r for r in results if push_level(r["composite"]) != "SILENT"]
    crit = [r for r in results if push_level(r["composite"]) == "CRITICAL"]

    print(f"\n{'='*70}")
    print(f"  SUMMARY: {len(results)} cases")
    print(f"  Gov investment:  {len(gov)} cases, {len([r for r in gov if r['has_strategic']])} detected by StrategicDetector")
    print(f"  NVIDIA/Huang:    {len(nvda)} cases, {len([r for r in nvda if r['has_strategic']])} detected by StrategicDetector")
    print(f"  Pushed: {len(pushed)}/{len(results)} ({len(crit)} CRITICAL)")
    print(f"  Avg composite: gov={sum(r['composite'] for r in gov)/len(gov):.3f}  "
          f"nvda={sum(r['composite'] for r in nvda)/len(nvda):.3f}" if nvda else "")

    # Strategic detector diagnostic
    missed = [r for r in results if not r["has_strategic"]]
    if missed:
        print(f"\n  NOT DETECTED by StrategicDetector ({len(missed)} cases):")
        for r in missed:
            print(f"    #{r['id']}: {r['title'][:80]}")

    print(f"{'='*70}")


if __name__ == "__main__":
    cases = parse_training_docx(DOCX_PATH)
    if not cases:
        print("No cases found.")
        sys.exit(1)
    print(f"Parsed {len(cases)} training cases from docx")
    results = backtest(cases)
    display(results)
