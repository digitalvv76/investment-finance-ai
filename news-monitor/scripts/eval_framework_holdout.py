"""Holdout blind evaluation — 检验 event_driven 评估框架准不准。

把人工标注答案藏起来，只喂事件陈述(title)给评估器，对比它自己判的
强度/受益股/方向/推送决策 vs 人工 ground truth。

排除已嵌入 prompt 的 4 条 few-shot 样本(gov-01/gov-07/jensen-07/gov-10)，
避免数据泄露虚高。用剩下 14 条干净盲测集。

Usage: python scripts/eval_framework_holdout.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from storage.models import NewsItem
from engine.event_driven_evaluator import EventDrivenEvaluator

# 已嵌入 prompt 的 few-shot 样本 — 排除以防数据泄露
SEEN_IN_PROMPT = {"gov-01", "gov-07", "jensen-07", "gov-10", "jensen-05"}
DATA = Path(__file__).resolve().parent.parent.parent / "data" / "training" / "catalyst-cases.jsonl"


def load_holdout():
    rows = [json.loads(l) for l in open(DATA, encoding="utf-8") if l.strip()]
    return [r for r in rows if r["case_id"] not in SEEN_IN_PROMPT]


async def main():
    holdout = load_holdout()
    ev = EventDrivenEvaluator()
    print(f"盲测集: {len(holdout)} 条 (已排除 {len(SEEN_IN_PROMPT)} 条 few-shot 样本)\n")
    print(f"{'case':<11}{'强度 判/真':<12}{'方向':<10}{'推送':<8}{'受益股召回':<12}")
    print("-" * 78)

    intensity_exact = 0     # 强度完全命中
    intensity_within1 = 0   # 强度 ±1 星容差
    push_match = 0          # 推送决策(is_push)一致
    recall_sum = 0.0        # 受益股召回率累加
    recall_n = 0

    for r in holdout:
        item = NewsItem(id=0, title=r["title"], content_snippet="")
        try:
            a = await ev.evaluate(item)
        except Exception as e:
            print(f"{r['case_id']:<11} ERROR: {e}")
            continue

        # 强度对比
        pred_i, true_i = a.intensity, r["intensity"]
        if pred_i == true_i:
            intensity_exact += 1
        if abs(pred_i - true_i) <= 1:
            intensity_within1 += 1

        # 推送决策对比
        pred_push = a.should_push
        true_push = r["is_push"]
        if pred_push == true_push:
            push_match += 1

        # 受益股召回率 (人工标的中，评估器命中几个)
        truth_tickers = set(t.upper() for t in r.get("beneficiaries", []) if t and t[0].isalpha())
        pred_tickers = set(t.upper() for t in a.ticker_hint)
        if truth_tickers:
            hit = len(truth_tickers & pred_tickers)
            recall = hit / len(truth_tickers)
            recall_sum += recall
            recall_n += 1
            recall_str = f"{hit}/{len(truth_tickers)}"
        else:
            recall_str = "n/a"

        i_flag = "✅" if pred_i == true_i else ("~" if abs(pred_i - true_i) <= 1 else "❌")
        p_flag = "✅" if pred_push == true_push else "❌"
        print(f"{r['case_id']:<11}{pred_i}/{true_i} {i_flag:<8}{a.event_types!s:<10}"
              f"{('推' if pred_push else '不推')}{p_flag:<5}{recall_str:<12} {r['title'][:22]}")

    n = len(holdout)
    print("-" * 78)
    print(f"\n📊 框架准确率报告 (n={n}, 干净盲测):")
    print(f"  强度完全命中:   {intensity_exact}/{n} = {intensity_exact/n*100:.0f}%")
    print(f"  强度±1星容差:   {intensity_within1}/{n} = {intensity_within1/n*100:.0f}%")
    print(f"  推送决策一致:   {push_match}/{n} = {push_match/n*100:.0f}%")
    if recall_n:
        print(f"  受益股平均召回: {recall_sum/recall_n*100:.0f}% (n={recall_n})")


if __name__ == "__main__":
    asyncio.run(main())
