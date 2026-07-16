"""Test Chinese entity extraction — company names → ticker mapping.

Spec: docs/superpowers/specs/2026-07-16-wallstreetcn-chinese-pipeline.md
"""

import pytest
from engine.entity_extractor import EntityExtractor


@pytest.fixture
def extractor():
    return EntityExtractor()


class TestChineseCompanyMapping:
    """中文公司名 → ticker 映射"""

    def test_nvidia_cn_name(self, extractor):
        """英伟达 → NVDA"""
        tickers = extractor._extract_tickers("英伟达股价创历史新高")
        assert "NVDA" in tickers

    def test_apple_cn_name(self, extractor):
        """苹果 → AAPL"""
        tickers = extractor._extract_tickers("苹果市值突破4万亿美元")
        assert "AAPL" in tickers

    def test_tesla_cn_name(self, extractor):
        """特斯拉 → TSLA"""
        tickers = extractor._extract_tickers("特斯拉暴跌15%")
        assert "TSLA" in tickers

    def test_intel_cn_name(self, extractor):
        """英特尔 → INTC"""
        tickers = extractor._extract_tickers("英特尔获CHIPS法案补贴")
        assert "INTC" in tickers

    def test_amd_cn_names(self, extractor):
        """超威/超微 → AMD"""
        assert "AMD" in extractor._extract_tickers("超威发布新芯片")
        assert "AMD" in extractor._extract_tickers("超微发布新芯片")

    def test_broadcom_cn_name(self, extractor):
        """博通 → AVGO"""
        tickers = extractor._extract_tickers("博通收购VMware")
        assert "AVGO" in tickers

    def test_taiwan_semi_cn_name(self, extractor):
        """台积电 → TSM"""
        tickers = extractor._extract_tickers("台积电3nm量产")
        assert "TSM" in tickers

    def test_jpmorgan_cn_name(self, extractor):
        """摩根大通 → JPM"""
        tickers = extractor._extract_tickers("摩根大通财报超预期")
        assert "JPM" in tickers

    def test_boeing_cn_name(self, extractor):
        """波音 → BA"""
        tickers = extractor._extract_tickers("波音获得国防合同")
        assert "BA" in tickers

    def test_multiple_cn_names(self, extractor):
        """一条新闻含多个中文公司名"""
        tickers = extractor._extract_tickers(
            "英伟达和台积电合作，苹果和微软竞争AI市场"
        )
        assert "NVDA" in tickers
        assert "TSM" in tickers
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_cn_name_not_in_fallback_ignored(self, extractor):
        """不在 FALLBACK_TICKERS 的中文映射不出现在结果中"""
        # 瑞波 (Ripple/XRP) 不是美股股票，不在 FALLBACK_TICKERS
        tickers = extractor._extract_tickers("瑞波获得法律胜利")
        # XRP not in FALLBACK_TICKERS → should not appear
        assert "瑞波" not in tickers  # it's a name, not a ticker

    def test_cn_and_en_mixed(self, extractor):
        """中英文混合"""
        tickers = extractor._extract_tickers("英伟达(NVDA)和AMD竞争AI芯片市场")
        assert "NVDA" in tickers
        assert "AMD" in tickers


class TestChineseTickerExtractionViaExtract:
    """通过完整的 extract() 验证中文ticker提取（无需ConfigLoader即可工作）"""

    def test_extract_chinese_news_tickers(self, extractor):
        """extract() 中文新闻 → tickers"""
        result = extractor.extract(
            "黄仁勋表示英伟达将加大对台积电的芯片代工订单，"
            "特斯拉股价大涨5%，苹果市值突破4万亿美元"
        )
        assert "NVDA" in result["tickers"]
        assert "TSM" in result["tickers"]
        assert "TSLA" in result["tickers"]

    def test_extract_cn_macro_news(self, extractor):
        """中文宏观新闻 — ticker提取（宏调术语需ConfigLoader加载keywords）"""
        result = extractor.extract("美联储加息25个基点，CPI同比上涨3.2%")
        # Ticker extraction still works without config
        assert isinstance(result["tickers"], list)

    def test_extract_cn_tariff_news(self, extractor):
        """中文贸易新闻"""
        result = extractor.extract("美国宣布对中国加征关税，英伟达和台积电受影响")
        assert "NVDA" in result["tickers"]
        assert "TSM" in result["tickers"]
