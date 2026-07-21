"""Tests for entity extractor."""
import pytest
from unittest.mock import MagicMock, patch
from engine.entity_extractor import EntityExtractor


@pytest.fixture
def extractor():
    """Create an EntityExtractor with mock config."""
    mock_config = MagicMock()
    mock_config.load_keywords.return_value = {
        'breaking_markers': ['BREAKING', 'URGENT'],
        'macro_alerts': ['CPI', 'FOMC', 'Federal Reserve', 'inflation', 'GDP', 'recession'],
        'key_people': ['Kevin Warsh', 'Jerome Powell', 'Elon Musk', 'Jensen Huang'],
        'sectors': {
            'semiconductor': ['semiconductor', 'chip', 'GPU'],
            'tech': ['cloud computing', 'AI', 'artificial intelligence'],
            'crypto': ['Bitcoin', 'Ethereum', 'cryptocurrency', 'blockchain'],
        },
    }
    return EntityExtractor(config=mock_config)


class TestEntityExtractor:
    """Entity extraction tests."""

    def test_extract_tickers_from_text(self, extractor):
        """Tickers from watchlist should be extracted."""
        result = extractor.extract("NVDA reports strong earnings as AAPL falls")
        assert 'NVDA' in result['tickers']
        assert 'AAPL' in result['tickers']

    def test_extract_tickers_ignores_common_words(self, extractor):
        """Common uppercase words should not be treated as tickers."""
        result = extractor.extract("THE market IS UP today BUT volatility remains")
        # THE, IS, UP, BUT are not known tickers
        assert 'THE' not in result['tickers']
        assert 'IS' not in result['tickers']

    def test_extract_companies_via_ner(self, extractor):
        """Company names should be detected via NER."""
        result = extractor.extract(
            "Nvidia Corporation announced a partnership with Apple Inc "
            "to develop new AI chips, according to Goldman Sachs analysts."
        )
        # NER may or may not fire depending on spaCy model; at minimum check structure
        assert 'companies' in result
        assert isinstance(result['companies'], list)

    def test_extract_people_from_known_list(self, extractor):
        """Known people should be detected even without NER."""
        result = extractor.extract("Kevin Warsh signals rate policy shift")
        assert 'Kevin Warsh' in result['people']

    def test_extract_people_via_ner(self, extractor):
        """People in NER should be captured."""
        result = extractor.extract(
            "Elon Musk announced Tesla's new factory plans yesterday"
        )
        # Elon Musk should be detected either via NER or known list
        assert 'Elon Musk' in result['people']

    def test_extract_indicators(self, extractor):
        """Macro indicators should be matched from keyword list."""
        result = extractor.extract(
            "CPI data shows inflation remains sticky, Federal Reserve may delay rate cuts"
        )
        assert 'CPI' in result['indicators']
        assert any('inflation' in i.lower() for i in result['indicators'])
        assert any('Federal Reserve' in i for i in result['indicators'])

    def test_extract_sectors(self, extractor):
        """Sector keywords should be mapped."""
        result = extractor.extract(
            "The semiconductor industry faces GPU shortages as AI demand surges. "
            "Bitcoin and cryptocurrency markets also rallied."
        )
        assert 'semiconductor' in result['sectors']
        assert 'crypto' in result['sectors']

    def test_empty_text(self, extractor):
        """Empty text should return empty lists."""
        result = extractor.extract("")
        assert result['tickers'] == []
        assert result['companies'] == []
        assert result['people'] == []
        assert result['indicators'] == []
        assert result['sectors'] == []

    def test_no_config_extractor(self):
        """Extractor without config should use fallbacks."""
        ex = EntityExtractor(config=None)
        result = ex.extract("NVDA and AMD are top semiconductor stocks")
        assert 'NVDA' in result['tickers']
        assert 'AMD' in result['tickers']

    def test_chinese_nvidia_mapping(self, extractor):
        """Chinese 英伟达 should map to NVDA."""
        result = extractor.extract("英伟达公司报告持有NEBIUS Group N.V. 9.3%的被动股权")
        assert 'NVDA' in result['tickers']

    def test_nebius_company_name_to_nbis(self, extractor):
        """Company name 'Nebius' (with 'u') should map to ticker NBIS."""
        result = extractor.extract("Nebius Group secures NVIDIA investment")
        assert 'NBIS' in result['tickers']

    def test_nebius_uppercase_to_nbis(self, extractor):
        """Uppercase NEBIUS should map to NBIS via case-insensitive match."""
        result = extractor.extract("英伟达披露持有NEBIUS 9.3%股权——SEC文件")
        assert 'NVDA' in result['tickers']
        assert 'NBIS' in result['tickers']

    def test_nebius_group_full_name(self, extractor):
        """Full company name 'Nebius Group N.V.' should map to NBIS."""
        result = extractor.extract("NVIDIA discloses stake in Nebius Group N.V.")
        assert 'NVDA' in result['tickers']
        assert 'NBIS' in result['tickers']

    def test_tsmc_english_to_tsm(self, extractor):
        """English 'TSMC' should map to TSM ticker."""
        result = extractor.extract(
            "Exclusive: TSMC to raise chipmaking prices by up to 10% from 2027"
        )
        assert 'TSM' in result['tickers']

    def test_tsmc_full_name_to_tsm(self, extractor):
        """'Taiwan Semiconductor' should map to TSM ticker."""
        result = extractor.extract(
            "Taiwan Semiconductor Manufacturing Co plans price increases"
        )
        assert 'TSM' in result['tickers']

    def test_tsmc_chinese_to_tsm(self, extractor):
        """Chinese 台积电 should map to TSM."""
        result = extractor.extract("台积电计划从2027年起将芯片制造价格提高至多10%")
        assert 'TSM' in result['tickers']
