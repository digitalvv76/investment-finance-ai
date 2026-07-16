"""Test Chinese priority scoring — deviation patterns + surprise keywords + source authority.

Spec: docs/superpowers/specs/2026-07-16-wallstreetcn-chinese-pipeline.md
"""

import pytest
from storage.models import NewsItem
from engine.priority import PriorityScorer, SOURCE_AUTHORITY


@pytest.fixture
def scorer():
    return PriorityScorer()


# ---------------------------------------------------------------------------
# Source authority
# ---------------------------------------------------------------------------


class TestSourceAuthority:
    """华尔街见闻信源权重"""

    def test_wallstreetcn_global_authority(self):
        assert SOURCE_AUTHORITY.get("华尔街见闻·全球快讯", 0) >= 0.05

    def test_wallstreetcn_us_authority(self):
        assert SOURCE_AUTHORITY.get("华尔街见闻·美股", 0) >= 0.05

    def test_wallstreetcn_forex_authority(self):
        assert SOURCE_AUTHORITY.get("华尔街见闻·外汇", 0) >= 0.05

    def test_sina_authority(self):
        assert SOURCE_AUTHORITY.get("新浪财经·7x24综合快讯", 0) >= 0.04

    def test_bloomberg_still_higher(self):
        """Bloomberg 仍高于华尔街见闻"""
        wsc = SOURCE_AUTHORITY.get("华尔街见闻·全球快讯", 0)
        bloomberg = SOURCE_AUTHORITY.get("bloomberg", 0)
        assert bloomberg > wsc

    def test_wallstreetcn_above_zerohedge(self):
        """华尔街见闻高于 ZeroHedge"""
        wsc = SOURCE_AUTHORITY.get("华尔街见闻·全球快讯", 0)
        zh = SOURCE_AUTHORITY.get("zerohedge", 0)
        assert wsc > zh


# ---------------------------------------------------------------------------
# Chinese deviation patterns
# ---------------------------------------------------------------------------


class TestChineseDeviationPatterns:
    """中文预期差正则"""

    def test_ppi_above_expected(self, scorer):
        """PPI高于预期 → deviation_score > 0"""
        item = NewsItem(
            title="美国6月PPI同比增长2.7%，高于预期的2.5%",
            source="华尔街见闻·全球快讯",
        )
        s = scorer.score(item, tickers=set(), macro_tags={"PPI"})
        assert s >= 0.12, f"Expected ≥0.12, got {s}"  # macro + deviation + source

    def test_nfp_beat(self, scorer):
        """非农超预期"""
        item = NewsItem(
            title="美国6月非农就业新增28.5万人，远超市场预期的19万人",
            source="华尔街见闻·全球快讯",
        )
        s = scorer.score(item, tickers=set(), macro_tags={"非农", "就业"})
        assert s >= 0.12, f"Expected ≥0.12, got {s}"

    def test_cpi_below_expected(self, scorer):
        """CPI低于预期"""
        item = NewsItem(
            title="美国5月CPI同比上涨3.3%，不及市场预估的3.5%",
            source="新浪财经·7x24综合快讯",
        )
        s = scorer.score(item, tickers=set(), macro_tags={"CPI", "通胀"})
        assert s >= 0.08, f"Expected ≥0.08, got {s}"

    def test_qualitative_deviation(self, scorer):
        """大超预期 — 定性偏离"""
        item = NewsItem(
            title="英伟达Q2营收大超预期，AI芯片需求爆发",
            source="华尔街见闻·美股",
        )
        s = scorer.score(item, tickers={"NVDA"})
        # ticker + deviation + source → should be notable
        assert s >= 0.10, f"Expected ≥0.10, got {s}"

    def test_far_below(self, scorer):
        """远低于预期"""
        item = NewsItem(
            title="特斯拉Q2交付量远低于市场预期",
            source="华尔街见闻·美股",
        )
        s = scorer.score(item, tickers={"TSLA"})
        assert s >= 0.10, f"Expected ≥0.10, got {s}"


