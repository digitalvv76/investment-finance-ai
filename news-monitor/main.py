"""Financial News Monitor -- main entry point.

Wires together the scheduler, fast-lane engine, deep-lane orchestrator,
and Telegram bot into a single runnable process.  Callbacks flow through:

    Scheduler -> Dedup -> FastLane (rule engine) -> DB update -> Telegram push
                                                    |
                                                    v
                                              DeepLane (async, LLM-gated)
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Load .env from repo root BEFORE any module reads os.environ.
# find_dotenv() walks up from this file's directory to find D:/class1/.env.
from dotenv import load_dotenv, find_dotenv
_env_path = find_dotenv(usecwd=True)
if _env_path:
    load_dotenv(_env_path)

# Ensure the news-monitor package directory is importable when running
# directly (``python main.py``) regardless of how the working directory
# is set up.
_pkg_root = Path(__file__).resolve().parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from config.loader import ConfigLoader
from storage.database import Database
from storage.vector_store import VectorStore
from collector.dedup import DedupManager
from collector.scheduler import NewsScheduler
from engine.fast_lane import FastLane
from engine.deep_lane import DeepLane
from engine.learner import Learner
from engine.curator import Curator
from engine.trainer import Trainer
from engine.alert_dispatcher import AlertDispatcher, AlertLevel
from engine.strategic_detector import StrategicDetector
from engine.impact_evaluator import ImpactEvaluator
from engine.event_driven_evaluator import EventDrivenEvaluator
from engine.impact_learner import ImpactLearner
from engine.event_matcher import EventMatcher
from engine.watchdog import Watchdog
from engine.relevance import signal_score, get_portfolio_summary
from engine.actionability_review import ActionabilityReviewer
from collector.fund_flow_collector import FundFlowCollector
from bot.telegram_bot import NewsBot
from web.routes import refresh_cached_db_health

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
from logging.handlers import RotatingFileHandler
from pathlib import Path as _Path

_log_dir = _Path("logs")
_log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler(
            _log_dir / "news_monitor.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Startup banner
logger.info("=" * 60)
logger.info("Financial News Monitor v1.0 starting")
logger.info("Python: %s | Platform: %s", sys.version.split()[0], sys.platform)
logger.info("=" * 60)


# ===================================================================
# NewsMonitor
# ===================================================================


class NewsMonitor:
    """Top-level orchestrator that owns every subsystem."""

    def __init__(self) -> None:
        # ---- config -------------------------------------------------
        self.config = ConfigLoader(str(_pkg_root / "config"))

        # Validate config at startup — logs warnings but does not abort
        issues = self.config.validate()
        if issues:
            critical = [i for i in issues if "failed to load" in i]
            if critical:
                logger.error("FATAL config errors: %s", critical)
                raise SystemExit(1)
            logger.warning("Config has %d non-fatal issue(s) — continuing", len(issues))

        # ---- database -----------------------------------------------
        settings = self.config.load_settings()
        db_path = settings["storage"]["sqlite_path"]
        self.db = Database(db_path)
        self.db.init_db()
        self.db.migrate_event_escalation()

        # ---- vector store (semantic dedup + similarity) -------------
        self.vector_store = VectorStore(
            persist_path=settings["storage"].get("chroma_path", "data/chroma")
        )
        try:
            self.vector_store.initialize()
        except Exception as e:
            logger.warning("VectorStore unavailable — semantic dedup disabled: %s", e)

        # ---- dedup (with semantic tier) -----------------------------
        self.dedup = DedupManager(vector_store=self.vector_store)

        # ---- scheduler ----------------------------------------------
        self.scheduler = NewsScheduler(self.config, self.db, self.dedup)

        # ---- fast-lane rule engine (with semantic resonance) --------
        self.fast_lane = FastLane(self.config, self.db, vector_store=self.vector_store)

        # ---- deep-lane orchestrator ---------------------------------
        self.deep_lane = DeepLane(self.config, self.db)

        # ---- learning engine ----------------------------------------
        self.learner = Learner(self.db)

        # ---- knowledge base trainer ---------------------------------
        self.trainer = Trainer(self.db)

        # ---- AI curator ---------------------------------------------
        self.curator = Curator(self.db, self.trainer)

        # ---- alert dispatcher (Pushover + enhanced Telegram) ----------
        self.alert_dispatcher = AlertDispatcher()
        self._strategic = StrategicDetector()

        # ---- watchdog (independent liveness monitor) ----------------
        # Runs on its OWN task, not inside the scheduler, so a scheduler
        # hang cannot also silence the watchdog.
        self.watchdog = Watchdog(
            self.db, self.alert_dispatcher, self.config.load_settings(),
        )

        # ---- impact evaluator (LLM, async, isolated) --------
        self.impact_evaluator = ImpactEvaluator()
        self.event_evaluator = EventDrivenEvaluator()
        self.impact_learner = ImpactLearner()
        self.event_matcher = EventMatcher()
        self.actionability_reviewer = ActionabilityReviewer()
        logger.info("ImpactEvaluator initialized (threshold=%.2f, event_matcher=%d events)",
                    ImpactEvaluator.THRESHOLD, self.event_matcher.event_count)
        logger.info("EventDrivenEvaluator initialized (prompt v1, temperature=0)")
        logger.info("Portfolio/Relevance: %s", get_portfolio_summary())

        # ---- fund flow collector (daily post-market) -----------------
        ff_cfg = settings.get("fund_flow", {})
        futu_host = os.environ.get("FUTU_OPEND_HOST", "172.18.0.1")  # docker bridge gateway
        futu_port = int(os.environ.get("FUTU_OPEND_PORT", "11111"))
        self.fund_flow_collector = FundFlowCollector(
            db=self.db,
            alert_dispatcher=self.alert_dispatcher,
            bot=None,  # wired after bot creation below
            futu_host=futu_host,
            futu_port=futu_port,
            watchlist=ff_cfg.get("tickers") or None,
            days_to_fetch=ff_cfg.get("days_to_fetch", 20),
        )

        # ---- Telegram bot -------------------------------------------
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN not set -- bot disabled")
            self.bot = None
        else:
            self.bot = NewsBot(token, self.db, self.config, self.deep_lane, self.learner, self.curator, self.trainer)
            self.fund_flow_collector._bot = self.bot

        # ---- web dashboard (optional) --------------------------------
        web_port = int(os.environ.get("WEB_PORT", "0"))
        self._sse_manager = None
        if web_port > 0:
            from web.server import WebDashboard
            self.web_dashboard = WebDashboard(
                db=self.db, curator=self.curator, trainer=self.trainer,
                learner=self.learner, deep_lane=self.deep_lane, port=web_port,
            )
            self.web_dashboard.impact_evaluator = self.impact_evaluator
            self.web_dashboard.watchdog = self.watchdog
            self._sse_manager = getattr(self.web_dashboard, 'sse_manager', None)
            logger.info("Web dashboard enabled on port %d", web_port)
        else:
            self.web_dashboard = None

        # ---- event clustering + escalation --------------------------
        from engine.cluster import NewsCluster
        from engine.market_snapshot import MarketSnapshot
        from engine.event_escalator import EventEscalator
        self.cluster = NewsCluster(self.db, vector_store=self.vector_store)
        self.market_snapshot = MarketSnapshot()
        self.escalator = EventEscalator(
            self.db, self.alert_dispatcher, self.market_snapshot, self.config,
            telegram_push_provider=(lambda: self.alert_dispatcher.wrap_telegram_push(self.bot)) if self.bot else None,
        )

        # ---- market snapshot collector (pre-market + intraday) ----------
        from collector.market_snapshot import MarketSnapshotCollector
        futu_host = os.environ.get("FUTU_OPEND_HOST", "172.18.0.1")
        futu_port = int(os.environ.get("FUTU_OPEND_PORT", "11111"))
        self.snapshot_collector = MarketSnapshotCollector(
            host=futu_host, port=futu_port,
        )

        # ---- sector rotation collector (post-market daily) -------------
        from collector.sector_rotation import SectorRotationCollector
        self.sector_collector = SectorRotationCollector(
            host=futu_host, port=futu_port,
        )

        # ── Build Phase 3 Pipeline ──
        from pipeline import Pipeline
        from pipeline.ingest import IngestStage
        from pipeline.macro import MacroStage
        from pipeline.screen import ScreenStage
        from pipeline.evaluate import EvaluateStage
        from pipeline.dispatch import DispatchStage
        from pipeline.deep import DeepStage
        from pipeline.channel import PushoverChannel, TelegramChannel, WebSSEChannel
        from engine.macro_agent import MacroAgent

        channels = []
        channels.append(PushoverChannel(self.alert_dispatcher))
        if self.bot:
            channels.append(TelegramChannel(self.bot))
        if self._sse_manager:
            channels.append(WebSSEChannel(self._sse_manager))

        self._dispatch_stage = DispatchStage(channels=channels)
        self._macro_agent = MacroAgent()
        self._pipeline = Pipeline([
            IngestStage(db=self.db, dedup=self.dedup, vector_store=self.vector_store, cluster=self.cluster),
            MacroStage(macro_agent=self._macro_agent),
            ScreenStage(fast_lane=self.fast_lane),
            EvaluateStage(
                impact_evaluator=self.impact_evaluator,
                dispatcher=self.alert_dispatcher,
                actionability_reviewer=self.actionability_reviewer,
                db=self.db,
                event_evaluator=self.event_evaluator,
                cluster=self.cluster,
            ),
            self._dispatch_stage,
            DeepStage(deep_lane=self.deep_lane),
        ])
        # Expose recent decisions to the web panel (dashboard built before pipeline).
        if self.web_dashboard is not None:
            self.web_dashboard.decisions_source = self._dispatch_stage
        logger.info("Pipeline: IngestStage → MacroStage → ScreenStage → EvaluateStage → DispatchStage → DeepStage")

    # -----------------------------------------------------------------
    # Callback - wired to scheduler.on_news_batch
    # -----------------------------------------------------------------

    async def on_news_batch(self, items):
        """Phase 3 pipeline: raw NewsItem → PipelineItem → full pipeline.

        Scheduler just collects + notifies. Pipeline handles everything:
        Ingest (dedup+DB+vector) → Screen → Evaluate → Dispatch → Deep.
        """
        from pipeline.item import PipelineItem

        pipe_items = []
        for news in items:
            pi = PipelineItem(
                id=0,  # Not yet in DB — IngestStage assigns id
                title=news.title,
                source=news.source,
                url=news.url,
                snippet=getattr(news, 'content_snippet', '') or '',
                published_at=str(getattr(news, 'published_at', '')),
                tickers_found=getattr(news, 'tickers_found', '') or '',
                macro_tags=getattr(news, 'macro_tags', '') or '',
                _raw={
                    'title': news.title, 'source': news.source,
                    'url': news.url,
                    'content_snippet': getattr(news, 'content_snippet', ''),
                    'tickers_found': getattr(news, 'tickers_found', ''),
                    'macro_tags': getattr(news, 'macro_tags', ''),
                    'is_breaking': getattr(news, 'is_breaking', False),
                },
            )
            pipe_items.append(pi)

        if pipe_items:
            try:
                pipe_items = await self._pipeline.run(pipe_items)
            except Exception:
                logger.exception("Pipeline: top-level failure")
                pipe_items = []

        # ---- Background: persist enriched fields + web broadcast ----
        for item in pipe_items:
            try:
                # Persist SCREEN fields back to DB
                self.db.update_news_status(
                    item.id,
                    'fast_pushed',
                    tickers_found=item.tickers_found,
                    macro_tags=item.macro_tags,
                    is_breaking=int(item.is_breaking),
                    priority_score=item.priority_score,
                )
                # Web SSE broadcast
                if self.web_dashboard and item.decision.alert_level != AlertLevel.NORMAL:
                    updated = self.db.get_news_by_id(item.id)
                    if updated:
                        await self.web_dashboard.broadcast_alert(updated)
            except Exception:
                logger.exception("Pipeline: post-processing failed for id=%d", item.id)

    async def _collect_impact_outcomes(self, window: str):
        """Periodic task: collect market data for pending assessments."""
        try:
            from engine.impact_collector import ImpactCollector
            collector = ImpactCollector()
            count = await collector.collect_pending(self.db, window)
            if count:
                logger.info("ImpactCollector[%s]: %d outcomes collected", window, count)
        except Exception as e:
            logger.error("ImpactCollector[%s] failed: %s", window, e)

    async def _run_collector_loop(self):
        """Run impact collector at 15m/1h/4h intervals.

        Each window fires independently — 15m runs every 15 min, 1h every
        60 min, 4h every 240 min.  Assessments are only collected when their
        created_at is old enough for the target window.
        """
        last_1h = datetime.now()
        last_4h = datetime.now()
        while True:
            await asyncio.sleep(15 * 60)
            await self._collect_impact_outcomes("15m")

            now = datetime.now()
            if (now - last_1h).total_seconds() >= 3600:
                await self._collect_impact_outcomes("1h")
                last_1h = now

            if (now - last_4h).total_seconds() >= 14400:
                await self._collect_impact_outcomes("4h")
                last_4h = now

    async def _run_escalation_loop(self):
        """Periodic event-line escalation sweep (interval from config)."""
        cfg = self.config.load_event_escalation()
        interval = int(cfg.get("sweep_interval_minutes", 5)) * 60
        while True:
            await asyncio.sleep(interval)
            try:
                await self.escalator.sweep()
            except Exception:
                logger.exception("EscalationLoop: sweep failed")

    async def _refresh_stats_loop(self):
        """Refresh the /health DB cache every 60 s.

        Runs DB stats in a background task so Docker HEALTHCHECK never
        blocks on SQLite COUNT queries during pipeline bursts.
        """
        while True:
            await asyncio.sleep(60)
            try:
                await refresh_cached_db_health(self.db)
            except Exception:
                logger.exception("StatsRefresh: health cache update failed")

    async def _run_fund_flow_loop(self):
        """Fund flow collection — two windows per trading day.

        Post-market (~17:00 ET): batches of 20 tickers, 5 min cooldown
            between batches. ~71 tickers = 4 batches × (4 min fetch + 5 min
            wait) ≈ 36 minutes total. Fits well within a 2-hour battery window.

        Pre-market (~08:00 ET): single-pass re-analysis from DB.
        """
        ff_cfg = self.config.load_settings().get("fund_flow", {})
        if not ff_cfg.get("enabled", True):
            logger.info("FundFlowLoop: disabled in config, skipping")
            return
        check_interval = ff_cfg.get("check_interval_minutes", 30) * 60
        batch_cooldown = ff_cfg.get("batch_cooldown_minutes", 5) * 60

        while True:
            await asyncio.sleep(check_interval)
            try:
                window = self.fund_flow_collector.get_pending_window()
                if window is None:
                    continue

                if window == "post":
                    pushed = await self.fund_flow_collector.collect_batch()
                    if pushed:
                        logger.info("FundFlowLoop[post]: %d signals pushed", pushed)
                    else:
                        # Not done yet — more batches to go, shorten the wait
                        logger.debug("FundFlowLoop[post]: batch done, cooldown %ds",
                                     batch_cooldown)
                        await asyncio.sleep(batch_cooldown)
                elif window == "pre":
                    pushed = await self.fund_flow_collector.analyze_stored()
                    if pushed:
                        logger.info("FundFlowLoop[pre]: %d signals pushed", pushed)
            except Exception:
                logger.exception("FundFlowLoop: failed")

    async def _run_snapshot_loop(self):
        """Time-window loop: pre-market snapshot + intraday snapshot + sector rotation.

        Pre-market  09:25 ET — full scan, push movers >±2% to TG + Pushover extreme
        Intraday    14:30 ET — re-scan, push extreme >±5%+volume to Pushover phone
        Post-market 16:30 ET — sector rotation ranking, push to TG
        """
        while True:
            await asyncio.sleep(120)  # check every 2 minutes
            try:
                # ECS server is Asia/Shanghai (UTC+8); convert to US Eastern
                now_utc = datetime.now(timezone.utc)
                now_et = now_utc.astimezone(timezone(timedelta(hours=-5)))
                # EDT is UTC-4, EST is UTC-5; using -5 for safety (wider window)
                hour, minute = now_et.hour, now_et.minute
                weekday = now_et.weekday()  # 0=Mon, 6=Sun
                if weekday >= 5:
                    continue  # skip weekends

                # Pre-market window: 09:25-09:35 ET
                if hour == 9 and 25 <= minute <= 35:
                    summary = await self.snapshot_collector.pre_market_snapshot()
                    if summary and summary.movers:
                        msg = MarketSnapshotCollector.format_pre_market_summary(summary)
                        if self.bot and self.bot._app:
                            for cid in self.bot._get_chat_ids():
                                try:
                                    await self.bot._app.bot.send_message(
                                        chat_id=cid, text=msg,
                                        disable_notification=False,
                                    )
                                except Exception:
                                    pass
                        if summary.extreme and self.alert_dispatcher:
                            extreme_msg = MarketSnapshotCollector.format_pre_market_summary(summary)
                            await self.alert_dispatcher.send_system_alert(
                                title="⚡ 盘前极端异动", message=extreme_msg,
                            )
                        logger.info("Window[pre]: %d movers pushed", len(summary.movers))

                # Intraday window: 14:30-14:40 ET
                if hour == 14 and 30 <= minute <= 40:
                    summary = await self.snapshot_collector.intraday_snapshot()
                    if summary and summary.extreme:
                        msg = MarketSnapshotCollector.format_intraday_alert(summary)
                        if self.bot and self.bot._app:
                            for cid in self.bot._get_chat_ids():
                                try:
                                    await self.bot._app.bot.send_message(
                                        chat_id=cid, text=msg,
                                        disable_notification=False,
                                    )
                                except Exception:
                                    pass
                        if self.alert_dispatcher:
                            await self.alert_dispatcher.send_system_alert(
                                title="⚡ 盘中极端异动", message=msg,
                            )
                        logger.info("Window[intra]: %d extreme pushed", len(summary.extreme))

                # Sector rotation: 16:30-16:40 ET (post-market)
                if hour == 16 and 30 <= minute <= 40:
                    s_summary = await self.sector_collector.collect_post_market()
                    if s_summary and s_summary.top5:
                        msg = SectorRotationCollector.format_summary(s_summary)
                        if self.bot and self.bot._app:
                            for cid in self.bot._get_chat_ids():
                                try:
                                    await self.bot._app.bot.send_message(
                                        chat_id=cid, text=msg,
                                        disable_notification=True,  # silent
                                    )
                                except Exception:
                                    pass
                        logger.info("Window[sector]: %d plates pushed", len(s_summary.top5))

            except Exception:
                logger.exception("WindowLoop: failed")

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def start(self) -> None:
        logger.info("News Monitor starting ...")

        # Wire the callback that the scheduler invokes on new items.
        self.scheduler.on_news_batch(self.on_news_batch)

        # Start the Telegram bot (polling mode).
        if self.bot:
            try:
                await self.bot.start()
            except Exception as e:
                logger.warning("Telegram bot failed to start (%s) — continuing without bot", e)
                self.bot = None

        # Start the collection scheduler.
        await self.scheduler.start()

        # Start the web dashboard (if enabled).
        if self.web_dashboard:
            await self.web_dashboard.start()

        # Prime /health cache immediately so there is no 60s "fake-ok" window.
        await refresh_cached_db_health(self.db)

        # Start impact collector loop (background, periodic)
        self._collector_task = asyncio.create_task(self._run_collector_loop())
        self._escalator_task = asyncio.create_task(self._run_escalation_loop())
        self._fund_flow_task = asyncio.create_task(self._run_fund_flow_loop())
        self._snapshot_task = asyncio.create_task(self._run_snapshot_loop())

        # Start the independent liveness watchdog.
        self._watchdog_task = asyncio.create_task(self.watchdog.run_loop())

        # Keep the /health DB cache fresh without blocking Docker HEALTHCHECK
        # on SQLite COUNT queries during pipeline bursts.
        self._stats_refresh_task = asyncio.create_task(self._refresh_stats_loop())

        logger.info("News Monitor running")

    async def stop(self) -> None:
        logger.info("News Monitor stopping ...")
        await self.scheduler.stop()
        if hasattr(self, '_collector_task'):
            self._collector_task.cancel()
        if hasattr(self, '_escalator_task'):
            self._escalator_task.cancel()
        if hasattr(self, '_watchdog_task'):
            self.watchdog.stop()
            self._watchdog_task.cancel()
        if hasattr(self, '_stats_refresh_task'):
            self._stats_refresh_task.cancel()
        if hasattr(self, '_fund_flow_task'):
            self._fund_flow_task.cancel()
            await self.fund_flow_collector.close()
        if self.web_dashboard:
            await self.web_dashboard.stop()
        if self.bot:
            await self.bot.stop()


# ===================================================================
# Entry point
# ===================================================================


async def main() -> None:
    monitor = NewsMonitor()
    try:
        await monitor.start()
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received (KeyboardInterrupt)")
    finally:
        await monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())
