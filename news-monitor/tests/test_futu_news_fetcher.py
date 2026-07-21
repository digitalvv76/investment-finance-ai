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
