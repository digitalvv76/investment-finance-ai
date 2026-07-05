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
from datetime import datetime
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
from engine.impact_learner import ImpactLearner
from engine.event_matcher import EventMatcher
from engine.relevance import signal_score, get_portfolio_summary
from engine.actionability_review import ActionabilityReviewer
from bot.telegram_bot import NewsBot

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

        # ---- impact evaluator (LLM, async, isolated) --------
        self.impact_evaluator = ImpactEvaluator()
        self.impact_learner = ImpactLearner()
        self.event_matcher = EventMatcher()
        self.actionability_reviewer = ActionabilityReviewer()
        logger.info("ImpactEvaluator initialized (threshold=%.2f, event_matcher=%d events)",
                    ImpactEvaluator.THRESHOLD, self.event_matcher.event_count)
        logger.info("Portfolio/Relevance: %s", get_portfolio_summary())

        # ---- Telegram bot -------------------------------------------
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN not set -- bot disabled")
            self.bot = None
        else:
            self.bot = NewsBot(token, self.db, self.config, self.deep_lane, self.learner, self.curator, self.trainer)

        # ---- web dashboard (optional) --------------------------------
        web_port = int(os.environ.get("WEB_PORT", "0"))
        if web_port > 0:
            from web.server import WebDashboard
            self.web_dashboard = WebDashboard(
                db=self.db, curator=self.curator, trainer=self.trainer,
                learner=self.learner, deep_lane=self.deep_lane, port=web_port,
            )
            # Make evaluator available for /api/impact/health endpoint
            self.web_dashboard.impact_evaluator = self.impact_evaluator
            logger.info("Web dashboard enabled on port %d", web_port)
        else:
            self.web_dashboard = None

    # -----------------------------------------------------------------
    # Callback - wired to scheduler.on_news_batch
    # -----------------------------------------------------------------

    async def on_news_batch(self, items):
        """Called by the scheduler whenever a batch of new items arrives.

        NEW PIPELINE (impact-first):
        1. FastLane pre-screening (cheap, fast).
        2. ImpactEvaluator LLM runs BEFORE push decision (not after).
        3. Composite impact score decides push level.
        4. Fallback to legacy PriorityScorer if ImpactEvaluator fails/times out.
        5. Deep lane triggered asynchronously for high-impact items.
        """
        pushed = self.fast_lane.process(items)

        # Limit concurrent LLM calls so we don't hammer the API.
        _settings = self.config.load_settings()
        _impact_cfg = _settings.get("impact_push", {})
        _llm_sem = asyncio.Semaphore(
            _impact_cfg.get("max_concurrent_llm", 3)
        )

        for item in pushed:
            # Persist the enriched fields from fast-lane processing.
            self.db.update_news_status(
                item.id,
                item.status,
                tickers_found=item.tickers_found,
                macro_tags=item.macro_tags,
                is_breaking=int(item.is_breaking),
                priority_score=item.priority_score,
            )

            # Build item dict for downstream consumers
            updated = self.db.get_news_by_id(item.id)
            if not updated:
                continue

            # ---- Strategic detection (cheap: regex only) ----
            text = f"{item.title or ''} {item.content_snippet or ''}"
            strategic_matches = []
            if item.priority_score >= 0.7 or 'STRATEGIC_' in (item.macro_tags or ''):
                strategic_matches = self._strategic.detect(text)

            # ---- NEW: ImpactEvaluator BEFORE push decision ----
            impact_assessment = None
            prescreen = _impact_cfg.get("prescreen_threshold", 0.30)
            if item.priority_score >= prescreen and self.impact_evaluator:
                async with _llm_sem:
                    try:
                        calibration_hint = self.impact_learner.generate_calibration_hint(self.db)
                        historical = self.event_matcher.get_examples(
                            text, event_category="", top_k=3,
                        )
                        impact_assessment = await self.impact_evaluator.evaluate(
                            item,
                            market_context="",
                            calibration_hint=calibration_hint,
                            historical_examples=historical,
                        )
                        if impact_assessment:
                            impact_assessment.news_id = item.id
                            self.db.insert_assessment(impact_assessment)
                    except asyncio.TimeoutError:
                        logger.warning("ImpactEval timeout for news#%s, using legacy classification", item.id)
                    except Exception as e:
                        logger.error("ImpactEval failed for news#%s: %s, falling back to legacy", item.id, e)

            # ---- 4-dimension signal score ----
            sig = signal_score(
                news_tickers=item.tickers_found or "",
                news_text=text,
                macro_tags=item.macro_tags or "",
                strategic_matches=strategic_matches,
                is_breaking=bool(item.is_breaking),
                published_at=getattr(item, 'published_at', None),
            )
            rel_mult = sig["composite"]
            logger.debug(
                "Signal: composite=%.3f (timeliness=%.2f novelty=%.2f "
                "relevance=%.2f dir=%s) — %s",
                sig["composite"], sig["timeliness"], sig["novelty"],
                sig["relevance"], sig["relevance_direction"],
                (item.title or "")[:60],
            )

            # ---- Classify alert level (impact-first, legacy fallback) ----
            level, reason = self.alert_dispatcher.classify(
                item.priority_score, strategic_matches,
                impact_assessment=impact_assessment,
                rel_mult=rel_mult,
            )

            # ---- LLM Actionability Review (borderline cases only) ----
            if (self.actionability_reviewer.should_review(rel_mult)
                    and level != AlertLevel.NORMAL):
                review_result = await self.actionability_reviewer.review(
                    item, sig, impact_assessment=impact_assessment,
                )
                if review_result == "NOT_ACTIONABLE":
                    logger.info(
                        "LLM review: downgrading %s -> NORMAL for #%s — %s",
                        level.value, item.id, (item.title or "")[:60],
                    )
                    level = AlertLevel.NORMAL
                    reason = f"llm_review_not_actionable (was: {reason})"

            # ---- Inject analyst note + impact scores for push formatters ----
            analyst_note = ""
            event_category = ""
            impact_score = 0
            confidence = 0
            if impact_assessment:
                analyst_note = getattr(impact_assessment, 'analyst_note', '') or ''
                event_category = getattr(impact_assessment, 'event_category', '') or ''
                impact_score = int(getattr(impact_assessment, 'impact_score', 0) or 0)
                confidence = int(getattr(impact_assessment, 'confidence', 0) or 0)
                updated['analyst_note'] = analyst_note
                updated['_analyst_note'] = analyst_note  # for alert_dispatcher
                updated['_event_category'] = event_category
                updated['_impact_score'] = impact_score
                updated['_confidence'] = confidence

            # ---- Alert dispatching ----
            if level in (AlertLevel.CRITICAL, AlertLevel.IMPORTANT):
                tg_push = self.alert_dispatcher.wrap_telegram_push(self.bot)
                result = await self.alert_dispatcher.dispatch(
                    item=updated,
                    priority_score=item.priority_score,
                    strategic_matches=strategic_matches,
                    telegram_push_fn=tg_push,
                )
                logger.info(
                    "Alert dispatched: level=%s channels=%s reason=%s",
                    result.level.value, result.channels_used, result.reason,
                )
            elif self.bot:
                await self.bot.push_alert(
                    updated, analyst_note=analyst_note,
                    event_category=event_category,
                    impact_score=impact_score,
                    confidence=confidence,
                )

            # ---- Web dashboard broadcast (SSE real-time push) ---------
            if self.web_dashboard:
                await self.web_dashboard.broadcast_alert(updated)

            # Trigger deep lane for high-impact items (async, don't block)
            if (impact_assessment and impact_assessment.impact_score >= 60) or item.priority_score >= 0.7:
                asyncio.create_task(self._run_deep_lane(item))

    async def _run_deep_lane(self, item):
        """Run deep lane analysis as a background task."""
        try:
            updated = self.db.get_news_by_id(item.id)
            if updated:
                from storage.models import NewsItem as NI
                ni = NI(
                    id=updated['id'],
                    title=updated['title'],
                    url=updated['url'],
                    source=updated['source'],
                    content_snippet=updated.get('content_snippet', ''),
                    tickers_found=updated.get('tickers_found', ''),
                    macro_tags=updated.get('macro_tags', ''),
                    is_breaking=bool(updated.get('is_breaking', False)),
                    priority_score=updated.get('priority_score', 0.0),
                    status=updated.get('status', 'pending'),
                )
                result = await self.deep_lane.process(ni)
                if self.bot and result.llm_analysis:
                    await self.bot.push_deep_analysis(updated)
        except Exception as e:
            logger.error(f"Deep lane background task failed: {e}")

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

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def start(self) -> None:
        logger.info("News Monitor starting ...")

        # Wire the callback that the scheduler invokes on new items.
        self.scheduler.on_news_batch(self.on_news_batch)

        # Start the Telegram bot (polling mode).
        if self.bot:
            await self.bot.start()

        # Start the collection scheduler.
        await self.scheduler.start()

        # Start the web dashboard (if enabled).
        if self.web_dashboard:
            await self.web_dashboard.start()

        # Start impact collector loop (background, periodic)
        self._collector_task = asyncio.create_task(self._run_collector_loop())

        logger.info("News Monitor running")

    async def stop(self) -> None:
        logger.info("News Monitor stopping ...")
        await self.scheduler.stop()
        if hasattr(self, '_collector_task'):
            self._collector_task.cancel()
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
