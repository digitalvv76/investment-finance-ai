"""REST API + SSE handlers for the News Monitor web dashboard.

Every handler receives the aiohttp ``Request``, pulls subsystem
references from ``request.app``, and returns a JSON response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict

from aiohttp import web

from storage.models import FeedbackRecord

logger = logging.getLogger(__name__)

_APP_START_TIME = time.time()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda o: json.dumps(o, default=str))


def _error(msg: str, status: int = 400) -> web.Response:
    return _json({"error": msg}, status=status)


def _get_db(request: web.Request):
    return request.app["db"]


def _get_curator(request: web.Request):
    return request.app.get("curator")


def _get_trainer(request: web.Request):
    return request.app.get("trainer")


def _get_learner(request: web.Request):
    return request.app.get("learner")


def _get_sse(request: web.Request):
    return request.app["sse_manager"]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


async def get_stats(request: web.Request) -> web.Response:
    db = _get_db(request)
    learner = _get_learner(request)

    stats = db.get_db_stats()
    stats["uptime_seconds"] = int(time.time() - _APP_START_TIME)

    if learner:
        stats["threshold"] = float(db.get_preference("learner_threshold") or 0.30)
        stats["personal_keywords"] = len(learner.get_personal_dict())
    else:
        stats["threshold"] = 0.30
        stats["personal_keywords"] = 0

    stats["sse_clients"] = _get_sse(request).client_count

    return _json(stats)


# ---------------------------------------------------------------------------
# News feed
# ---------------------------------------------------------------------------


async def get_recent_news(request: web.Request) -> web.Response:
    db = _get_db(request)
    hours = int(request.query.get("hours", 24))
    limit = min(int(request.query.get("limit", 50)), 200)
    items = db.get_recent_news(hours=hours, limit=limit)
    return _json({"items": items, "total": len(items)})


async def get_news_by_id(request: web.Request) -> web.Response:
    db = _get_db(request)
    news_id = int(request.match_info["id"])
    item = db.get_news_by_id(news_id)
    if not item:
        return _error("News not found", status=404)
    return _json(item)


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


async def post_feedback(request: web.Request) -> web.Response:
    db = _get_db(request)
    learner = _get_learner(request)

    try:
        body = await request.json()
    except Exception:
        return _error("Invalid JSON body")

    news_id = body.get("news_id")
    reaction = body.get("reaction", "")

    if not news_id or not reaction:
        return _error("news_id and reaction are required")

    valid = {"content_good", "prediction_right", "prediction_wrong", "thumbs_up", "thumbs_down", "analyze_click"}
    if reaction not in valid:
        return _error(f"Invalid reaction. Must be one of: {', '.join(sorted(valid))}")

    fb = FeedbackRecord(news_id=int(news_id), reaction=reaction)
    fid = db.insert_feedback(fb)

    # Trigger adaptation cycle in background
    if learner and reaction in ("content_good", "thumbs_up", "thumbs_down"):
        asyncio.create_task(_run_adaptation(learner))

    return _json({"id": fid, "ok": True})


async def _run_adaptation(learner) -> None:
    try:
        await asyncio.to_thread(learner.run_adaptation_cycle)
        logger.info("Learner adaptation cycle completed")
    except Exception as e:
        logger.error("Learner adaptation failed: %s", e)


# ---------------------------------------------------------------------------
# Curator profile
# ---------------------------------------------------------------------------


async def get_profile(request: web.Request) -> web.Response:
    curator = _get_curator(request)
    if not curator:
        return _error("Curator not available", status=503)
    return _json(curator.get_profile())


async def put_profile(request: web.Request) -> web.Response:
    curator = _get_curator(request)
    if not curator:
        return _error("Curator not available", status=503)

    try:
        body = await request.json()
    except Exception:
        return _error("Invalid JSON body")

    curator.save_profile(body)
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Training documents
# ---------------------------------------------------------------------------


async def get_training_docs(request: web.Request) -> web.Response:
    trainer = _get_trainer(request)
    if not trainer:
        return _error("Trainer not available", status=503)
    docs = trainer.list_docs()
    return _json({"docs": docs})


async def post_training_url(request: web.Request) -> web.Response:
    trainer = _get_trainer(request)
    if not trainer:
        return _error("Trainer not available", status=503)

    try:
        body = await request.json()
    except Exception:
        return _error("Invalid JSON body")

    url = body.get("url", "").strip()
    if not url:
        return _error("url is required")

    title = body.get("title", "").strip()

    # Run in background — URL fetch + LLM summarization can take 10-30s
    async def _ingest():
        try:
            doc_id = await trainer.ingest_url(url, title=title)
            logger.info("Training URL ingested: id=%d url=%s", doc_id, url[:80])
        except Exception as e:
            logger.error("Training URL ingestion failed: %s", e)

    asyncio.create_task(_ingest())
    return _json({"ok": True, "message": "URL ingestion started. Check /api/training for progress."})


async def post_training_text(request: web.Request) -> web.Response:
    trainer = _get_trainer(request)
    if not trainer:
        return _error("Trainer not available", status=503)

    try:
        body = await request.json()
    except Exception:
        return _error("Invalid JSON body")

    text = body.get("text", "").strip()
    if not text:
        return _error("text is required")

    title = body.get("title", "").strip()
    source = body.get("source", "web-dashboard").strip()
    doc_id = trainer.ingest_text(text, title=title, source=source)
    return _json({"id": doc_id, "ok": True})


async def delete_training_doc(request: web.Request) -> web.Response:
    trainer = _get_trainer(request)
    if not trainer:
        return _error("Trainer not available", status=503)

    doc_id = int(request.match_info["id"])
    trainer.delete_doc(doc_id)
    return _json({"ok": True})


async def post_training_file(request: web.Request) -> web.Response:
    """Upload a .docx or .pdf file for training."""
    trainer = _get_trainer(request)
    if not trainer:
        return _error("Trainer not available", status=503)

    # Read multipart form data
    reader = await request.multipart()
    field = await reader.next()
    if not field or field.name != "file":
        return _error("Missing 'file' field in multipart form")

    filename = field.filename or "upload"
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ('docx', 'pdf', 'md', 'txt', 'markdown'):
        return _error(f"Unsupported file type: .{ext}. Use .docx, .pdf, .md, or .txt")

    # Write to temp file
    import tempfile, os as _os
    suffix = f".{ext}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        while True:
            chunk = await field.read_chunk(65536)
            if not chunk:
                break
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        result = await trainer.ingest_file(tmp_path, filename=filename)
        return _json(result)
    except Exception as e:
        logger.error("File ingestion failed: %s", e)
        return _error(f"Ingestion failed: {str(e)}")
    finally:
        try:
            _os.unlink(tmp_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Filters / learner state
# ---------------------------------------------------------------------------


async def get_filters(request: web.Request) -> web.Response:
    db = _get_db(request)
    learner = _get_learner(request)

    import json as _json_mod

    data: Dict[str, Any] = {
        "filter_tickers": _json_mod.loads(db.get_preference("filter_tickers") or "[]"),
        "muted_tickers": _json_mod.loads(db.get_preference("muted_tickers") or "{}"),
        "urgent_keywords": (db.get_preference("urgent_keywords") or "").split(",") if db.get_preference("urgent_keywords") else [],
        "threshold": float(db.get_preference("learner_threshold") or 0.30),
    }

    if learner:
        data["source_weights"] = learner.get_source_weights()
        data["topic_scores"] = learner.get_topic_scores()
        data["personal_keywords"] = learner.get_personal_dict()

    return _json(data)


async def put_filters(request: web.Request) -> web.Response:
    db = _get_db(request)
    learner = _get_learner(request)

    try:
        body = await request.json()
    except Exception:
        return _error("Invalid JSON body")

    import json as _json_mod

    if "filter_tickers" in body:
        db.set_preference("filter_tickers", _json_mod.dumps(body["filter_tickers"]))
    if "muted_tickers" in body:
        db.set_preference("muted_tickers", _json_mod.dumps(body["muted_tickers"]))
    if "urgent_keywords" in body:
        db.set_preference("urgent_keywords", ",".join(body["urgent_keywords"]))
    if "threshold" in body and learner:
        db.set_preference("learner_threshold", str(body["threshold"]))

    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Alert history
# ---------------------------------------------------------------------------


async def get_alert_history(request: web.Request) -> web.Response:
    db = _get_db(request)
    limit = min(int(request.query.get("limit", 50)), 200)

    # Get fast_pushed and deep_pushed items
    fast = db.get_news_by_status("fast_pushed", limit=limit // 2)
    deep = db.get_news_by_status("deep_pushed", limit=limit // 2)

    items = fast + deep
    items.sort(key=lambda x: x.get("captured_at", ""), reverse=True)
    items = items[:limit]

    alerts: list[dict] = []
    for item in items:
        score = item.get("priority_score", 0)
        if score >= 0.9:
            level = "critical"
        elif score >= 0.7:
            level = "important"
        else:
            level = "normal"
        alerts.append({**item, "level": level})

    return _json({"alerts": alerts})


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


async def get_daily_digest(request: web.Request) -> web.Response:
    db = _get_db(request)
    from bot.digest import DigestGenerator
    dg = DigestGenerator(db)
    text = dg.generate(hours=24)
    return _json({"digest": text})


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------


async def sse_events(request: web.Request) -> web.StreamResponse:
    """SSE endpoint — keeps connection open and streams events to the browser."""
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )
    await response.prepare(request)

    sse_mgr = _get_sse(request)
    cid, queue = await sse_mgr.subscribe()

    # Initial heartbeat
    await response.write(b": ok\n\n")

    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=30.0)
                await response.write(message.encode("utf-8"))
            except asyncio.TimeoutError:
                # Keepalive ping
                await response.write(b": ping\n\n")
    except (ConnectionResetError, ConnectionAbortedError, asyncio.CancelledError):
        pass
    finally:
        await sse_mgr.unsubscribe(cid)

    return response


# ---------------------------------------------------------------------------
# Impact Evaluator API
# ---------------------------------------------------------------------------


async def impact_latest(request: web.Request) -> web.Response:
    db = _get_db(request)
    limit = int(request.query.get("limit", 20))
    min_score = float(request.query.get("min_score", 0))
    assessments = db.get_assessments(limit=limit, min_score=min_score)
    return _json(assessments)


async def impact_detail(request: web.Request) -> web.Response:
    db = _get_db(request)
    aid = int(request.match_info["id"])
    a = db.get_assessment(aid)
    if not a:
        return _error("assessment not found", 404)
    outcomes = db.get_outcomes_for_assessment(aid)
    a["outcomes"] = outcomes
    return _json(a)


async def impact_outcomes(request: web.Request) -> web.Response:
    db = _get_db(request)
    aid = int(request.match_info["id"])
    outcomes = db.get_outcomes_for_assessment(aid)
    return _json(outcomes)


async def impact_calibration(request: web.Request) -> web.Response:
    db = _get_db(request)
    cal = db.get_calibration()
    return _json(cal)


async def impact_stats(request: web.Request) -> web.Response:
    db = _get_db(request)
    stats = db.get_impact_stats()
    return _json(stats)


async def impact_health(request: web.Request) -> web.Response:
    db = _get_db(request)
    stats = db.get_health_stats(hours=1)
    # Merge with in-memory health monitor if available
    evaluator = request.app.get("impact_evaluator")
    if evaluator:
        stats.update(evaluator.health.health)
    return _json(stats)


async def impact_prompts(request: web.Request) -> web.Response:
    db = _get_db(request)
    from engine.impact_evaluator import PromptVersionManager
    mae = PromptVersionManager.compare_mae(db)
    return _json({"active": PromptVersionManager.ACTIVE, "versions": mae})
