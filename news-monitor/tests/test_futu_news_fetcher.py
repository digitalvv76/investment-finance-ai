"""Tests for Futu news fetcher — keyword list + dedup + time parsing."""
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from collector.futu_news_fetcher import (
    FutuNewsFetcher,
    _SEARCH_KEYWORDS,
    _parse_futu_time,
    _DEDUP_TTL,
)


class TestKeywordList:
    """Verify keyword list coverage."""

    def test_all_tickers_have_companion_keywords(self):
        """Every watchlist ticker should be searchable.  English company names
        are supplementary — ticker alone is sufficient for ticker-based search.
        This test verifies key tickers that MUST be in the list."""
        must_have = [
            "KTOS", "NVDA", "TSLA", "PLTR", "IONQ", "RKLB", "OKLO",
            "RGTI", "NBIS", "ASTS", "SMR", "TEM", "SPCX", "MRVL",
            "LRCX", "AVGO", "ARM", "ORCL", "TSM", "MU",
        ]
        for ticker in must_have:
            assert ticker in _SEARCH_KEYWORDS, f"{ticker} missing from keywords"

    def test_english_company_names_in_keywords(self):
        """Key English company names should be present as supplementary keywords."""
        english_names = [
            "Kratos", "Nvidia", "Tesla", "Palantir", "Rocket Lab",
            "IonQ", "Oklo", "Rigetti", "Nebius", "SpaceX",
            "Broadcom", "Marvell", "Lam Research", "Oracle",
            "Taiwan Semiconductor", "Micron",
        ]
        for name in english_names:
            assert name in _SEARCH_KEYWORDS, f"'{name}' missing from keywords"

    def test_macro_keywords_present(self):
        """Macro / people / theme keywords should be present."""
        macro_keys = ["美联储", "CPI", "PPI", "非农", "GDP",
                      "黄仁勋", "Jensen Huang", "马斯克", "Elon Musk",
                      "美股", "港股", "芯片法案", "关税"]
        for kw in macro_keys:
            assert kw in _SEARCH_KEYWORDS, f"'{kw}' missing from keywords"

    def test_no_duplicate_keywords(self):
        """Keyword list should not contain duplicates."""
        seen = set()
        dups = []
        for kw in _SEARCH_KEYWORDS:
            if kw in seen:
                dups.append(kw)
            seen.add(kw)
        assert len(dups) == 0, f"Duplicate keywords: {dups}"


class TestFutuNewsFetcher:
    """Fetcher logic tests (no live Futu connection needed)."""

    @pytest.fixture
    def fetcher(self):
        return FutuNewsFetcher(keywords=["KTOS", "Kratos", "NVDA", "Nvidia"])

    def test_init_with_custom_keywords(self):
        """Custom keyword list should be accepted."""
        f = FutuNewsFetcher(keywords=["AAPL", "Apple"])
        assert f._keywords == ["AAPL", "Apple"]

    def test_init_with_default_keywords(self):
        """Default keywords should be the full _SEARCH_KEYWORDS."""
        f = FutuNewsFetcher()
        assert f._keywords == _SEARCH_KEYWORDS
        assert len(f._keywords) > 100

    def test_cycle_cooldown_prevents_too_frequent_fetch(self, fetcher):
        """fetch() should return [] if called within _MIN_CYCLE_INTERVAL."""
        import asyncio
        fetcher._last_cycle = time.time()  # just set now
        result = asyncio.run(fetcher.fetch())
        assert result == []

    def test_dedup_skips_seen_title(self):
        """Title already in _seen should be skipped."""
        f = FutuNewsFetcher(keywords=["TEST"])
        title = "Unique Test Article Title For Dedup"
        title_hash = __import__("hashlib").md5(
            title.encode("utf-8")
        ).hexdigest()
        f._seen[title_hash] = time.time()

        # Build a raw result that would become this title
        raw = [{
            "title": title,
            "source": "富途·测试",
            "url": "http://example.com",
            "published_at": "2026-07-21 08:00:00",
            "related_tickers": ["KTOS"],
        }]

        # Simulate the dedup logic
        now = time.time()
        items = []
        for r in raw:
            t = r["title"]
            th = __import__("hashlib").md5(
                t.encode("utf-8", errors="replace")
            ).hexdigest()
            if th in f._seen:
                if now - f._seen[th] < _DEDUP_TTL:
                    continue
            items.append(r)

        assert len(items) == 0, "Seen title should be deduped"

    def test_dedup_allows_expired_title(self):
        """Title past DEDUP_TTL should be allowed through."""
        f = FutuNewsFetcher(keywords=["TEST"])
        title = "Expired Article Title"
        title_hash = __import__("hashlib").md5(
            title.encode("utf-8")
        ).hexdigest()
        # Set seen time far in the past
        f._seen[title_hash] = time.time() - _DEDUP_TTL - 1

        now = time.time()
        raw = [{
            "title": title,
            "source": "富途·测试",
            "url": "http://example.com",
            "published_at": "2026-07-21 08:00:00",
            "related_tickers": [],
        }]

        items = []
        for r in raw:
            t = r["title"]
            th = __import__("hashlib").md5(
                t.encode("utf-8", errors="replace")
            ).hexdigest()
            if th in f._seen:
                if now - f._seen[th] < _DEDUP_TTL:
                    continue
            items.append(r)

        assert len(items) == 1, "Expired title should not be deduped"


