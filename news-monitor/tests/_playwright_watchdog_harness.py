"""Playwright acceptance harness for the Watchdog health page.

Starts a minimal real WebDashboard (aiohttp) with a Watchdog wired in,
backed by a stub DB whose ingestion count is controlled by SCENARIO env:
    SCENARIO=healthy  → ingest above floor → page shows ✅ / state=healthy
    SCENARIO=stalled  → zero ingestion     → page shows 🔴 / state=stalled

Run:  SCENARIO=stalled WATCHDOG_PORT=8099 python tests/_playwright_watchdog_harness.py
Then Playwright navigates http://localhost:8099/health/watchdog and asserts.
"""

import asyncio
import os

from web.server import WebDashboard
from engine.watchdog import Watchdog


class _StubDB:
    def __init__(self, ingest_1h):
        self._ingest = ingest_1h

    def get_recent_news(self, hours=24, limit=500):
        n = self._ingest if hours <= 1 else self._ingest * 20
        return [{"id": i, "status": "archived", "captured_at": "2026-07-10T00:00:00"}
                for i in range(n)]

    def get_health_stats(self, hours=1):
        return {"total_assessments_1h": 20, "health_events_1h": 0, "success_rate": 100.0}

    def insert_health_event(self, e):
        return 1

    def get_db_stats(self):
        return {"news_count": 0, "feedback_count": 0, "event_count": 0, "db_size_mb": 0.1}


class _NoPushDispatcher:
    async def send_system_alert(self, *a, **k):
        return False


async def main():
    scenario = os.environ.get("SCENARIO", "healthy")
    port = int(os.environ.get("WATCHDOG_PORT", "8099"))
    ingest = 10 if scenario == "healthy" else 0

    db = _StubDB(ingest)
    wd = Watchdog(db, _NoPushDispatcher(), {"watchdog": {"consecutive_bad_threshold": 99}})
    await wd.check(now_monotonic=0.0)  # populate last_verdict from stub data

    dash = WebDashboard(db=db, port=port, host="127.0.0.1")
    dash.watchdog = wd
    await dash.start()
    print(f"HARNESS READY scenario={scenario} port={port} state={wd.last_verdict.state.value}", flush=True)

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