# ---------------------------------------------------------------------------
# Chinese surprise keywords
# ---------------------------------------------------------------------------


class TestChineseSurpriseKeywords:
    """中文意外关键词"""

    def test_plunge_keyword(self, scorer):
        """暴跌"""
        item = NewsItem(
            title="英伟达盘中暴跌12%，市值蒸发2000亿美元",
            source="华尔街见闻·美股",
        )
        s = scorer.score(item, tickers={"NVDA"})
        assert s >= 0.10, f"Expected ≥0.10, got {s}"

    def test_surge_keyword(self, scorer):
        """暴涨"""
        item = NewsItem(
            title="游戏驿站暴涨超90%触发熔断",
            source="新浪财经·7x24综合快讯",
        )
        s = scorer.score(item, tickers={"GME"})
        assert s >= 0.12, f"Expected ≥0.12, got {s}"

    def test_black_swan_keyword(self, scorer):
        """黑天鹅"""
        item = NewsItem(
            title="黑天鹅事件引发全球市场恐慌",
            source="华尔街见闻·全球快讯",
        )
        s = scorer.score(item, tickers=set(), macro_tags={"地缘政治"})
        # surprise keywords push score up
        assert s >= 0.05, f"Expected ≥0.05, got {s}"

    def test_panic_keyword(self, scorer):
        """恐慌"""
        item = NewsItem(
            title="市场恐慌性抛售，VIX飙升至40",
            source="华尔街见闻·全球快讯",
        )
        s = scorer.score(item, tickers=set(), macro_tags={"VIX"})
        assert s >= 0.08, f"Expected ≥0.08, got {s}"


# ---------------------------------------------------------------------------
# Routine Chinese news (low score)
# ---------------------------------------------------------------------------


class TestRoutineChineseNews:
    """中文常规新闻应得低分"""

    def test_routine_a_share_news(self, scorer):
        """A股日常新闻"""
        item = NewsItem(
            title="沪深两市成交额再破万亿",
            source="新浪财经·7x24综合快讯",
        )
        s = scorer.score(item)
        assert s < 0.15, f"Expected <0.15, got {s}"

    def test_routine_commentary(self, scorer):
        """无数据支撑的市场评论"""
        item = NewsItem(
            title="分析师：A股短期震荡为主",
            source="新浪财经·7x24综合快讯",
        )
        s = scorer.score(item)
        assert s < 0.10, f"Expected <0.10, got {s}"

    def test_chinese_domestic_policy(self, scorer):
        """中国国内政策 — 无美股映射，低分"""
        item = NewsItem(
            title="央行开展1000亿元MLF操作",
            source="新浪财经·7x24综合快讯",
        )
        s = scorer.score(item, macro_tags={"MLF"})
        # Has macro tag but no tickers, no deviation — moderate at best
        assert s < 0.20, f"Expected <0.20, got {s}"


# ---------------------------------------------------------------------------
# MacroAgent routing — Chinese macro items
# ---------------------------------------------------------------------------


class TestMacroRouting:
    """宏观新闻应被正确评分以供 MacroAgent 接管"""

    def test_ppi_routes_to_macro(self, scorer):
        """PPI超预期 → 宏观通道"""
        item = NewsItem(
            title="美国6月PPI同比增长2.7%，高于预期的2.5%",
            source="华尔街见闻·全球快讯",
        )
        s = scorer.score(item, macro_tags={"PPI", "通胀"})
        # Score high enough for fast-lane / MacroAgent
        assert s >= 0.10, f"Expected ≥0.10, got {s}"

    def test_fomc_routes_to_macro(self, scorer):
        """美联储决议 → 宏观通道"""
        item = NewsItem(
            title="美联储维持利率不变，点阵图显示年内降息一次",
            source="华尔街见闻·全球快讯",
        )
        s = scorer.score(item, macro_tags={"美联储", "利率", "FOMC"})
        assert s >= 0.10, f"Expected ≥0.10, got {s}"
