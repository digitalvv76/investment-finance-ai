"""Tests for web_scraper VLM fallback logic — does NOT call real APIs."""
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from collector.web_scraper import WebScraper, _MIN_ITEMS_CSS, _VLM_COOLDOWN_SECONDS
from storage.models import NewsItem


class TestVlmStateMachine:
    """Unit tests for _should_use_vlm fail-counter and cool-down logic."""

    def test_css_success_resets_fail_counter(self):
        scraper = WebScraper()
        # Simulate 2 prior failures
        scraper._vlm_state["CNBC"] = {"failures": 2, "vlm_until": 0.0}

        # CSS returns enough items → should NOT trigger VLM
        result = scraper._should_use_vlm("CNBC", 10)
        assert result is False
        assert scraper._vlm_state["CNBC"]["failures"] == 0

    def test_one_failure_no_trigger(self):
        scraper = WebScraper()
        result = scraper._should_use_vlm("新浪财经", 0)
        assert result is False
        assert scraper._vlm_state["新浪财经"]["failures"] == 1

    def test_two_failures_no_trigger(self):
        scraper = WebScraper()
        scraper._vlm_state["新浪财经"] = {"failures": 1, "vlm_until": 0.0}
        result = scraper._should_use_vlm("新浪财经", 1)
        assert result is False
        assert scraper._vlm_state["新浪财经"]["failures"] == 2

    def test_three_failures_triggers_vlm(self):
        scraper = WebScraper()
        scraper._vlm_state["MarketWatch"] = {"failures": 2, "vlm_until": 0.0}
        result = scraper._should_use_vlm("MarketWatch", 0)
        assert result is True
        assert scraper._vlm_state["MarketWatch"]["failures"] == 3
        # Cool-down timestamp must be set
        assert scraper._vlm_state["MarketWatch"]["vlm_until"] > 0

    def test_vlm_cooldown_blocked(self):
        """Within cool-down window, VLM continues to fire."""
        scraper = WebScraper()
        future = time.monotonic() + 1800  # 30 min from now
        scraper._vlm_state["CNBC"] = {"failures": 4, "vlm_until": future}
        result = scraper._should_use_vlm("CNBC", 2)
        assert result is True  # Still in VLM mode

    def test_vlm_cooldown_expired_css_still_low_re_triggers(self):
        """After cool-down, if CSS still returns too few, VLM re-fires."""
        scraper = WebScraper()
        past = time.monotonic() - 10  # 10s ago
        scraper._vlm_state["CNBC"] = {"failures": 5, "vlm_until": past}
        result = scraper._should_use_vlm("CNBC", 2)
        assert result is True  # CSS below threshold, VLM fires again

    def test_vlm_cooldown_expired_css_fails_retriggers(self):
        """After cool-down expires but CSS still fails, VLM re-triggers."""
        scraper = WebScraper()
        past = time.monotonic() - 10
        scraper._vlm_state["新浪财经"] = {"failures": 5, "vlm_until": past}
        # CSS still returns 0 after cool-down → re-trigger VLM
        result = scraper._should_use_vlm("新浪财经", 0)
        assert result is True
        assert scraper._vlm_state["新浪财经"]["vlm_until"] > time.monotonic()

    def test_min_items_threshold_respected(self):
        """Each source has its own min-items threshold."""
        scraper = WebScraper()
        scraper._vlm_state["MarketWatch"] = {"failures": 2, "vlm_until": 0.0}
        # MarketWatch min is 5; 4 items < 5 → triggers
        result = scraper._should_use_vlm("MarketWatch", 4)
        assert result is True  # Below threshold

    def test_unknown_source_uses_default_min(self):
        """Source not in _MIN_ITEMS_CSS defaults to 3."""
        scraper = WebScraper()
        result = scraper._should_use_vlm("UnknownSource", 4)
        assert result is False  # 4 >= default 3 → no trigger


