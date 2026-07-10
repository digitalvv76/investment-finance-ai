"""Playwright acceptance harness for the /health/decisions panel."""
import asyncio
import os
from collections import deque
from web.server import WebDashboard


class _StubDecisions:
    def __init__(self):
        self.recent_decisions = deque([
            {"id": 2, "title": "Tesla stock gets stunning price target hike from UBS",
             "level": "notable", "silent": True, "ticker_hint": ["TSLA"],
             "headline_signal": "分析师大幅上调目标价", "reason": "watchlist_safety_net"},
            {"id": 1, "title": "Fed signals emergency rate cut",
             "level": "important", "silent": False, "ticker_hint": ["SPY"],
             "headline_signal": "美联储紧急降息", "reason": "high impact"},
        ])


class _StubDB:
    def get_db_stats(self):
        return {"news_count": 0, "feedback_count": 0, "event_count": 0, "db_size_mb": 0.1}


async def main():
    port = int(os.environ.get("DEC_PORT", "8102"))
    dash = WebDashboard(db=_StubDB(), port=port, host="127.0.0.1")
    dash.decisions_source = _StubDecisions()
    await dash.start()
    print(f"HARNESS READY port={port}", flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
