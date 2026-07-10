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
from engine.event_driven_evaluator import EventDrivenEvaluator, watchlist_safety_net
from engine.watchdog import Watchdog
from engine.impact_learner import ImpactLearner
from engine.event_matcher import EventMatcher
from engine.relevance import signal_score, get_portfolio_summary, get_tracked_tickers
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

        # ---- impact evaluator (LLM, async, isolated) --------
        # Event-driven sentinel is now the PRIMARY evaluator (structured
        # catalyst detection + intensity). The old free-form ImpactEvaluator
        # and its learner/matcher are kept instantiated but dormant (no longer
        # drives push decisions) for backward compat + dashboard history.
        self.event_evaluator = EventDrivenEvaluator()
        self.impact_evaluator = ImpactEvaluator()
        self.impact_learner = ImpactLearner()
        self.event_matcher = EventMatcher()
        self.actionability_reviewer = ActionabilityReviewer()
        logger.info("EventDrivenEvaluator initialized (PRIMARY); ImpactEvaluator dormant (event_matcher=%d events)",
                    self.event_matcher.event_count)
        logger.info("Portfolio/Relevance: %s", get_portfolio_summary())

        # ---- liveness watchdog (independent task; disambiguates "silence") ----
        # Runs on its OWN asyncio task (see start()), NOT inside the scheduler —
        # if the scheduler loop hangs, a watchdog living inside it would hang too.
        self.watchdog = Watchdog(self.db, self.alert_dispatcher, self.config.load_settings())

        # ---- Telegram bot -------------------------------------------
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN not set -- bot disabled")
            self.bot = None
        else:
            self.bot = NewsBot(token, self.db, self.config, self.deep_lane, self.learner, self.curator, self.trainer)

        # ---- event clustering + escalation (NEW V1) -------------------
        from engine.cluster import NewsCluster
        from engine.market_snapshot import MarketSnapshot
        from engine.event_escalator import EventEscalator

        self.cluster = NewsCluster(self.db, vector_store=self.vector_store)
        self.market_snapshot = MarketSnapshot()
        self.escalator = EventEscalator(
            self.db, self.alert_dispatcher, self.market_snapshot, self.config,
            telegram_push_provider=lambda: (
                self.alert_dispatcher.wrap_telegram_push(self.bot) if self.bot else None
            ),
        )

        # Inject into scheduler (created earlier)
        self.scheduler.cluster = self.cluster
        self.scheduler.escalator = self.escalator

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
            # Expose watchdog for /health/watchdog(.json)
            self.web_dashboard.watchdog = self.watchdog
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

        for idx, item in enumerate(pushed):
            # Yield every 5 items to keep web server responsive
            if idx % 5 == 0:
                await asyncio.sleep(0)

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

            # ---- Event-driven evaluation (PRIMARY) — runs on ALL screened items ----
            # No prescreen gate: the event prompt's Step-1 relevance filter is the
            # real gatekeeper. priority_score no longer decides whether the LLM runs.
            event_assessment = None
            impact_assessment = None
            if self.event_evaluator:
                async with _llm_sem:
                    try:
                        event_assessment = await self.event_evaluator.evaluate(item)
                    except Exception as e:
                        logger.error("EventDrivenEval failed for news#%s: %s", item.id, e)
                if event_assessment is not None:
                    impact_assessment = self._event_to_assessment(event_assessment, item)
                    impact_assessment.news_id = item.id
                    try:
                        self.db.insert_assessment(impact_assessment)
                    except Exception as e:
                        logger.error("insert_assessment failed for #%s: %s", item.id, e)

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

            # ---- Push decision ----
            has_tickers = bool(item.tickers_found and item.tickers_found.strip())
            is_macro = bool(item.macro_tags and item.macro_tags.strip())
            if event_assessment is not None:
                # Deterministic event rule: is_event && intensity>=3 → push.
                # Bypasses watchlist/timeliness gates by design — catalysts on
                # untracked small-caps are exactly the target of this model.
                if event_assessment.should_push:
                    level = (AlertLevel.CRITICAL if event_assessment.alert_level == "critical"
                             else AlertLevel.IMPORTANT)
                    reason = (f"event_driven intensity={event_assessment.intensity} "
                              f"types={event_assessment.event_types}")
                else:
                    level = AlertLevel.NORMAL
                    reason = ("event_driven no_push: "
                              + (event_assessment.filter_reason
                                 or f"intensity={event_assessment.intensity}"))
            else:
                # Fallback path (no LLM provider available): legacy classify.
                level, reason = self.alert_dispatcher.classify(
                    item.priority_score, strategic_matches,
                    rel_mult=rel_mult,
                    has_tickers=has_tickers,
                    is_macro=is_macro,
                    timeliness=sig.get("timeliness"),
                )

            # ---- Inject assessment fields for push formatters ----
            analyst_note = ""
            flash_note = ""
            event_category = ""
            impact_score = 0
            confidence = 0
            urgency = ""
            sentiment = ""
            greed_index = 50
            key_points = "[]"
            risk_flags = "[]"
            if impact_assessment:
                analyst_note = getattr(impact_assessment, 'analyst_note', '') or ''
                flash_note = getattr(impact_assessment, 'flash_note', '') or ''
                event_category = getattr(impact_assessment, 'event_category', '') or ''
                impact_score = int(getattr(impact_assessment, 'impact_score', 0) or 0)
                confidence = int(getattr(impact_assessment, 'confidence', 0) or 0)
                urgency = getattr(impact_assessment, 'urgency', '') or ''
                sentiment = getattr(impact_assessment, 'sentiment', '') or ''
                greed_index = int(getattr(impact_assessment, 'greed_index', 50) or 50)
                key_points = getattr(impact_assessment, 'key_points', '[]') or '[]'
                risk_flags = getattr(impact_assessment, 'risk_flags', '[]') or '[]'
                # Surface catalyst tickers the LLM found even if FastLane missed them
                if event_assessment and event_assessment.ticker_hint:
                    merged = set(filter(None, (updated.get('tickers_found') or '').split(',')))
                    merged.update(event_assessment.ticker_hint)
                    updated['tickers_found'] = ','.join(sorted(merged))
                updated['analyst_note'] = analyst_note
                updated['_analyst_note'] = analyst_note  # for alert_dispatcher
                updated['_flash_note'] = flash_note
                updated['_event_category'] = event_category
                updated['_impact_score'] = impact_score
                updated['_confidence'] = confidence
                updated['_urgency'] = urgency
                updated['_sentiment'] = sentiment
                updated['_greed_index'] = greed_index
                updated['_key_points'] = key_points
                updated['_risk_flags'] = risk_flags

            # ---- Alert dispatching (phone kept strict; Telegram widened) ----
            #   intensity >= 3   → Pushover(phone) + Telegram   (CRITICAL/IMPORTANT)
            #   is_event, 1-2    → Telegram silent only          (weak catalyst)
            #   is_event = false → no push (stored + dashboard only)
            # dispatch() routes phone vs silent-TG by the adapter urgency
            # (FLASH/ALERT → phone+TG; WATCH/INFO → NORMAL → silent TG).
            weak_catalyst = bool(
                event_assessment is not None
                and event_assessment.is_event
                and not event_assessment.should_push
            )
            # Watchlist/portfolio safety net: non-event news, but the sentinel
            # flagged a substantive action (notable) on a name the user tracks.
            # Silent Telegram only — phone stays strict (never fires here).
            wl_safety_net = watchlist_safety_net(event_assessment, get_tracked_tickers())
            if wl_safety_net:
                reason = ("watchlist_safety_net: notable action on "
                          + ",".join(event_assessment.ticker_hint))
                logger.info("Watchlist safety net → silent TG: %s — %s",
                            ",".join(event_assessment.ticker_hint),
                            (item.title or "")[:60])
            if level in (AlertLevel.CRITICAL, AlertLevel.IMPORTANT) or weak_catalyst or wl_safety_net:
                tg_push = self.alert_dispatcher.wrap_telegram_push(self.bot)
                result = await self.alert_dispatcher.dispatch(
                    item=updated,
                    priority_score=item.priority_score,
                    strategic_matches=strategic_matches,
                    telegram_push_fn=tg_push,
                    timeliness=None,  # event rule already decided; don't re-gate on timeliness
                    impact_assessment=impact_assessment,
                )
                logger.info(
                    "Alert dispatched: level=%s channels=%s reason=%s",
                    result.level.value, result.channels_used, result.reason,
                )
            else:
                logger.info("No push #%s (%s) — %s", item.id, reason, (item.title or "")[:60])

            # ---- Web dashboard broadcast (SSE real-time push) ---------
            if self.web_dashboard:
                await self.web_dashboard.broadcast_alert(updated)

            # Trigger deep lane for pushed events (async, don't block)
            if (event_assessment and event_assessment.should_push) or item.priority_score >= 0.7:
                asyncio.create_task(self._run_deep_lane(item))

    @staticmethod
    def _event_to_assessment(ea, item):
        """Adapt an EventAssessment into an ImpactAssessment for DB storage,
        push formatters, and the dashboard — no schema migration required.

        Mapping: intensity(1-5) → impact_score(×20) + urgency; headline_signal
        → flash_note; risk_snapshot → risk_flags; sector_tags/ticker_hint/
        event_types → key_points (Chinese display).
        """
        import json
        from storage.models import ImpactAssessment

        if ea.intensity >= 5:
            urgency = "FLASH"
        elif ea.intensity >= 3:
            urgency = "ALERT"
        elif ea.is_event:
            urgency = "WATCH"
        else:
            urgency = "INFO"

        if ea.is_event:
            event_category = "catalyst:" + ",".join(str(t) for t in ea.event_types)
            kp = []
            if ea.sector_tags:
                kp.append("板块: " + ", ".join(ea.sector_tags))
            if ea.ticker_hint:
                kp.append("关联代码: " + ", ".join(ea.ticker_hint))
            kp.append(f"强度: {'★' * ea.intensity} ({ea.intensity}/5)")
            if ea.event_types:
                kp.append("催化剂类型: " + ",".join(str(t) for t in ea.event_types))
            key_points = json.dumps(kp, ensure_ascii=False)
            risk_flags = json.dumps([ea.risk_snapshot] if ea.risk_snapshot else [], ensure_ascii=False)
        else:
            event_category = "filtered"
            key_points = "[]"
            risk_flags = "[]"

        return ImpactAssessment(
            impact_score=float(ea.intensity * 20),
            confidence=80.0,
            event_category=event_category,
            surprise_level="",
            breadth="",
            urgency=urgency,
            sentiment="BULLISH" if ea.is_event else "",
            greed_index=50,
            reasoning_chain=json.dumps([ea.filter_reason] if ea.filter_reason else [], ensure_ascii=False),
            similar_events="[]",
            expected_moves=json.dumps(
                {"sector_tags": ea.sector_tags, "ticker_hint": ea.ticker_hint}, ensure_ascii=False
            ),
            calibration_note="",
            flash_note=ea.headline_signal,
            analyst_note=ea.headline_signal,
            key_points=key_points,
            risk_flags=risk_flags,
            prompt_version="event_driven",
            latency_ms=0,
        )

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

        # Start liveness watchdog on its own independent task
        self._watchdog_task = asyncio.create_task(self.watchdog.run_loop())

        logger.info("News Monitor running")

    async def stop(self) -> None:
        logger.info("News Monitor stopping ...")
        await self.scheduler.stop()
        if hasattr(self, '_collector_task'):
            self._collector_task.cancel()
        if hasattr(self, '_watchdog_task'):
            self.watchdog.stop()
            self._watchdog_task.cancel()
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
