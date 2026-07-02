"""Tests for strategic relationship detector."""
import pytest
from engine.strategic_detector import StrategicDetector, StrategicMatch


@pytest.fixture
def detector():
    return StrategicDetector()


# ---------------------------------------------------------------------------
# Government intervention
# ---------------------------------------------------------------------------

def test_us_gov_invests_in_company(detector):
    text = "美国政府通过CHIPS Act向英特尔注资85亿美元，用于亚利桑那州芯片工厂建设"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].category == "gov_intervention"
    assert matches[0].confidence >= 0.65


def test_energy_department_subsidizes(detector):
    text = "Department of Energy announced $2 billion in grants for EV battery manufacturing"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].category == "gov_intervention"


def test_dod_awards_contract(detector):
    text = "国防部授予微软100亿美元云计算合同"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].category == "gov_intervention"


def test_chips_act_funding(detector):
    text = "芯片法案新一轮拨款落地，台积电亚利桑那厂获得数十亿美元补贴"
    matches = detector.detect(text)
    assert len(matches) >= 1


def test_inflation_reduction_act(detector):
    text = "Inflation Reduction Act drives $50B in clean energy investments across US"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].category == "gov_intervention"


def test_white_house_executive_order(detector):
    text = "白宫签署行政命令限制对华AI芯片出口"
    matches = detector.detect(text)
    assert len(matches) >= 1


def test_ftc_approves_merger(detector):
    text = "FTC批准亚马逊收购Whole Foods"
    matches = detector.detect(text)
    assert len(matches) >= 1


# ---------------------------------------------------------------------------
# NVIDIA / Jensen Huang investment
# ---------------------------------------------------------------------------

def test_nvidia_invests_in_startup(detector):
    text = "英伟达宣布入股AI初创公司Anthropic，投资金额达数亿美元"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].category == "nvda_investment"


def test_jensen_huang_acquires(detector):
    text = "Jensen Huang leads $500M investment round in quantum computing startup"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].category == "nvda_investment"


def test_nvidia_strategic_investment(detector):
    text = "NVIDIA战略入股自动驾驶公司Wayve，布局具身智能"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].category == "nvda_investment"


def test_nvda_acquires(detector):
    text = "NVDA完成对AI芯片设计公司Mellanox的收购"
    matches = detector.detect(text)
    assert len(matches) >= 1


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def test_high_confidence_nvda_jensen(detector):
    """Jensen Huang + 入股 should get high confidence."""
    text = "黄仁勋个人入股AI算力公司CoreWeave，投资金额1亿美元"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].confidence >= 0.80


def test_low_confidence_generic(detector):
    """Generic regulator + 发布 without specifics should get lower confidence."""
    text = "监管机构发布新的行业指导意见"
    matches = detector.detect(text)
    # Should either not match or have lower confidence
    if matches:
        assert matches[0].confidence <= 0.70


def test_high_confidence_chips_act(detector):
    """CHIPS Act + 资助 should be high confidence."""
    text = "CHIPS Act资助英特尔建设新一代芯片工厂"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].confidence >= 0.70


# ---------------------------------------------------------------------------
# Negative cases (should NOT trigger)
# ---------------------------------------------------------------------------

def test_irrelevant_news(detector):
    """Normal market news should not trigger strategic alerts."""
    text = "Apple reports record quarterly earnings, stock up 3%"
    matches = detector.detect(text)
    assert len(matches) == 0


def test_routine_earnings(detector):
    text = "NVIDIA下周三发布财报，市场预期营收增长20%"
    matches = detector.detect(text)
    assert len(matches) == 0


def test_normal_acquisition(detector):
    """Company acquisition WITHOUT government or NVIDIA involvement."""
    text = "微软收购游戏公司Activision Blizzard"
    matches = detector.detect(text)
    assert len(matches) == 0


def test_empty_text(detector):
    assert len(detector.detect("")) == 0
    assert len(detector.detect("短")) == 0


# ---------------------------------------------------------------------------
# has_strategic_event shortcut
# ---------------------------------------------------------------------------

def test_has_strategic_event_true(detector):
    assert detector.has_strategic_event("美国政府入股台积电")


def test_has_strategic_event_false(detector):
    assert not detector.has_strategic_event("AAPL股价上涨3%")


# ---------------------------------------------------------------------------
# Ticker extraction
# ---------------------------------------------------------------------------

def test_extract_tickers_from_strategic_text(detector):
    text = "美国政府通过CHIPS Act向INTC注资85亿美元，同时台积电TSM和三星也获得补贴"
    known = {"INTC", "TSM", "NVDA", "AMD", "AAPL"}
    tickers = detector.extract_mentioned_tickers(text, known)
    assert "INTC" in tickers
    assert "TSM" in tickers
    assert "AMD" not in tickers  # Not mentioned


def test_extract_tickers_none_mentioned(detector):
    text = "美国政府出台新能源补贴政策"
    known = {"TSLA", "RIVN", "LCID"}
    tickers = detector.extract_mentioned_tickers(text, known)
    assert len(tickers) == 0


# ---------------------------------------------------------------------------
# Multiple matches in one text
# ---------------------------------------------------------------------------

def test_multiple_strategic_matches(detector):
    text = ("美国政府通过CHIPS Act向英特尔拨款100亿，"
            "同时英伟达宣布战略入股AI芯片初创公司Cerebras")
    matches = detector.detect(text)
    assert len(matches) >= 2
    categories = {m.category for m in matches}
    assert "gov_intervention" in categories
    assert "nvda_investment" in categories


# ---------------------------------------------------------------------------
# Chinese text (mixed)
# ---------------------------------------------------------------------------

def test_mixed_cn_en(detector):
    text = "US Government announced CHIPS Act funding for TSMC Arizona fab"
    matches = detector.detect(text)
    assert len(matches) >= 1


def test_chinese_policy(detector):
    text = "财政部出台新的芯片产业扶持政策，对半导体企业给予税收优惠"
    matches = detector.detect(text)
    assert len(matches) >= 1


def test_chinese_nvda_investment(detector):
    text = "英伟达入股国产GPU公司摩尔线程，布局中国AI芯片市场"
    matches = detector.detect(text)
    assert len(matches) >= 1
    assert matches[0].category == "nvda_investment"
