"""Tests for deep-analysis data grounding — SPEC-deep-analysis-stale-data.md

The deep analysis card fabricated market data (META claimed -7.64% when it was
actually +4.70%) and issued a real "short META" recommendation. Root cause:
market enrichment timed out silently → LLM had zero data → soft prompt
constraint failed → LLM invented prices.

This suite verifies the hard gate + output validation that prevent fabrication.
Tests never use real push credentials.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from engine.deep_lane import (
    _has_valid_market_data,
    _strip_fabricated_numbers,
    _has_trade_recommendation,
    NO_DATA_BANNER,
)


# ══════════════════════════════════════════════════════════════════════════
# ① Hard gate: detect whether we actually got market data
# ══════════════════════════════════════════════════════════════════════════

class TestHasValidMarketData:
    def test_empty_string_no_data(self):
        assert _has_valid_market_data("") is False

    def test_none_no_data(self):
        assert _has_valid_market_data(None) is False

    def test_header_only_no_data(self):
        """Just the header line with no price rows → no data."""
        assert _has_valid_market_data(
            "[REAL-TIME MARKET DATA — use this to ground your analysis]"
        ) is False

    def test_whitespace_only_no_data(self):
        assert _has_valid_market_data("   \n  \n") is False

    def test_has_price_row_is_valid(self):
        """A real price row (contains $ and %) → valid data."""
        block = (
            "[REAL-TIME MARKET DATA — use this to ground your analysis]\n"
            "  META: $654.7 (+4.70% pre-market) (above 20MA 610.2)"
        )
        assert _has_valid_market_data(block) is True

    def test_index_row_is_valid(self):
        """SPX/VIX macro rows count as valid data too."""
        block = (
            "[REAL-TIME MARKET DATA — use this to ground your analysis]\n"
            "  SPX: 5820.3 (+0.85%)"
        )
        assert _has_valid_market_data(block) is True


# ══════════════════════════════════════════════════════════════════════════
# ② Output validation: strip numbers that don't match the enrichment
# ══════════════════════════════════════════════════════════════════════════

class TestStripFabricatedNumbers:
    def test_matching_numbers_pass(self):
        """Numbers present in enrichment are kept."""
        enrichment = "  META: $654.7 (+4.70% pre-market)"
        llm = "META盘前上涨4.70%至654.7美元，动能强劲。"
        cleaned, flagged = _strip_fabricated_numbers(llm, enrichment)
        assert flagged == []
        assert "654.7" in cleaned

    def test_fabricated_price_flagged(self):
        """A price NOT in enrichment (the Micron bug: -7.64% @ 649.2) is flagged."""
        enrichment = "  META: $654.7 (+4.70% pre-market)"
        llm = "META盘前下跌7.64%至649.2美元，跌破20日均线。做空META，目标580。"
        cleaned, flagged = _strip_fabricated_numbers(llm, enrichment)
        assert len(flagged) > 0
        # The fabricated sentence should be removed
        assert "649.2" not in cleaned
        assert "7.64" not in cleaned

    def test_no_enrichment_flags_all_numbers(self):
        """With no enrichment, ANY specific price/percent is fabricated."""
        llm = "META下跌7.64%至649.2美元。做空META。"
        cleaned, flagged = _strip_fabricated_numbers(llm, "")
        assert len(flagged) > 0
        assert "649.2" not in cleaned

    def test_qualitative_text_untouched(self):
        """Text with no specific numbers passes through unchanged."""
        llm = "META受宏观逆风压制，情绪偏空，需关注财报。"
        cleaned, flagged = _strip_fabricated_numbers(llm, "")
        assert flagged == []
        assert cleaned == llm

    def test_year_and_generic_numbers_not_flagged(self):
        """Plain integers / years without $ or % are not treated as prices."""
        llm = "2026年第一季度营收增长，行业景气度回升。"
        cleaned, flagged = _strip_fabricated_numbers(llm, "")
        assert flagged == []
        assert cleaned == llm


# ══════════════════════════════════════════════════════════════════════════
# ②b Adversarial: Chinese/full-width number formats that bypassed v1
# (found by quality-gate adversarial review — same-model blind spot for
#  英文半角 number formats. Real Chinese LLM output uses 美元/％/百分之/裸点位.)
# ══════════════════════════════════════════════════════════════════════════

class TestChineseNumberBypass:
    def test_chinese_yuan_price_no_dollar(self):
        """'649.2美元' with no $ must be flagged (the real incident variant)."""
        llm = "META盘前下跌7.64个百分点至649.2美元，跌破均线。"
        cleaned, flagged = _strip_fabricated_numbers(llm, "")
        assert len(flagged) > 0
        assert "649.2" not in cleaned

    def test_bare_target_and_stop(self):
        """'目标580，止损600' bare numbers with 目标/止损 keywords → flagged."""
        llm = "META目标580，止损600，仓位可加。"
        cleaned, flagged = _strip_fabricated_numbers(llm, "")
        assert len(flagged) > 0
        assert "580" not in cleaned

    def test_fullwidth_percent(self):
        """Full-width ％ (U+FF05) must be flagged."""
        llm = "META将下跌7.64％，跌破支撑。"
        cleaned, flagged = _strip_fabricated_numbers(llm, "")
        assert len(flagged) > 0
        assert "7.64" not in cleaned

    def test_ge_baifendian(self):
        """'个百分点' change unit must be flagged."""
        llm = "META料下跌7.64个百分点。"
        cleaned, flagged = _strip_fabricated_numbers(llm, "")
        assert len(flagged) > 0

    def test_integer_price_yuan(self):
        """Integer price with 美元/元 must be flagged."""
        llm = "META盘前跌至649美元一线。"
        cleaned, flagged = _strip_fabricated_numbers(llm, "")
        assert len(flagged) > 0
        assert "649" not in cleaned

    def test_20pct_not_washed_by_20ma(self):
        """'下跌20%' must NOT be laundered by '20MA' in enrichment.

        grounded set must exclude MA-period / volume bare numbers.
        """
        enrichment = "  META: $654.7 (+4.70%) (above 20MA 610.2)"
        llm = "预计META后市将下跌20%至520美元。"
        cleaned, flagged = _strip_fabricated_numbers(llm, enrichment)
        assert len(flagged) > 0
        assert "520" not in cleaned

    def test_grounded_price_still_kept_with_ma(self):
        """Regression: real grounded price/percent still survives."""
        enrichment = "  META: $654.7 (+4.70%) (above 20MA 610.2)"
        llm = "META上涨4.70%至654.7美元，站上20日均线610.2。"
        cleaned, flagged = _strip_fabricated_numbers(llm, enrichment)
        assert flagged == []
        assert "654.7" in cleaned


class TestTradeRecommendationDetection:
    """Pure-text trade calls (no numbers) — the softest bypass."""

    def test_short_call_detected(self):
        assert _has_trade_recommendation("建议立即做空META并逢高减仓。") is True

    def test_long_call_detected(self):
        assert _has_trade_recommendation("买入NVDA，加仓科技板块。") is True

    def test_qualitative_no_call(self):
        assert _has_trade_recommendation("事件偏空，需关注后续财报指引。") is False

    def test_english_short_detected(self):
        assert _has_trade_recommendation("Recommend to short META here.") is True


# ══════════════════════════════════════════════════════════════════════════
# ③ Integration: _call_llm hard gate + validation wiring
# ══════════════════════════════════════════════════════════════════════════

class TestCallLlmGrounding:
    """Verify the gate/validation are wired into the LLM call path."""

    @pytest.fixture
    def deep_lane(self):
        from engine.deep_lane import DeepLane
        cfg = MagicMock()
        cfg.load_settings.return_value = {"deep_lane": {}}
        db = MagicMock()
        db.get_preference.return_value = ""
        db.get_training_context.return_value = ""
        dl = DeepLane(config=cfg, db=db)
        dl._api_key = "test-key"  # pretend a provider is configured
        return dl

    @pytest.fixture
    def item(self):
        from storage.models import NewsItem
        return NewsItem(
            id=3340,
            title="Micron's $250 Billion Bet, Pepsi and Levi Get Punished",
            source="bloomberg", url="http://x/1",
            tickers_found="META,MRVL", macro_tags="", sentiment="bearish",
            sentiment_score=-0.4,
        )

    @pytest.mark.asyncio
    async def test_timeout_engages_no_data_gate(self, deep_lane, item):
        """Enrichment timeout → no-data prompt used + banner + numbers stripped.

        Simulates the exact production bug: fetch times out, LLM tries to
        fabricate '-7.64% @ 649.2 short META', validation strips it.
        """
        async def _slow(*a, **k):
            import asyncio
            await asyncio.sleep(10)  # will be cancelled by wait_for
        deep_lane._fetch_market_enrichment = _slow

        # LLM fabricates numbers (as in the real incident)
        fabricated = "META盘前下跌7.64%至649.2美元，跌破20日均线。做空META，目标580。"
        deep_lane._call_deepseek = AsyncMock(return_value=fabricated)
        deep_lane._call_anthropic = AsyncMock(return_value=fabricated)

        with patch("engine.deep_lane._ENRICH_TIMEOUT", 0.05):
            result = await deep_lane._call_llm(item)

        # Fabricated numbers must be gone
        assert "649.2" not in result
        assert "7.64" not in result
        # Banner present
        assert NO_DATA_BANNER in result

    @pytest.mark.asyncio
    async def test_valid_data_keeps_grounded_numbers(self, deep_lane, item):
        """When enrichment is valid, grounded numbers survive, no banner."""
        enrichment = (
            "[REAL-TIME MARKET DATA — use this to ground your analysis]\n"
            "  META: $654.7 (+4.70% pre-market) (above 20MA 610.2)"
        )
        deep_lane._fetch_market_enrichment = AsyncMock(return_value=enrichment)

        grounded = "META盘前上涨4.70%至654.7美元，站上20日均线610.2，动能强劲。"
        deep_lane._call_deepseek = AsyncMock(return_value=grounded)
        deep_lane._call_anthropic = AsyncMock(return_value=grounded)

        result = await deep_lane._call_llm(item)

        assert "654.7" in result
        assert "4.70" in result
        assert NO_DATA_BANNER not in result  # data was present

    @pytest.mark.asyncio
    async def test_valid_data_but_llm_fabricates_gets_stripped(self, deep_lane, item):
        """Data present for META, but LLM hard-codes a WRONG number → stripped.

        SPEC §5 case 3: enrichment says +4.70%, LLM says -7.64% → caught.
        """
        enrichment = (
            "[REAL-TIME MARKET DATA]\n"
            "  META: $654.7 (+4.70% pre-market)"
        )
        deep_lane._fetch_market_enrichment = AsyncMock(return_value=enrichment)

        mixed = "META数据显示+4.70%。但我认为会下跌7.64%至649.2美元。做空META。"
        deep_lane._call_deepseek = AsyncMock(return_value=mixed)
        deep_lane._call_anthropic = AsyncMock(return_value=mixed)

        result = await deep_lane._call_llm(item)

        # Grounded sentence kept, fabricated one stripped
        assert "4.70" in result
        assert "649.2" not in result
        assert "7.64" not in result

    @pytest.mark.asyncio
    async def test_no_data_strips_pure_text_trade_call(self, deep_lane, item):
        """No data + LLM gives pure-text 'short META' (no numbers) → stripped."""
        async def _slow(*a, **k):
            import asyncio
            await asyncio.sleep(10)
        deep_lane._fetch_market_enrichment = _slow

        pure_call = "META受宏观逆风压制。建议立即做空META并逢高减仓。"
        deep_lane._call_deepseek = AsyncMock(return_value=pure_call)
        deep_lane._call_anthropic = AsyncMock(return_value=pure_call)

        with patch("engine.deep_lane._ENRICH_TIMEOUT", 0.05):
            result = await deep_lane._call_llm(item)

        # The trade recommendation sentence must be gone in no-data mode
        assert "做空" not in result
        assert NO_DATA_BANNER in result

