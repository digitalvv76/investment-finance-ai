"""Web dashboard — optional HTTP subsystem for News Monitor.

Provides a real-time browser dashboard for news notifications and
system training.  Activated by setting the ``WEB_PORT`` environment
variable (or ``web.port`` in settings.yaml).

Lifecycle mirrors ``NewsBot``::

    dashboard = WebDashboard(db, curator, trainer, learner, port=8080)
    await dashboard.start()
    # ... system runs ...
    await dashboard.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from aiohttp import web

from web.sse_manager import SSEManager
from web.auth import basic_auth_middleware
from web.routes import (
    health_check,
    get_stats, get_recent_news, get_news_by_id,
    post_feedback,
    get_profile, put_profile,
    get_training_docs, post_training_url, post_training_text, post_training_file, delete_training_doc,
    get_filters, put_filters,
    get_alert_history, get_daily_digest,
    sse_events,
    impact_latest, impact_health, impact_stats,
    impact_calibration, impact_prompts, impact_detail, impact_outcomes,
    impact_health_events,
)

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent


class WebDashboard:
    """Optional HTTP server for the news-monitor dashboard.

    Wraps an aiohttp Application with REST API + SSE + static file serving.
    """

    def __init__(
        self,
        db=None,
        curator=None,
        trainer=None,
        learner=None,
        port: int = 8080,
        host: str = "0.0.0.0",
    ) -> None:
        self.db = db
        self.curator = curator
        self.trainer = trainer
        self.learner = learner
        self.port = port
        self.host = host

        self._sse = SSEManager()
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._stats_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _create_app(self) -> web.Application:
        app = web.Application()

        # Store subsystems on the app for route handlers
        app["db"] = self.db
        app["curator"] = self.curator
        app["trainer"] = self.trainer
        app["learner"] = self.learner
        app["sse_manager"] = self._sse
        app["impact_evaluator"] = getattr(self, "impact_evaluator", None)

        # CORS middleware (permissive for local dev)
        @web.middleware
        async def cors_middleware(request: web.Request, handler):
            if request.method == "OPTIONS":
                resp = web.Response()
            else:
                resp = await handler(request)
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            return resp

        # ---- Middleware (order matters: auth first, then CORS) ----
        app.middlewares.append(basic_auth_middleware)
        app.middlewares.append(cors_middleware)

        # ---- Serve dashboard HTML at / ----
        static_dir = _HERE / "static"
        async def index_handler(request: web.Request) -> web.FileResponse:
            return web.FileResponse(static_dir / "index.html")

        app.router.add_get("/", index_handler)

        # ---- Health check (no auth — for monitoring probes) ----
        app.router.add_get("/health", health_check)
        app.router.add_get("/api/health", health_check)

        # ---- API routes ----
        app.router.add_get("/api/stats", get_stats)
        app.router.add_get("/api/news/recent", get_recent_news)
        app.router.add_get("/api/news/{id}", get_news_by_id)
        app.router.add_post("/api/feedback", post_feedback)
        app.router.add_get("/api/profile", get_profile)
        app.router.add_put("/api/profile", put_profile)
        app.router.add_get("/api/training", get_training_docs)
        app.router.add_post("/api/training/url", post_training_url)
        app.router.add_post("/api/training/text", post_training_text)
        app.router.add_post("/api/training/file", post_training_file)
        app.router.add_delete("/api/training/{id}", delete_training_doc)
        app.router.add_get("/api/filters", get_filters)
        app.router.add_put("/api/filters", put_filters)
        app.router.add_get("/api/alerts/history", get_alert_history)
        app.router.add_get("/api/daily", get_daily_digest)
        app.router.add_get("/api/events", sse_events)
        app.router.add_get("/api/impact/latest", impact_latest)
        app.router.add_get("/api/impact/health", impact_health)
        app.router.add_get("/api/impact/stats", impact_stats)
        app.router.add_get("/api/impact/calibration", impact_calibration)
        app.router.add_get("/api/impact/prompts", impact_prompts)
        app.router.add_get("/api/impact/events", impact_health_events)
        app.router.add_get("/api/impact/{id}", impact_detail)
        app.router.add_get("/api/impact/{id}/outcomes", impact_outcomes)

        # ---- Static files ----
        static_dir = _HERE / "static"
        if static_dir.is_dir():
            app.router.add_static("/", static_dir, show_index=True)

        return app

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        logger.info("Web dashboard starting on http://%s:%d", self.host, self.port)

        self._app = self._create_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        # Periodic stats broadcast
        self._stats_task = asyncio.create_task(self._stats_loop())

        logger.info("Web dashboard running — open http://localhost:%d", self.port)

    async def stop(self) -> None:
        logger.info("Web dashboard stopping ...")

        if self._stats_task:
            self._stats_task.cancel()
            try:
                await self._stats_task
            except asyncio.CancelledError:
                pass

        if self._runner:
            await self._runner.cleanup()

        logger.info("Web dashboard stopped")

    # ------------------------------------------------------------------
    # Real-time broadcast
    # ------------------------------------------------------------------

    async def broadcast_alert(self, item: dict) -> None:
        """Push a news alert to all connected SSE clients."""
        await self._sse.broadcast("news_alert", item)

    async def broadcast_stats(self) -> None:
        """Push updated stats to all connected SSE clients."""
        if self.db:
            stats = self.db.get_db_stats()
            stats["sse_clients"] = self._sse.client_count
            await self._sse.broadcast("stats_update", stats)

    async def _stats_loop(self) -> None:
        """Broadcast stats every 60 seconds."""
        while True:
            await asyncio.sleep(60)
            try:
                await self.broadcast_stats()
            except Exception as e:
                logger.debug("Stats broadcast failed: %s", e)
