"""Futu news fetcher — keyword-based news search via Futu OpenD.

Uses get_search_news API to pull Chinese & English financial news from
Futu's news aggregation (富途资讯, MT Newswires, Benzinga, PR Newswire,
金十数据, 证券时报, etc.).

Strategy: search ALL keywords every cycle using concurrent API calls.
Each keyword gets its own OpenQuoteContext connection running in a thread
pool.  Deduplication by title hash prevents cross-keyword duplicates.

v2 (2026-07-21): replaced keyword rotation with full concurrent search.
All keywords searched every 60s instead of rotating 16 per cycle.
English company names added as supplementary keywords.

v2.1 (2026-07-21): keyword→ticker fallback.  When Futu returns an article
with empty related_securities, inject the search keyword's canonical ticker
(like Finnhub does via its symbol= parameter).  Prevents score=0 when
entity extraction misses a Chinese company name.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from storage.models import NewsItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keywords — tickers + English company names + macro/people/theme
# ---------------------------------------------------------------------------
# Each watchlist stock gets BOTH its ticker AND its English company name
# as search keywords.  Ticker catches "KTOS stock surges"; company name
# catches "Kratos wins $156M contract" when the headline doesn't use the
# ticker symbol.  Futu get_search_news is language-agnostic.
_SEARCH_KEYWORDS = [
    # === Watchlist tickers + English company names (dual-keyword) ===
    "AAOI", "ABSI", "ACHR", "Archer Aviation",
    "ALAB", "AMBA",
    "ARKK", "ARKQ", "ARM", "Arm Holdings",
    "ASTS", "AST SpaceMobile",
    "AVAV", "AeroVironment",
    "AVGO", "Broadcom",
    "BABA", "Alibaba",
    "BE", "Bloom Energy",
    "BOT", "BOTZ", "BTBT",
    "BTC", "Bitcoin", "BTCS", "BTDR",
    "BWXT", "BWX Technologies",
    "CBRS", "CLPT", "CRWV", "DTIL",
    "ETH", "Ethereum",
    "FIG", "FUTU",
    "GLD", "GLXY", "Galaxy Digital",
    "GOOGL", "Google",
    "HII", "Huntington Ingalls",
    "HPE", "Hewlett Packard Enterprise",
    "IONQ", "IonQ",
    "IREN", "Iris Energy",
    "KTOS", "Kratos",
    "LEU", "Centrus Energy",
    "LITE", "Lumentum",
    "LRCX", "Lam Research",
    "MP", "MP Materials",
    "MRAAY", "MRVL", "Marvell",
    "MU", "Micron",
    "NBIS", "Nebius",
    "NNE", "Nano Nuclear",
    "NVDA", "Nvidia",
    "NVTS", "Navitas Semiconductor",
    "OKLO", "Oklo",
    "ORCL", "Oracle",
    "PLTR", "Palantir",
    "QQQ", "QQQM",
    "RDW", "Redwire",
    "RGTI", "Rigetti",
    "RKLB", "Rocket Lab",
    "ROBT", "RXRX", "Recursion",
    "SATS", "EchoStar",
    "SERV", "Serve Robotics",
    "SMH", "SMR", "NuScale",
    "SOL", "SOXL", "SOXX",
    "SPCX", "SpaceX",
    "TEM", "Tempus AI",
    "TSLA", "Tesla",
    "TSM", "TSMC", "Taiwan Semiconductor",
    "UPXI", "UUUU", "Energy Fuels",
    "VOO", "VPG", "VST", "Vistra",
    "WEN", "WOLF", "Wolfspeed",
    "ZETA", "Zeta Global",
    # === Macro / Fed (no ticker needed) ===
    "美联储", "CPI", "PPI", "非农", "GDP",
    # === Key people (person-driven events) ===
    "黄仁勋", "Jensen Huang", "马斯克", "Elon Musk", "巴菲特", "Warren Buffett",
    # === Broad market fallback ===
    "美股", "港股",
    # === Policy catalysts ===
    "芯片法案", "关税", "CHIPS Act", "tariff",
]

# Max results per keyword
_MAX_PER_KEYWORD = 20

# Max concurrent Futu API calls (local OpenD — keep modest to avoid
# overwhelming the daemon)
_MAX_CONCURRENT = 5

# Minimum seconds between cycles
_MIN_CYCLE_INTERVAL = 60

# Dedup window — skip titles seen in last N seconds
_DEDUP_TTL = 3600 * 4  # 4 hours

# ── Circuit breaker: prevent connection-leak death spiral ──────────────
# When Futu OpenD is unreachable, every OpenQuoteContext() triggers an
# internal retry loop (~6 s per attempt) inside the Futu SDK.  Fanning out
# 100+ keywords × 5 concurrent = 5 threads retrying forever, leaking
# sockets + file descriptors + log I/O.  Over 15 minutes this produces
# 280+ failures and eventually starves the event loop.
#
# Solution: pre-flight check → circuit breaker → skip entire cycle.
# One quick connect test gates the entire fan-out.  After N consecutive
# failures, circuit opens and we stop trying for an exponentially
# increasing backoff (60s → 120s → 240s → 480s → capping at 600s).
#
# Production incident: 2026-07-29 — Futu OpenD down → 280+ retries in
# 15 min → event loop hung → 10 h silent pipeline.  (See HISTORY.md)
_CONNECT_TIMEOUT = 5.0                # pre-flight max wait
_CB_THRESHOLD = 3                     # consecutive failures to open circuit
_CB_BACKOFF_BASE = 60                 # first backoff (seconds)
_CB_BACKOFF_MAX = 600                 # cap at 10 minutes
_CB_COOLDOWN_CYCLES = 6               # after backoff, try 1 probe cycle

# ---------------------------------------------------------------------------
# Keyword → ticker fallback (like Finnhub's symbol= parameter)
# ---------------------------------------------------------------------------
# When Futu returns an article with empty related_securities, inject the
# search keyword's canonical ticker so the article gets a ticker hit in
# scoring.  Built from entity_extractor's company-name mappings + direct
# ticker matching against the known watchlist.
_KEYWORD_TO_TICKER: Dict[str, str] = {}


def _build_keyword_ticker_map() -> Dict[str, str]:
    """Build keyword→ticker lookup from entity_extractor mappings + keyword list.

    Called once at module load.  Returns a dict suitable for O(1) lookup
    during fetch.  Covers EVERY watchlist stock through three strategies:
      1. Direct ticker: uppercase 2-5 letters in the ticker section → self
      2. English company name → ticker (via entity_extractor._company_to_ticker)
      3. Manual company name → ticker for watchlist stocks not in entity_extractor
    Non-ticker keywords (macro, people, market, policy) are excluded.
    """
    from engine.entity_extractor import EntityExtractor

    ee = EntityExtractor(config=None)

    # Merge English + Chinese company-name → ticker maps
    company_to_ticker: Dict[str, str] = {}
    for name, ticker in ee._company_to_ticker.items():
        company_to_ticker[name.lower()] = ticker
    for name, ticker in ee._cn_company_to_ticker.items():
        company_to_ticker[name.lower()] = ticker

    # Additional watchlist-specific company names not in entity_extractor
    _extra_company_names: Dict[str, str] = {
        # Space / defense
        "archer aviation": "ACHR", "aerovironment": "AVAV",
        "redwire": "RDW", "huntington ingalls": "HII",
        # Tech / semiconductors
        "ionq": "IONQ", "hewlett packard enterprise": "HPE",
        "navitas semiconductor": "NVTS",
        # Energy / nuclear
        "oklo": "OKLO", "nuscale": "SMR", "nano nuclear": "NNE",
        "centrus energy": "LEU", "bloom energy": "BE",
        "iris energy": "IREN", "energy fuels": "UUUU",
        "vistra": "VST",
        # Industrials / materials
        "mp materials": "MP", "bwx technologies": "BWXT",
        "lumentum": "LITE",
        # Biotech / health
        "tempus ai": "TEM", "recursion": "RXRX",
        "serv robotics": "SERV", "serve robotics": "SERV",
        # Finance / crypto
        "galaxy digital": "GLXY",
        # Satcom / space
        "ast spacemobile": "ASTS", "echostar": "SATS",
        # Chips / hardware
        "micron": "MU", "oracle": "ORCL",
        "wolfspeed": "WOLF",
        # Adtech / data
        "zeta global": "ZETA",
        # Broadcom / Marvell (ensure)
        "broadcom": "AVGO", "marvell": "MRVL",
        "arm holdings": "ARM",
    }
    company_to_ticker.update(_extra_company_names)

    # Also add commonly-used short names
    for short_name, ticker in [
        ("arm", "ARM"), ("ionq", "IONQ"), ("oklo", "OKLO"),
        ("spacex", "SPCX"), ("nebius", "NBIS"), ("kratos", "KTOS"),
        ("nvidia", "NVDA"), ("tesla", "TSLA"), ("palantir", "PLTR"),
        ("rigetti", "RGTI"), ("oracle", "ORCL"), ("micron", "MU"),
        ("broadcom", "AVGO"), ("marvell", "MRVL"),
        ("tsmc", "TSM"), ("alibaba", "BABA"), ("google", "GOOGL"),
        ("rocket lab", "RKLB"), ("lam research", "LRCX"),
        ("taiwan semiconductor", "TSM"),
    ]:
        if short_name not in company_to_ticker:
            company_to_ticker[short_name] = ticker

    # Non-ticker keywords to exclude (macro, people, market, policy)
    _NON_TICKER = {
        "CPI", "PPI", "GDP", "ETH", "BTC", "SOL",
        "美联储", "非农", "美股", "港股", "芯片法案", "关税",
        "CHIPS Act", "chips act", "tariff",
        "黄仁勋", "Jensen Huang", "马斯克", "Elon Musk",
        "巴菲特", "Warren Buffett",
    }

    result: Dict[str, str] = {}
    for kw in _SEARCH_KEYWORDS:
        if kw in _NON_TICKER:
            continue

        kw_lower = kw.lower()

        # Strategy 1: Direct ticker (uppercase 2-5 letters)
        if 1 <= len(kw) <= 5 and kw.isalpha() and kw.isupper():
            result[kw] = kw
            continue

        # Strategy 2: Company name → ticker
        ticker = company_to_ticker.get(kw_lower)
        if ticker:
            result[kw] = ticker

    return result


# Build at import time
_KEYWORD_TO_TICKER = _build_keyword_ticker_map()


def _probe_sync(host: str, port: int) -> bool:
    """Synchronous connection probe — runs in thread pool.

    Uses a raw TCP socket connect (2s timeout) to test Futu OpenD
    reachability WITHOUT creating an OpenQuoteContext.  This is critical:
    OpenQuoteContext() starts an internal retry loop that we cannot stop
    from asyncio (to_thread threads ignore CancelledError).  A raw socket
    connect succeeds or fails in 2s — no leak, no retry loop.

    After TCP succeeds we still do a quick OpenQuoteContext API call to
    verify the gateway is actually responding (not just accepting TCP).
    """
    import socket

    # Phase 1: raw TCP connect — fail-fast, no SDK overhead
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=2.0)
    except (OSError, TimeoutError):
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    # Phase 2: lightweight API call through the SDK
    from futu import OpenQuoteContext, RET_OK

    ctx = None
    try:
        ctx = OpenQuoteContext(host=host, port=port)
        ret, _ = ctx.get_market_state(["US.QQQ"])
        return ret == RET_OK
    except Exception:
        return False
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass


class FutuNewsFetcher:
    """Futu news search fetcher — concurrent full-keyword coverage.

    Searches ALL keywords every cycle using concurrent connections.
    No rotation — every ticker/company name is polled every 60 seconds.

    Circuit breaker: when Futu OpenD is unreachable, the fetcher does a
    single pre-flight connection check before fanning out to 100+ keywords.
    After N consecutive failures the circuit opens and all cycles are
    skipped for an exponentially increasing backoff.  This prevents the
    connection-leak death spiral where 5 concurrent SDK threads each run
    their internal retry loop forever (280+ failures, event-loop starvation).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        keywords: Optional[List[str]] = None,
    ):
        self._host = host
        self._port = port
        self._keywords = keywords or _SEARCH_KEYWORDS
        self._last_cycle = 0.0
        self._seen: Dict[str, float] = {}  # title_hash → timestamp

        # ── Circuit breaker state ──
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0       # monotonic timestamp
        self._circuit_probe_done = False      # one probe after cooldown

    # ── Circuit breaker helpers ────────────────────────────────────────

    def _circuit_is_open(self, now: float) -> bool:
        """True while the circuit breaker is tripped."""
        return now < self._circuit_open_until

    def _record_success(self, now: float) -> None:
        """Reset circuit on a healthy cycle."""
        if self._consecutive_failures > 0:
            logger.info(
                "FutuNews: circuit reset — connection restored after %d failures",
                self._consecutive_failures,
            )
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._circuit_probe_done = False

    def _record_failure(self, now: float) -> None:
        """Increment failure count; open circuit if threshold reached."""
        self._consecutive_failures += 1
        n = self._consecutive_failures
        if n >= _CB_THRESHOLD:
            delay = min(
                _CB_BACKOFF_BASE * (2 ** (n - _CB_THRESHOLD)),
                _CB_BACKOFF_MAX,
            )
            self._circuit_open_until = now + delay
            logger.warning(
                "FutuNews: CIRCUIT OPEN — %d consecutive failures, "
                "suspending for %ds (next probe at +%ds)",
                n, delay, delay,
            )
        else:
            logger.warning(
                "FutuNews: connection failed (%d/%d before circuit opens)",
                n, _CB_THRESHOLD,
            )

    # ── Pre-flight check ───────────────────────────────────────────────

    async def _probe_connection(self) -> bool:
        """Single-thread connection test with a short asyncio timeout.

        Creates exactly ONE OpenQuoteContext in a thread.  If the SDK's
        internal connect takes longer than _CONNECT_TIMEOUT we cancel the
        await (the thread keeps running but we know OpenD is down).

        Returns True if the probe succeeded, False otherwise.
        """
        host, port = self._host, self._port
        try:
            ok = await asyncio.wait_for(
                asyncio.to_thread(_probe_sync, host, port),
                timeout=_CONNECT_TIMEOUT,
            )
            return bool(ok)
        except asyncio.TimeoutError:
            logger.debug("FutuNews: probe timed out after %.0fs", _CONNECT_TIMEOUT)
            return False
        except Exception as e:
            logger.debug("FutuNews: probe error: %s", e)
            return False

    # ── Main fetch ─────────────────────────────────────────────────────

    async def fetch(self) -> List[NewsItem]:
        """Fetch news for ALL keywords concurrently. Call on heartbeat timer."""
        now = time.time()

        # ── Cooldown gate ──────────────────────────────────────────
        if now - self._last_cycle < _MIN_CYCLE_INTERVAL:
            remaining = _MIN_CYCLE_INTERVAL - (now - self._last_cycle)
            logger.debug("FutuNews: cooldown (%.0fs remaining)", remaining)
            return []

        # ── Circuit breaker gate ───────────────────────────────────
        if self._circuit_is_open(now):
            # One probe per cooldown period to see if OpenD is back
            if not self._circuit_probe_done:
                self._circuit_probe_done = True
                logger.info(
                    "FutuNews: circuit open — probing connection (failures=%d)",
                    self._consecutive_failures,
                )
                if await self._probe_connection():
                    self._record_success(now)
                    # fall through to normal fetch
                else:
                    remaining = int(self._circuit_open_until - now)
                    logger.warning(
                        "FutuNews: probe failed — circuit still open "
                        "(%ds remaining)", remaining,
                    )
                    return []
            else:
                remaining = int(self._circuit_open_until - now)
                logger.debug(
                    "FutuNews: circuit open — skipping cycle (%ds remaining)",
                    remaining,
                )
                return []

        self._last_cycle = now

        # ── Pre-flight check (before fan-out) ──────────────────────
        if not await self._probe_connection():
            logger.warning(
                "FutuNews: pre-flight failed — skipping %d keywords this cycle",
                len(self._keywords),
            )
            self._record_failure(now)
            return []

        logger.info("FutuNews: searching ALL %d keywords (concurrent, max %d)",
                     len(self._keywords), _MAX_CONCURRENT)

        # ── Concurrent fetch: each keyword gets its own connection ──
        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _fetch_one(kw: str) -> List[dict]:
            async with sem:
                return await asyncio.to_thread(self._fetch_single_keyword, kw)

        tasks = [_fetch_one(kw) for kw in self._keywords]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results, skipping exceptions
        all_raw: List[dict] = []
        for kw, result in zip(self._keywords, results):
            if isinstance(result, Exception):
                logger.debug("FutuNews: keyword '%s' error: %s", kw, result)
            elif isinstance(result, list):
                all_raw.extend(result)

        # ── Health tracking: count successful keywords ─────────────
        success_count = sum(
            1 for r in results if isinstance(r, list)
        )
        if success_count == 0 and len(self._keywords) > 0:
            logger.warning(
                "FutuNews: ALL %d keywords failed — may indicate OpenD issue",
                len(self._keywords),
            )
            self._record_failure(now)
        else:
            self._record_success(now)

        logger.debug("FutuNews: %d raw items from %d keywords (%d ok)",
                     len(all_raw), len(self._keywords), success_count)

        # ── Dedup + build NewsItems ──
        items: List[NewsItem] = []
        for raw in all_raw:
            title = raw.get("title", "")
            title_hash = hashlib.md5(
                title.encode("utf-8", errors="replace")
            ).hexdigest()
            if title_hash in self._seen:
                if now - self._seen[title_hash] < _DEDUP_TTL:
                    continue
            self._seen[title_hash] = now

            tickers_raw = raw.get("related_tickers", [])
            # ── Finnhub-style fallback: inject search keyword's ticker ──
            if not tickers_raw:
                search_kw = raw.get("_search_kw", "")
                fallback_ticker = _KEYWORD_TO_TICKER.get(search_kw, "")
                if fallback_ticker:
                    tickers_raw = [fallback_ticker]
            tickers_str = ",".join(tickers_raw)
            items.append(NewsItem(
                title=title,
                url=raw.get("url", ""),
                source=raw.get("source", ""),
                content_snippet=title,
                published_at=_parse_futu_time(raw.get("published_at", "")),
                tickers_found=tickers_str,
            ))

        # Cleanup old seen entries
        cutoff = now - _DEDUP_TTL * 2
        self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

        logger.info("FutuNews: %d unique items (from %d raw)",
                     len(items), len(all_raw))
        return items

    def _fetch_single_keyword(self, kw: str) -> List[dict]:
        """Fetch news for ONE keyword. Runs in thread pool (Futu API is sync)."""
        from futu import OpenQuoteContext, NewsSubType, RET_OK

        ctx = None
        try:
            ctx = OpenQuoteContext(host=self._host, port=self._port)
            ret, data = ctx.get_search_news(
                kw,
                max_count=_MAX_PER_KEYWORD,
                news_sub_type=NewsSubType.ALL,
            )
            if ret != RET_OK:
                logger.debug("FutuNews: search '%s' failed: %s", kw, data)
                return []
            if data is None or len(data) == 0:
                return []

            items: List[dict] = []
            for _, row in data.iterrows():
                related = row.get("related_securities", None)
                if related is None or not isinstance(related, list):
                    related = []

                items.append({
                    "title": str(row.get("title", "")),
                    "source": f"富途·{row.get('source', '资讯')}",
                    "url": str(row.get("url", "")),
                    "published_at": str(row.get("publish_time", "")),
                    "related_tickers": related,
                    "_search_kw": kw,  # for keyword→ticker fallback
                })
            return items
        except Exception as e:
            logger.debug("FutuNews: keyword '%s' error: %s", kw, e)
            return []
        finally:
            if ctx is not None:
                ctx.close()

    async def close(self):
        """No-op — connections are per-cycle."""
        pass


def _parse_futu_time(ts: str) -> datetime:
    """Parse Futu publish_time to datetime. Returns now() on failure."""
    if not ts:
        return datetime.now()
    try:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d"):
            try:
                return datetime.strptime(ts.strip(), fmt)
            except ValueError:
                continue
        parts = ts.strip().split("/")
        if len(parts) == 2:
            return datetime(datetime.now().year, int(parts[0]), int(parts[1]))
    except Exception:
        pass
    return datetime.now()
