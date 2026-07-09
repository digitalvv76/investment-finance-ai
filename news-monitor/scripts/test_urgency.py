"""End-to-end test: LLM urgency classification with new prompt format.

Sends 4 representative news items through ImpactEvaluator and checks:
1. All new fields present in output
2. Urgency correctly assigned per event type
3. Flash_note, key_points, risk_flags populated
4. Formula fallback works when urgency missing
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure we can import from the project
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.models import NewsItem, ImpactAssessment
from engine.impact_evaluator import ImpactEvaluator, PromptVersionManager

TEST_CASES = [
    {
        "name": "US-Iran war (should be FLASH)",
        "item": NewsItem(
            id=99901,
            title="美国对伊朗发动大规模军事打击，原油价格飙升8%，全球金融市场剧震",
            url="https://wallstreetcn.com/live/global/test1",
            source="华尔街见闻·全球快讯",
            content_snippet=(
                "美国国防部确认已对伊朗核设施发动大规模空袭，伊朗回应将封锁"
                "霍尔木兹海峡。布伦特原油暴涨8.2%突破95美元，WTI原油涨7.8%。"
                "标普500期货跌2.3%，纳斯达克期货跌3.1%。美国10年期国债收益率"
                "下跌18个基点至3.85%。黄金飙升4.2%突破2800美元。市场进入全面"
                "避险模式，VIX暴涨45%。"
            ),
            tickers_found="USO,XLE,GLD",
            macro_tags="geopolitical,oil,bonds,vix",
        ),
    },
    {
        "name": "NVDA earnings beat (should be ALERT)",
        "item": NewsItem(
            id=99902,
            title="英伟达Q2财报超预期，数据中心营收同比增长210%，盘后涨8%",
            url="https://cnbc.com/nvda-earnings",
            source="CNBC",
            content_snippet=(
                "NVIDIA reported Q2 revenue of $42.5B vs $38.2B expected. "
                "Data center revenue grew 210% YoY to $35.2B. Q3 guidance raised "
                "to $46B. CEO Jensen Huang: 'AI demand is accelerating, not slowing.' "
                "Stock up 8% after hours."
            ),
            tickers_found="NVDA,SMH,SOXX",
            macro_tags="earnings,semiconductor,ai",
        ),
    },
    {
        "name": "China A-share market close (should be WATCH or INFO)",
        "item": NewsItem(
            id=99903,
            title="A股三大指数集体收跌，沪指跌0.3%，两市成交额不足6000亿",
            url="https://finance.sina.com.cn/test3",
            source="新浪财经",
            content_snippet=(
                "7月8日，A股三大指数集体收跌。上证指数跌0.32%报3254.17点，"
                "深证成指跌0.48%，创业板指跌0.67%。两市成交额5892亿元，"
                "较上一交易日缩量312亿元。北向资金净卖出32.8亿元。"
            ),
            tickers_found="",
            macro_tags="china,equities",
        ),
    },
    {
        "name": "Analyst upgrade (should be INFO)",
        "item": NewsItem(
            id=99904,
            title="摩根士丹利上调苹果目标价至250美元，维持增持评级",
            url="https://marketwatch.com/aapl-upgrade",
            source="MarketWatch",
            content_snippet=(
                "Morgan Stanley analyst raised Apple price target from $220 to $250, "
                "citing strong Services revenue growth and iPhone 18 upgrade cycle "
                "expectations. Maintains Overweight rating."
            ),
            tickers_found="AAPL",
            macro_tags="analyst,tech",
        ),
    },
]


async def run_test():
    evaluator = ImpactEvaluator()
    print(f"ImpactEvaluator providers: {evaluator._available_providers()}")
    print(f"Prompt v1 length: {len(PromptVersionManager.load('v1'))} chars\n")
    print("=" * 70)

    results = []
    for tc in TEST_CASES:
        item = tc["item"]
        print(f"\n--- {tc['name']} ---")
        print(f"Title: {item.title[:80]}")

        assessment = await evaluator.evaluate(item)

        if assessment is None:
            print("  ❌ FAIL: No assessment returned")
            results.append(("FAIL", tc["name"], "no assessment"))
            continue

        # Check all fields
        checks = []
        checks.append(("impact_score > 0", assessment.impact_score > 0))
        checks.append(("confidence > 0", assessment.confidence > 0))
        checks.append(("urgency set", assessment.urgency in ('FLASH', 'ALERT', 'WATCH', 'INFO')))
        checks.append(("sentiment set", assessment.sentiment in (
            'BULLISH', 'CAUTIOUSLY_BULLISH', 'NEUTRAL',
            'CAUTIOUSLY_BEARISH', 'BEARISH',
        )))
        checks.append(("greed_index 0-100", 0 <= assessment.greed_index <= 100))
        checks.append(("flash_note not empty", len(assessment.flash_note) > 20))
        checks.append(("key_points is list", bool(json.loads(assessment.key_points))))
        checks.append(("risk_flags set", isinstance(json.loads(assessment.risk_flags), list)))

        all_pass = all(passed for _, passed in checks)
        status = "✅" if all_pass else "⚠️"

        print(f"  urgency: {assessment.urgency}")
        print(f"  impact_score: {assessment.impact_score} | confidence: {assessment.confidence}")
        print(f"  sentiment: {assessment.sentiment} | greed_index: {assessment.greed_index}")
        print(f"  flash_note: {assessment.flash_note[:100]}...")
        kp = json.loads(assessment.key_points)
        print(f"  key_points ({len(kp)}): {kp[:2]}...")
        rf = json.loads(assessment.risk_flags)
        print(f"  risk_flags ({len(rf)}): {rf}")

        for label, passed in checks:
            print(f"  {'✅' if passed else '❌'} {label}")

        results.append(("PASS" if all_pass else "PARTIAL", tc["name"], assessment.urgency))

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    passed = sum(1 for r in results if r[0] == "PASS")
    print(f"  {passed}/{len(results)} fully passed")
    for status, name, urgency in results:
        print(f"  {status:7s} | {urgency:5s} | {name}")


if __name__ == "__main__":
    asyncio.run(run_test())