class TestVlmItemsToNews:
    """Unit tests for _vlm_items_to_news conversion."""

    def test_converts_valid_headlines(self):
        scraper = WebScraper()
        headlines = [
            {"title": "Fed cuts rates", "url": "https://cnbc.com/1", "snippet": "Breaking news"},
            {"title": "Market rallies", "url": "", "snippet": "Market rallies on news"},
        ]
        items = scraper._vlm_items_to_news(headlines, "CNBC")
        assert len(items) == 2
        assert items[0].title == "Fed cuts rates"
        assert items[0].source == "CNBC"
        assert items[0].url == "https://cnbc.com/1"
        assert items[1].url == ""

    def test_filters_empty_titles(self):
        scraper = WebScraper()
        headlines = [
            {"title": "", "url": "https://x.com"},
            {"title": "Valid headline", "url": "", "snippet": "Valid"},
        ]
        items = scraper._vlm_items_to_news(headlines, "TestSource")
        assert len(items) == 1
        assert items[0].title == "Valid headline"

    def test_truncates_long_titles(self):
        scraper = WebScraper()
        long_title = "A" * 300
        headlines = [{"title": long_title, "url": "", "snippet": "x"}]
        items = scraper._vlm_items_to_news(headlines, "X")
        assert len(items[0].title) == 200

    def test_strips_html_tags(self):
        scraper = WebScraper()
        headlines = [{"title": "<b>Bold News</b>", "url": "", "snippet": "x"}]
        items = scraper._vlm_items_to_news(headlines, "X")
        assert items[0].title == "Bold News"


class TestVlmExtractIntegration:
    """Integration tests for _vlm_extract with mock Anthropic API."""

    @pytest.mark.asyncio
    async def test_vlm_extract_returns_parsed_headlines(self):
        scraper = WebScraper()
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(return_value=b"fake_png_bytes")

        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock()]
        mock_msg.content[0].text = json.dumps([
            {"title": "Breaking: Fed cuts rates", "url": "https://cnbc.com/1", "snippet": "Fed cuts"},
            {"title": "Market rallies on news", "url": "https://cnbc.com/2", "snippet": "Rally"},
        ])
        mock_client.messages.create = MagicMock(return_value=mock_msg)

        with patch.object(scraper, "_get_vlm_client", return_value=mock_client):
            with patch.object(scraper, "_load_vlm_prompt", return_value="Test prompt"):
                result = await scraper._vlm_extract(mock_page, "CNBC")

        assert len(result) == 2
        assert result[0]["title"] == "Breaking: Fed cuts rates"
        assert result[0]["url"] == "https://cnbc.com/1"

    @pytest.mark.asyncio
    async def test_vlm_extract_no_client_returns_empty(self):
        scraper = WebScraper()
        mock_page = AsyncMock()

        with patch.object(scraper, "_get_vlm_client", return_value=None):
            result = await scraper._vlm_extract(mock_page, "CNBC")

        assert result == []

    @pytest.mark.asyncio
    async def test_vlm_extract_api_error_returns_empty(self):
        scraper = WebScraper()
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(return_value=b"fake_png")

        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(side_effect=Exception("API error"))

        with patch.object(scraper, "_get_vlm_client", return_value=mock_client):
            with patch.object(scraper, "_load_vlm_prompt", return_value="Test prompt"):
                result = await scraper._vlm_extract(mock_page, "CNBC")

        assert result == []

    @pytest.mark.asyncio
    async def test_vlm_extract_timeout_returns_empty(self):
        scraper = WebScraper()
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(return_value=b"fake_png")

        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(
            side_effect=asyncio.TimeoutError("timed out")
        )

        with patch.object(scraper, "_get_vlm_client", return_value=mock_client):
            with patch.object(scraper, "_load_vlm_prompt", return_value="Test prompt"):
                result = await scraper._vlm_extract(mock_page, "CNBC")

        assert result == []

    @pytest.mark.asyncio
    async def test_vlm_extract_strips_markdown_fences(self):
        scraper = WebScraper()
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(return_value=b"fake_png")

        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock()]
        mock_msg.content[0].text = '```json\n[{"title": "News", "url": "", "snippet": "x"}]\n```'
        mock_client.messages.create = MagicMock(return_value=mock_msg)

        with patch.object(scraper, "_get_vlm_client", return_value=mock_client):
            with patch.object(scraper, "_load_vlm_prompt", return_value="Test prompt"):
                result = await scraper._vlm_extract(mock_page, "CNBC")

        assert len(result) == 1
        assert result[0]["title"] == "News"
