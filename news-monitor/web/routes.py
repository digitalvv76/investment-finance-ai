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


def _get_watchdog(request: web.Request):
    return request.app.get("watchdog")


def _watchdog_snapshot(wd) -> Dict[str, Any]:
    """Build a serializable status snapshot from the watchdog.

    Falls back to a live gather+evaluate if no check has run yet, so the
    page always reflects current truth even right after startup.
    """
    if wd is None:
        return {"available": False, "state": "unknown", "reason": "watchdog 未启用"}

    from engine.watchdog import evaluate_health

    verdict = wd.last_verdict
    signals = wd.last_signals
    try:
        if verdict is None or signals is None:
            signals = wd.gather_signals()
            verdict = evaluate_health(signals)
    except Exception as e:  # never let the health page itself crash
        return {"available": True, "state": "error", "reason": f"快照失败: {e}"}

    alert_states = {"stalled", "degraded"}
    return {
        "available": True,
        "state": verdict.state.value,
        "ok": verdict.state.value not in alert_states,
        "reason": verdict.reason,
        "should_alert": verdict.should_alert,
        "emergency": verdict.emergency,
        "signals": {
            "ingest_1h": signals.ingest_1h,
            "ingest_floor": signals.ingest_floor,
            "hours_since_last_push": signals.hours_since_last_push,
            "error_events_1h": signals.error_events_1h,
            "success_rate": signals.success_rate,
            "assessments_1h": signals.assessments_1h,
        },
        "last_check_at": wd.last_check_at,
    }


async def watchdog_status(request: web.Request) -> web.Response:
    """Detailed watchdog JSON — the silence-disambiguation verdict + signals."""
    return _json(_watchdog_snapshot(_get_watchdog(request)))


async def watchdog_page(request: web.Request) -> web.Response:
    """Human-viewable ops health page (unauthenticated via /health prefix).

    Auto-refreshes so the operator can eyeball whether silence is benign
    (market quiet) or a real fault, without digging into logs.
    """
    snap = _watchdog_snapshot(_get_watchdog(request))
    state = snap.get("state", "unknown")
    palette = {
        "healthy": ("#0a7c2f", "✅", "系统健康"),
        "quiet_ok": ("#0a6b7c", "😴", "市场平静（非故障）"),
        "stalled": ("#b00020", "🔴", "采集停摆 — 疑似故障"),
        "degraded": ("#c25e00", "🟠", "处理降级 — 需检查"),
        "unknown": ("#555", "❔", "未知"),
        "error": ("#b00020", "⚠️", "快照错误"),
    }
    color, icon, label = palette.get(state, palette["unknown"])
    sig = snap.get("signals", {}) or {}
    rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in {
            "近1h采集条数": sig.get("ingest_1h", "—"),
            "采集下限(基准)": sig.get("ingest_floor", "—"),
            "距上次推送(小时)": sig.get("hours_since_last_push", "—"),
            "近1h错误数": sig.get("error_events_1h", "—"),
            "处理成功率(%)": sig.get("success_rate", "—"),
            "近1h评估数": sig.get("assessments_1h", "—"),
            "上次体检时间": snap.get("last_check_at", "—"),
        }.items()
    )
    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>新闻监控 · 系统健康</title>