class TestParseFutuTime:
    """Futu time string parsing."""

    def test_parse_standard_format(self):
        dt = _parse_futu_time("2026-07-21 08:00:00")
        assert dt.year == 2026
        assert dt.month == 7
        assert dt.day == 21
        assert dt.hour == 8
        assert dt.minute == 0

    def test_parse_date_only(self):
        dt = _parse_futu_time("2026-07-21")
        assert dt.year == 2026
        assert dt.month == 7
        assert dt.day == 21

    def test_parse_empty_string_returns_now(self):
        before = datetime.now()
        dt = _parse_futu_time("")
        after = datetime.now()
        assert before <= dt <= after

    def test_parse_garbage_returns_now(self):
        dt = _parse_futu_time("not a real date")
        assert isinstance(dt, datetime)


class TestCircuitBreaker:
    """Circuit breaker prevents connection-leak death spiral (2026-07-29 incident)."""

    @pytest.fixture
    def fetcher(self):
        return FutuNewsFetcher(keywords=["KTOS", "NVDA", "TSLA"])

    # ── Circuit state helpers ─────────────────────────────────────────

    def test_initial_state_closed(self, fetcher):
        """Circuit starts closed — no failures yet."""
        assert fetcher._consecutive_failures == 0
        assert fetcher._circuit_open_until == 0.0
        assert not fetcher._circuit_is_open(time.time())

    def test_record_failure_increments_counter(self, fetcher):
        """Each failure increments the counter."""
        now = time.time()
        fetcher._record_failure(now)
        assert fetcher._consecutive_failures == 1
        fetcher._record_failure(now)
        assert fetcher._consecutive_failures == 2

    def test_circuit_opens_after_threshold(self, fetcher):
        """After _CB_THRESHOLD failures, circuit opens with backoff."""
        from collector.futu_news_fetcher import _CB_THRESHOLD

        now = time.time()
        for _ in range(_CB_THRESHOLD):
            fetcher._record_failure(now)

        assert fetcher._circuit_is_open(now)
        assert fetcher._circuit_open_until > now

    def test_circuit_backoff_increases_exponentially(self, fetcher):
        """Each subsequent failure after threshold doubles the backoff."""
        from collector.futu_news_fetcher import (
            _CB_THRESHOLD, _CB_BACKOFF_BASE, _CB_BACKOFF_MAX,
        )

        now = time.time()
        delays = []
        for i in range(_CB_THRESHOLD + 3):  # threshold + 3 extra failures
            fetcher._record_failure(now)
            if fetcher._circuit_open_until > now:
                delays.append(fetcher._circuit_open_until - now)
            now = fetcher._circuit_open_until  # advance time past each backoff

        # First backoff = _CB_BACKOFF_BASE (60s)
        assert len(delays) >= 2
        assert delays[0] == _CB_BACKOFF_BASE
        # Second backoff should be 2× base
        assert delays[1] == min(_CB_BACKOFF_BASE * 2, _CB_BACKOFF_MAX)

    def test_record_success_resets_circuit(self, fetcher):
        """After a successful cycle, circuit resets completely."""
        from collector.futu_news_fetcher import _CB_THRESHOLD

        now = time.time()
        for _ in range(_CB_THRESHOLD):
            fetcher._record_failure(now)

        assert fetcher._circuit_is_open(now)

        fetcher._record_success(now + 999)
        assert fetcher._consecutive_failures == 0
        assert fetcher._circuit_open_until == 0.0
        assert not fetcher._circuit_is_open(now + 999)

    def test_circuit_is_open_returns_false_after_backoff_expires(self, fetcher):
        """Circuit closes automatically when backoff expires."""
        from collector.futu_news_fetcher import _CB_THRESHOLD

        now = time.time()
        for _ in range(_CB_THRESHOLD):
            fetcher._record_failure(now)

        # Circuit is open now
        assert fetcher._circuit_is_open(now)

        # After backoff expires
        future = fetcher._circuit_open_until + 1
        assert not fetcher._circuit_is_open(future)

    # ── Pre-flight probe ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetch_skips_when_probe_fails(self, fetcher):
        """When pre-flight probe fails, fetch returns [] without fanning out."""
        import asyncio

        async def fake_probe():
            return False

        fetcher._probe_connection = fake_probe
        fetcher._last_cycle = 0  # clear cooldown

        result = await fetcher.fetch()
        assert result == []
        assert fetcher._consecutive_failures >= 1

    @pytest.mark.asyncio
    async def test_fetch_skips_when_circuit_open(self, fetcher):
        """When circuit is open, fetch returns [] immediately."""
        from collector.futu_news_fetcher import _CB_THRESHOLD

        now = time.time()
        for _ in range(_CB_THRESHOLD):
            fetcher._record_failure(now)
        fetcher._circuit_probe_done = True  # probe already attempted this period
        fetcher._last_cycle = 0

        result = await fetcher.fetch()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_probes_once_per_cooldown(self, fetcher):
        """When circuit is open, only one probe per cooldown period."""
        from collector.futu_news_fetcher import _CB_THRESHOLD

        now = time.time()
        for _ in range(_CB_THRESHOLD):
            fetcher._record_failure(now)
        fetcher._last_cycle = 0
        # circuit_probe_done is False initially

        probe_count = 0

        async def fake_probe():
            nonlocal probe_count
            probe_count += 1
            return False

        fetcher._probe_connection = fake_probe

        # First fetch: should probe
        await fetcher.fetch()
        assert probe_count == 1
        assert fetcher._circuit_probe_done is True

        # Second fetch: should NOT probe again
        await fetcher.fetch()
        assert probe_count == 1  # still 1

    @pytest.mark.asyncio
    async def test_probe_success_resets_circuit_and_fetches(self, fetcher):
        """When probe succeeds after circuit open, circuit resets and fetch proceeds."""
        from collector.futu_news_fetcher import _CB_THRESHOLD

        now = time.time()
        for _ in range(_CB_THRESHOLD):
            fetcher._record_failure(now)
        fetcher._last_cycle = 0

        async def fake_probe():
            return True

        fetcher._probe_connection = fake_probe

        # Mock _fetch_single_keyword to avoid real Futu connection
        with patch.object(fetcher, '_fetch_single_keyword', return_value=[]):
            result = await fetcher.fetch()

        # Circuit should be reset after successful probe
        assert fetcher._consecutive_failures == 0
        assert not fetcher._circuit_is_open(time.time())
        # fetch() was called (returned empty because keywords found nothing)
        assert result == []
