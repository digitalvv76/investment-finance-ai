"""Prompt A/B 对比实验 — 不改生产代码，本地运行新旧 prompt 对比输出。

用法: python scripts/compare_prompts.py [--limit N] [--verbose]

1. 加载 impact_v1.txt (线上版) 和 impact_v1_exp.txt (实验版)
2. 从 catalyst-cases 训练集取 N 条测试新闻
3. 每条新闻分别用两个 prompt 调用 DeepSeek
4. 输出逐条对比 + 汇总统计

实验版改动 (vs 线上版):
  A. greed_index 锚点 — 5 档市场状态映射 (0-30/31-45/46-55/56-70/71-100)
  B. confidence 混合信号降权 — 多空并存时降 20-40 分
  C. 快速预判 — 纯事实/中性报道低分快速通过
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from openai import OpenAI

PROMPT_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "training"

# ── 加载 prompt ──────────────────────────────────────────────

def load_prompt(filename: str) -> str:
    path = PROMPT_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


# ── LLM 调用 ──────────────────────────────────────────────────

def call_llm(system_prompt: str, user_prompt: str, label: str = "") -> dict | None:
    """调用 DeepSeek，返回解析后的 JSON dict。失败返回 None。"""
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com/v1",
    )
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1200,
            timeout=60,
        )
        raw = resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"  ⚠️  LLM 调用失败 [{label}]: {e}")
        return None

    # 解析 JSON (去 markdown 包裹)
    if raw.startswith("```"):
        import re
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON 解析失败 [{label}]: {e}")
        print(f"     raw (前200字): {raw[:200]}")
        return None


# ── 加载测试集 ────────────────────────────────────────────────

def load_test_cases_from_db(limit: int = 10, status_filter: str = None,
                           skip_recent: int = 0) -> list[dict]:
    """从生产 DB 取最近 N 条新闻。可选择只取已推送和跳过最近 N 条。"""
    import sqlite3
    db_path = Path(__file__).resolve().parent.parent / "data" / "news.db"
    if not db_path.is_file():
        print(f"DB not found: {db_path}")
        return []
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    where = "WHERE content_snippet IS NOT NULL AND length(content_snippet) > 50"
    params = []
    if status_filter:
        where += " AND status IN ('fast_pushed', 'deep_pushed')"
    rows = db.execute(f"""
        SELECT id, title, content_snippet, source, captured_at, status
        FROM news
        {where}
        ORDER BY captured_at DESC
        LIMIT ?
    """, [limit + skip_recent]).fetchall()
    db.close()

    # 跳过最近 skip_recent 条
    seen = 0
    cases = []
    for r in rows:
        if seen < skip_recent:
            seen += 1
            continue
        cases.append({
            "case_id": f"tg-{r['id']}",
            "title": r["title"],
            "snippet": (r["content_snippet"] or "")[:500],
            "source": r["source"],
            "status": r["status"] if "status" in r.keys() else "",
            "captured_at": r["captured_at"],
            "note": "",
            "beneficiaries": [], "losers": [], "linked_sectors": [], "sector_etf": [],
        })
        if len(cases) >= limit:
            break
    return cases


def load_test_cases_from_file(filepath: str, limit: int = 50) -> list[dict]:
    """从 JSONL 文件加载测试用例。"""
    cases = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            cases.append({
                "case_id": f"prod-{c.get('id', '?')}",
                "title": c.get("title", ""),
                "snippet": c.get("snippet", "")[:500],
                "source": c.get("source", ""),
                "captured_at": c.get("captured_at", ""),
                "note": "",
                "beneficiaries": [], "losers": [], "linked_sectors": [], "sector_etf": [],
            })
            if len(cases) >= limit:
                break
    return cases


def load_test_cases(limit: int = 12) -> list[dict]:
    """从 catalyst-cases 加载测试新闻。正例+负例各取一半。"""
    cases = []
    for filename in ["catalyst-cases.jsonl", "catalyst-cases-negative.jsonl"]:
        path = DATA_DIR / filename
        if not path.is_file():
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))

    # 选多样化的子集：正例+负例混合，按 case_id 排序后取 limit
    cases.sort(key=lambda c: c.get("case_id", ""))
    # 均匀采样而非只取前 N
    if len(cases) <= limit:
        return cases
    step = len(cases) / limit
    selected = [cases[int(i * step)] for i in range(limit)]
    return selected


# ── 构建 user prompt ──────────────────────────────────────────

def build_user_prompt(case: dict) -> str:
    """模拟 impact evaluator 的 user prompt 构建。"""
    title = case.get("title", "")
    # 优先用 snippet (DB 来源)，其次 note (训练集)，最后 market_reaction
    snippet = case.get("snippet", "") or case.get("note", "") or case.get("market_reaction", "")
    tickers = ", ".join(case.get("beneficiaries", []) + case.get("losers", []))
    sectors = ", ".join(case.get("linked_sectors", case.get("sector_etf", [])))

    parts = [f"Title: {title}"]
    if tickers:
        parts.append(f"Tickers: {tickers}")
    if sectors:
        parts.append(f"Macro tags: {sectors}")
    if snippet:
        parts.append(f"Content: {snippet[:800]}")
    return "\n".join(parts)


# ── 对比逻辑 ───────────────────────────────────────────────────

def compare_outputs(old: dict | None, new: dict | None, case: dict) -> dict:
    """逐字段对比新旧输出，返回差异摘要。"""
    fields = [
        ("impact_score", 0),
        ("confidence", 0),
        ("greed_index", 50),
        ("urgency", "INFO"),
        ("sentiment", "NEUTRAL"),
    ]
    diffs = {}
    for key, default in fields:
        ov = old.get(key, default) if old else None
        nv = new.get(key, default) if new else None
        if ov is None and nv is None:
            continue
        if ov is None:
            diffs[key] = {"old": None, "new": nv, "delta": "N/A (old failed)"}
        elif nv is None:
            diffs[key] = {"old": ov, "new": None, "delta": "N/A (new failed)"}
        elif isinstance(ov, (int, float)) and isinstance(nv, (int, float)):
            delta = nv - ov
            if abs(delta) >= 5:  # 只有 ≥5 分差异才报告
                diffs[key] = {"old": ov, "new": nv, "delta": delta}
        elif str(ov) != str(nv):
            diffs[key] = {"old": ov, "new": nv, "delta": f"{ov} → {nv}"}

    return diffs


# ── 主流程 ─────────────────────────────────────────────────────

async def main(limit: int = 12, verbose: bool = False, source: str = "training"):
    print("=" * 72)
    print("  Prompt A/B 对比实验")
    print("  A (旧版/线上): impact_v1_backup    B (新版/实验): impact_v1.txt")
    print("=" * 72)

    # 新版已合并到 impact_v1.txt，旧版在备份文件
    prompt_new = load_prompt("impact_v1.txt")
    # 如果有备份则用备份做旧版，否则回退到 impact_v1.txt (即新旧相同)
    backup_path = PROMPT_DIR / "impact_v1_backup_20260712.txt"
    if backup_path.is_file():
        prompt_old = backup_path.read_text(encoding="utf-8")
        print("  旧版: impact_v1_backup_20260712.txt (线上原版)")
        print("  新版: impact_v1.txt (已合并实验版)")
    else:
        prompt_old = prompt_new
        print("  ⚠️  无备份文件，新旧版本相同")

    # 验证实验版有 3 个改动标记
    checks = {
        "A. greed_index 锚点": "EXTREME FEAR" in prompt_new,
        "B. confidence 混合信号降权": "bullish and bearish" in prompt_new.lower(),
        "C. 快速预判": "QUICK PRE-SCREEN" in prompt_new,
    }
    print("\n改动确认:")
    for name, ok in checks.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    if not all(checks.values()):
        print("\n❌ 实验版 prompt 缺少预期改动，终止。")
        return

    if source == "db":
        cases = load_test_cases_from_db(limit)
        source_label = "生产 DB 最近新闻"
    elif source == "tg":
        cases = load_test_cases_from_db(limit, status_filter="pushed", skip_recent=10)
        source_label = "生产 DB 已推送 TG 新闻 (跳过已测10条)"
    elif source == "prod20":
        fpath = Path(__file__).resolve().parent.parent.parent / "data" / "training" / "prod-pushed-20260711.jsonl"
        cases = load_test_cases_from_file(str(fpath), limit)
        source_label = "ECS生产最近20条推送 (2026-07-11)"
    else:
        cases = load_test_cases(limit)
        source_label = "catalyst-cases 训练集"
    print(f"\n测试集: {len(cases)} 条 ({source_label})")
    print(f"每条调用 2 次 LLM (A+B)，共 {len(cases) * 2} 次调用\n")

    results = []
    t0 = time.monotonic()

    for i, case in enumerate(cases):
        cid = case.get("case_id", f"#{i}")
        user_prompt = build_user_prompt(case)

        print(f"[{i+1}/{len(cases)}] {cid}: {case['title'][:60]}...")

        # 并行调用新旧 prompt（同一新闻的两个版本可并行）
        old_task = asyncio.to_thread(call_llm, prompt_old, user_prompt, f"A-{cid}")
        new_task = asyncio.to_thread(call_llm, prompt_new, user_prompt, f"B-{cid}")
        old_result, new_result = await asyncio.gather(old_task, new_task)

        diffs = compare_outputs(old_result, new_result, case)

        if diffs:
            print(f"  📊 {len(diffs)} 个字段有差异:")
            for key, d in diffs.items():
                if isinstance(d["delta"], (int, float)):
                    direction = "↑" if d["delta"] > 0 else "↓"
                    print(f"     {key}: {d['old']} → {d['new']} ({direction}{abs(d['delta'])})")
                else:
                    print(f"     {key}: {d['delta']}")
        else:
            if old_result is None and new_result is None:
                print(f"  ❌ 双方均调用失败")
            elif old_result is None:
                print(f"  ⚠️  仅 A 失败，B 成功")
            elif new_result is None:
                print(f"  ⚠️  仅 B 失败，A 成功")
            else:
                print(f"  ✅ 无显著差异 (各字段差值 < 5)")

        results.append({
            "case_id": cid,
            "title": case["title"],
            "old": old_result,
            "new": new_result,
            "diffs": diffs,
        })

        if verbose and (old_result or new_result):
            res = old_result or new_result or {}
            print(f"     impact={res.get('impact_score','?')} "
                  f"confidence={res.get('confidence','?')} "
                  f"greed={res.get('greed_index','?')} "
                  f"urgency={res.get('urgency','?')} "
                  f"sentiment={res.get('sentiment','?')}")

        # 避免触发限流
        await asyncio.sleep(0.3)

    elapsed = time.monotonic() - t0

    # ── 汇总报告 ──────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  汇总报告")
    print("=" * 72)

    total = len(results)
    both_ok = sum(1 for r in results if r["old"] and r["new"])
    old_only = sum(1 for r in results if r["old"] and not r["new"])
    new_only = sum(1 for r in results if r["new"] and not r["old"])
    both_fail = sum(1 for r in results if not r["old"] and not r["new"])
    with_diffs = sum(1 for r in results if r["diffs"])

    print(f"\n成功率: A={both_ok + old_only}/{total}  B={both_ok + new_only}/{total}")
    print(f"双方成功: {both_ok}  仅A成功: {old_only}  仅B成功: {new_only}  双方失败: {both_fail}")
    print(f"有显著差异的用例: {with_diffs}/{both_ok}")

    # 字段级统计（只统计双方都成功的）
    field_stats = {}
    for r in results:
        if not r["old"] or not r["new"]:
            continue
        for key in ["impact_score", "confidence", "greed_index"]:
            ov = r["old"].get(key, 0)
            nv = r["new"].get(key, 0)
            if key not in field_stats:
                field_stats[key] = {"deltas": [], "increases": 0, "decreases": 0}
            if abs(nv - ov) >= 5:
                field_stats[key]["deltas"].append(nv - ov)
                if nv > ov:
                    field_stats[key]["increases"] += 1
                else:
                    field_stats[key]["decreases"] += 1

    if field_stats:
        print("\n字段级差异 (双方成功 + 差值≥5):")
        for key, stats in field_stats.items():
            deltas = stats["deltas"]
            if not deltas:
                print(f"  {key}: 无显著差异")
                continue
            avg = sum(deltas) / len(deltas)
            print(f"  {key}: ↑{stats['increases']}次 ↓{stats['decreases']}次  "
                  f"平均Δ={avg:+.1f}  范围=[{min(deltas):+.0f}, {max(deltas):+.0f}]")

    # sentiment / urgency 变化
    sentiment_changes = 0
    urgency_changes = 0
    for r in results:
        if not r["old"] or not r["new"]:
            continue
        if r["old"].get("sentiment") != r["new"].get("sentiment"):
            sentiment_changes += 1
        if r["old"].get("urgency") != r["new"].get("urgency"):
            urgency_changes += 1
    print(f"\nSentiment 变化: {sentiment_changes}/{both_ok} 条")
    print(f"Urgency 变化:   {urgency_changes}/{both_ok} 条")

    # ── 保存详细结果 ──────────────────────────────────────────
    out_path = Path(__file__).resolve().parent.parent / "data" / "experiments"
    out_path.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    result_file = out_path / f"prompt-compare-{timestamp}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "config": {"limit": limit, "prompt_old": "impact_v1.txt", "prompt_new": "impact_v1_exp.txt"},
            "elapsed_s": round(elapsed, 1),
            "summary": {
                "total": total, "both_ok": both_ok, "old_only": old_only,
                "new_only": new_only, "both_fail": both_fail, "with_diffs": with_diffs,
                "field_stats": {k: {"avg_delta": round(sum(v["deltas"])/len(v["deltas"]), 1) if v["deltas"] else 0,
                                     "increases": v["increases"], "decreases": v["decreases"]}
                                for k, v in field_stats.items()},
                "sentiment_changes": sentiment_changes,
                "urgency_changes": urgency_changes,
            },
            "results": [{k: r[k] for k in ["case_id", "title", "old", "new", "diffs"]} for r in results],
        }, f, ensure_ascii=False, indent=2)

    print(f"\n完整结果已保存: {result_file}")
    if total > 0:
        print(f"耗时: {elapsed:.0f}s  ({(elapsed/total*2):.1f}s/调用)")
    else:
        print(f"耗时: {elapsed:.0f}s")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Prompt A/B 对比实验")
    p.add_argument("--limit", type=int, default=12, help="测试条数 (默认 12)")
    p.add_argument("--source", choices=["training", "db", "tg", "prod20"], default="training",
                   help="数据源: training (训练集), db (生产DB最近), tg (TG推送), prod20 (ECS生产20条)")
    p.add_argument("--verbose", "-v", action="store_true", help="显示每条完整输出")
    args = p.parse_args()
    asyncio.run(main(limit=args.limit, verbose=args.verbose, source=args.source))