<meta http-equiv="refresh" content="30">
<style>
 body{{font-family:-apple-system,system-ui,sans-serif;background:#f5f6f8;margin:0;padding:24px;color:#1a1a1a}}
 .card{{max-width:560px;margin:0 auto;background:#fff;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.08);overflow:hidden}}
 .banner{{background:{color};color:#fff;padding:28px 24px}}
 .banner .icon{{font-size:44px}}
 .banner h1{{margin:8px 0 4px;font-size:22px}}
 .banner p{{margin:0;opacity:.92;font-size:15px;line-height:1.5}}
 table{{width:100%;border-collapse:collapse}}
 td{{padding:12px 24px;border-top:1px solid #eee;font-size:14px}}
 td:first-child{{color:#666}} td:last-child{{text-align:right;font-weight:600}}
 .foot{{padding:14px 24px;color:#999;font-size:12px;text-align:center}}
</style></head><body>
<div class="card" data-state="{state}">
  <div class="banner">
    <div class="icon">{icon}</div>
    <h1 id="state-label">{label}</h1>
    <p id="reason">{snap.get('reason','')}</p>
  </div>
  <table><tbody>{rows}</tbody></table>
  <div class="foot">每 30 秒自动刷新 · state={state}</div>
</div>
</body></html>"""
    return web.Response(text=html, content_type="text/html")


# ---------------------------------------------------------------------------
# Health check (no auth required — for monitoring probes)
# ---------------------------------------------------------------------------


async def health_check(request: web.Request) -> web.Response:
    """Lightweight health check, excluded from auth.

    Returns HTTP 200 with status/uptime/DB info.  Uptime monitors and
    Docker HEALTHCHECK can hit this endpoint without credentials.
    """
    db = _get_db(request)
    try:
        db.get_db_stats()
        db_ok = True
    except Exception:
        db_ok = False

    return _json({
        "status": "ok" if db_ok else "degraded",
        "uptime_seconds": int(time.time() - _APP_START_TIME),
        "db": "ok" if db_ok else "error",
        "sse_clients": _get_sse(request).client_count,
        "watchdog": _watchdog_snapshot(_get_watchdog(request)),
    })


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


async def impact_health_events(request: web.Request) -> web.Response:
    db = _get_db(request)
    limit = int(request.query.get("limit", 20))
    events = db.get_health_events(limit=limit)
    return _json(events)


# ---------------------------------------------------------------------------
# Deep analysis endpoint — triggered by Pushover HTML link
# ---------------------------------------------------------------------------

_DEEP_ANALYSIS_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>深度分析</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 12px; line-height: 1.6;
         min-height: 100vh; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px;
           padding: 16px; max-width: 720px; margin: 0 auto; }}
  h1 {{ font-size: 1.1em; color: #58a6ff; margin-bottom: 10px; word-break: break-word; }}
  .meta {{ color: #8b949e; font-size: 0.8em; margin-bottom: 14px; display: flex; flex-wrap: wrap; gap: 8px; }}
  .analysis {{ white-space: pre-wrap; background: #0d1117; border-left: 3px solid #58a6ff;
               padding: 12px 14px; border-radius: 4px; font-size: 0.9em; }}
  .loading {{ text-align: center; padding: 48px 20px; color: #8b949e; }}
  .loading .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%;
                  background: #58a6ff; margin: 0 4px; animation: bounce 1.4s infinite ease-in-out; }}
  .loading .dot:nth-child(2) {{ animation-delay: 0.2s; }}
  .loading .dot:nth-child(3) {{ animation-delay: 0.4s; }}
  @keyframes bounce {{ 0%, 80%, 100% {{ transform: scale(0); }} 40% {{ transform: scale(1); }} }}
  .error {{ color: #f85149; background: #1f1519; padding: 12px; border-radius: 6px; font-size: 0.9em; }}
  .links {{ margin-top: 14px; display: flex; gap: 12px; flex-wrap: wrap; }}
  .links a {{ color: #58a6ff; text-decoration: none; font-size: 0.85em; padding: 6px 12px;
              background: #21262d; border-radius: 6px; border: 1px solid #30363d; }}
  .links a:hover {{ background: #30363d; }}
</style>
</head>
<body>
<div class="card">
  <h1>🔍 {title}</h1>
  <div class="meta">
    <span>📰 {source}</span>
    <span>🏷️ {tickers}</span>
  </div>
  <div id="result"><div class="loading">正在深度分析<div style="margin-top:12px"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div></div></div>
  <div class="links">{original_link}</div>
</div>
<script>
  const newsId = {news_id};
  const pollInterval = 2000;
  const maxPolls = 60;
  let polls = 0;

  async function check() {{
    polls++;
    try {{
      const resp = await fetch('/api/news/' + newsId + '/analyze/result');
      if (!resp.ok) throw new Error('not ready');
      const data = await resp.json();
      if (data.analysis) {{
        document.getElementById('result').innerHTML =
          '<div class="analysis">' + escapeHtml(data.analysis) + '</div>';
        return;
      }}
    }} catch(e) {{}}
    if (polls < maxPolls) setTimeout(check, pollInterval);
    else document.getElementById('result').innerHTML =
      '<div class="error">分析超时，请稍后重试</div>';
  }}

  function escapeHtml(text) {{
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }}

  // Kick off analysis on the server side
  fetch('/api/news/' + newsId + '/analyze/start', {{ method: 'POST' }})
    .catch(() => {{}});

  setTimeout(check, 1500);
</script>
</body>
</html>"""


async def deep_analysis_handler(request: web.Request) -> web.Response:
    """Return the deep analysis HTML page (loading state + JS polling).

    GET /api/news/{id}/analyze
    """
    news_id = int(request.match_info["id"])
    db = _get_db(request)
    news_dict = db.get_news_by_id(news_id)

    if not news_dict:
        return web.Response(
            text="<html><body style='color:#f85149;background:#0d1117;padding:20px;font-family:sans-serif'><h2>News not found</h2></body></html>",
            content_type="text/html", status=404,
        )

    html = _DEEP_ANALYSIS_HTML.format(
        news_id=news_id,
        title=news_dict.get("title", "(no title)")[:120],
        source=news_dict.get("source", "unknown"),
        tickers=news_dict.get("tickers_found", "") or "—",
        original_link=_format_original_link(news_dict),
    )
    return web.Response(text=html, content_type="text/html")


async def deep_analysis_start(request: web.Request) -> web.Response:
    """Trigger deep analysis asynchronously.  Called via JS fetch from the loading page.

    POST /api/news/{id}/analyze/start
    """
    news_id = int(request.match_info["id"])
    db = _get_db(request)
    deep_lane = request.app.get("deep_lane")

    news_dict = db.get_news_by_id(news_id)
    if not news_dict or not deep_lane:
        return _json({"ok": False}, status=404)

    # Don't re-run if already done
    if news_dict.get("llm_analysis"):
        return _json({"ok": True, "cached": True})

    # Fire and forget — result is persisted to DB, polled by /result endpoint
    asyncio.ensure_future(_run_and_persist(deep_lane, news_dict, db))
    return _json({"ok": True})


async def deep_analysis_result(request: web.Request) -> web.Response:
    """Poll for the analysis result.  Returns JSON.

    GET /api/news/{id}/analyze/result
    """
    news_id = int(request.match_info["id"])
    db = _get_db(request)
    news_dict = db.get_news_by_id(news_id)

    if not news_dict:
        return _json({"analysis": None, "error": "not found"}, status=404)

    analysis = news_dict.get("llm_analysis", "")
    if analysis:
        return _json({"analysis": analysis, "done": True})
    return _json({"analysis": None, "done": False}, status=202)


async def _run_and_persist(deep_lane, news_dict: dict, db) -> None:
    """Run deep analysis in background, persist to DB."""
    try:
        from storage.models import NewsItem
        item = _newsitem_from_dict(news_dict)
        result = await asyncio.wait_for(
            deep_lane.process_on_demand(item),
            timeout=60.0,
        )
        if result.llm_analysis:
            db.update_news_status(
                result.id or news_dict["id"], news_dict.get("status", "deep_pushed"),
                llm_analysis=result.llm_analysis,
            )
    except asyncio.TimeoutError:
        logger.error("Deep analysis timed out for news #%s", news_dict.get("id"))
    except Exception as e:
        logger.error("Deep analysis failed for news #%s: %s", news_dict.get("id"), e)


def _format_original_link(news_dict: dict) -> str:
    url = news_dict.get("url", "")
    if url:
        return f'<a class="back" href="{url}" target="_blank">📎 查看原文 →</a>'
    return ""


def _newsitem_from_dict(d: dict):
    """Build a NewsItem from a DB row dict."""
    from storage.models import NewsItem
    return NewsItem(
        id=d.get("id", 0),
        title=d.get("title", ""),
        source=d.get("source", ""),
        url=d.get("url", ""),
        content_snippet=d.get("content_snippet", ""),
        tickers_found=d.get("tickers_found", ""),
        macro_tags=d.get("macro_tags", ""),
        sentiment=d.get("sentiment", ""),
        sentiment_score=d.get("sentiment_score", 0.0),
        priority_score=d.get("priority_score", 0.0),
        entities=d.get("entities", ""),
        status=d.get("status", ""),
    )
