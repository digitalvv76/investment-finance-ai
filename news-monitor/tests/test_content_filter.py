"""Test content filter — geo-market + content quality gates."""
import pytest
from engine.content_filter import (
    geo_market_filter,
    content_quality_filter,
    _is_ccp_propaganda,
    _is_single_stock_noise,
    _is_political_gossip,
    _is_routine_foreign_politics,
)


class TestGeoMarketFilter:
    """Geographic / market relevance filter."""

    def test_non_us_politics_demoted(self):
        """Venezuela government collapse — no US connection → ×0.2"""
        text = "Venezuela government collapses as Maduro flees Caracas, military takes control"
        result = geo_market_filter(text)
        assert result == 0.2, f"Expected 0.2, got {result}"

    def test_iran_state_funeral_non_us(self):
        """Iran state funeral — domestic political, no US market impact → ×0.2"""
        text = "Iran holds state funeral for Khamenei, millions mourn in Tehran"
        result = geo_market_filter(text)
        assert result == 0.2, f"Expected 0.2, got {result}"

    def test_us_israel_iran_war_keeps_score(self):
        """US-Israel vs Iran conflict — directly affects US markets → ×1.0"""
        text = "US troops deployed as Israel strikes Iran nuclear facilities, oil supply threatened, S&P futures plunge"
        result = geo_market_filter(text)
        assert result == 1.0, f"Expected 1.0, got {result}"

    def test_iran_oil_sanctions_keeps_score(self):
        """Iran oil sanctions with US connection → ×1.0"""
        text = "White House imposes new sanctions on Iran oil exports, crude prices surge"
        result = geo_market_filter(text)
        assert result == 1.0, f"Expected 1.0, got {result}"

    def test_us_news_untouched(self):
        """Domestic US news passes through unaffected."""
        text = "Federal Reserve holds rates steady, S&P 500 rallies to new record"
        result = geo_market_filter(text)
        assert result == 1.0, f"Expected 1.0, got {result}"

    def test_non_us_no_political_action_ambiguous(self):
        """Country mentioned but no clear political action → ambiguous ×0.6"""
        text = "Venezuela coffee exports rise 15% amid improving weather"
        result = geo_market_filter(text)
        assert result == 0.6, f"Expected 0.6, got {result}"

    def test_global_systemic_country_keeps_score(self):
        """China/Japan/Germany are globally systemic → political+US link → ×1.0"""
        text = "Bank of Japan unexpectedly hikes rates, US Treasury yields spike, Nasdaq futures drop"
        result = geo_market_filter(text)
        assert result == 1.0, f"Expected 1.0, got {result}"

    def test_china_domestic_politics_demoted(self):
        """Chinese party news without US market link → ×0.15"""
        text = "国务院召开常务会议研究部署下半年经济工作 习近平总书记主持"
        result = geo_market_filter(text)
        assert result == 0.15, f"Expected 0.15, got {result}"

    def test_north_korea_missile_ambiguous(self):
        """North Korea without US connection → ×0.6 (not clearly political)"""
        text = "North Korea reports record harvest, food shortages ease"
        result = geo_market_filter(text)
        assert result == 0.6, f"Expected 0.6, got {result}"


class TestMilitaryConflictOverride:
    """Military conflict escalation overrides non-US political demotion."""

    def test_iran_missile_deployment_no_us_connector(self):
        """Iran deploys missiles near key shipping lane — military escalation → ×0.80"""
        text = "Iran deploys ballistic missiles to coastal launch sites, IRGC on heightened alert"
        result = geo_market_filter(text)
        assert result == 0.80, f"Expected 0.80, got {result}"

    def test_us_iran_naval_standoff_keeps_score(self):
        """US destroyers face off with IRGC — has US connector → ×1.0"""
        text = "US destroyers face off with IRGC speedboats near Strait of Hormuz"
        result = geo_market_filter(text)
        assert result == 1.0, f"Expected 1.0, got {result}"

    def test_iran_election_still_blocked(self):
        """Iran domestic election without military conflict → still ×0.2"""
        text = "Iran presidential election sees record turnout in Tehran"
        result = geo_market_filter(text)
        assert result == 0.2, f"Expected 0.2, got {result}"

    def test_north_korea_icbm_test(self):
        """North Korea ICBM test — military escalation → ×0.80"""
        text = "North Korea tests ICBM capable of reaching US mainland, Japan on high alert"
        result = geo_market_filter(text)
        assert result == 0.80, f"Expected 0.80, got {result}"

    def test_chinese_iran_military_exercise(self):
        """Chinese: Iran Revolutionary Guard military exercise → ×0.80"""
        text = "伊朗革命卫队在霍尔木兹海峡举行大规模军事演习，模拟封锁海峡"
        result = geo_market_filter(text)
        assert result == 0.80, f"Expected 0.80, got {result}"

    def test_iran_state_funeral_still_blocked(self):
        """Iran state funeral — domestic political, no military conflict → ×0.2"""
        text = "Iran holds state funeral for Khamenei, millions mourn in Tehran"
        result = geo_market_filter(text)
        assert result == 0.2, f"Expected 0.2, got {result}"

    def test_russia_military_exercise(self):
        """Belarus military mobilization near border — military escalation → ×0.80"""
        text = "Belarus begins large-scale military exercise near border, mobilizes reserves"
        result = geo_market_filter(text)
        assert result == 0.80, f"Expected 0.80, got {result}"


class TestContentQualityFilter:
    """Content quality / noise filter."""

    def test_trump_interview_demoted(self):
        """Political interview without tickers → ×0.30"""
        text = "President Donald Trump defends business dealings, his children in exclusive interview with CNBC"
        result = content_quality_filter(text, tickers_found="")
        assert result <= 0.30, f"Expected ≤0.30, got {result}"

    def test_trump_with_tickers_keeps(self):
        """Trump mentioned BUT with ticker match → passes"""
        text = "Trump defends tariff policy, says Apple moving production back to US"
        result = content_quality_filter(text, tickers_found="AAPL")
        assert result == 1.0, f"Expected 1.0, got {result}"

    def test_ccp_propaganda_demoted(self):
        """Chinese party meeting with zero market relevance → ×0.15"""
        text = "中国农业银行党委召开会议传达学习贯彻习近平总书记重要讲话精神"
        assert _is_ccp_propaganda(text.lower())

    def test_ccp_propaganda_with_market_link_passes(self):
        """Party news that mentions semiconductors → NOT flagged as propaganda"""
        text = "党委会议研究部署半导体芯片产业发展 英伟达合作项目获批"
        assert not _is_ccp_propaganda(text.lower())

    def test_a_share_limit_up_demoted(self):
        """A-share single stock limit-up → noise"""
        text = "A股：尾盘突变！605358立昂微涨停"
        assert _is_single_stock_noise(text.lower(), has_tickers=False)

    def test_single_stock_analyst_noise(self):
        """Analyst upgrade without multi-asset context → noise"""
        text = "Analyst upgrades Tesla to buy, raises price target to $450"
        assert _is_single_stock_noise(text.lower(), has_tickers=True)

    def test_single_stock_with_multi_asset_passes(self):
        """Stock movement WITH multi-asset breadth → NOT noise"""
        text = "Tesla surges 12% as S&P 500 hits record, Treasury yields fall, gold rallies"
        assert not _is_single_stock_noise(text.lower(), has_tickers=True)

    def test_state_funeral_routine_politics(self):
        """State funeral with no US connection → routine foreign politics"""
        text = "Nation holds state funeral for former president, thousands attend memorial service"
        assert _is_routine_foreign_politics(text.lower(), has_tickers=False)

    def test_state_funeral_with_us_link_passes(self):
        """State funeral but mentions US → NOT routine foreign politics"""
        text = "State funeral for key US ally, Secretary of State attends memorial service"
        assert not _is_routine_foreign_politics(text.lower(), has_tickers=False)

    def test_strategic_event_bypasses_all(self):
        """Strategic event (gov investment) bypasses ALL content filters → ×1.0"""
        text = "美国政府入股量子计算公司，拨款50亿美元建设国家量子实验室"
        result = content_quality_filter(text, has_strategic=True)
        assert result == 1.0, f"Expected 1.0, got {result}"

    def test_nvda_endorsement_untouched(self):
        """Jensen Huang endorsement should pass clean."""
        text = "Jensen Huang calls Marvell the next trillion-dollar company, stock surges 32%"
        result = content_quality_filter(text, tickers_found="MRVL")
        assert result == 1.0, f"Expected 1.0, got {result}"

    def test_clean_macro_news_untouched(self):
        """Clean macro news passes both filters unscathed."""
        text = "CPI data beats expectations, S&P 500 futures rise, 10-year yield jumps to 4.5%"
        geo = geo_market_filter(text)
        quality = content_quality_filter(text, tickers_found="SPY")
        assert geo == 1.0
        assert quality == 1.0


class TestCombinedPipeline:
    """End-to-end combined filter scenarios."""

    def test_marvell_jensen_huang_endorsement(self):
        """Marvell被黄仁勋力挺 → 满分通过"""
        text = "Jensen Huang declares Marvell is the next trillion-dollar company, shares soar 32.52%"
        geo = geo_market_filter(text)
        quality = content_quality_filter(text, tickers_found="MRVL")
        combined = geo * quality
        assert combined == 1.0, f"Expected 1.0, got {combined}"

    def test_china_agricultural_bank_party_meeting(self):
        """中国农业银行党委会 → 被彻底压制"""
        text = "中国农业银行党委召开会议传达学习贯彻习近平总书记重要讲话精神"
        geo = geo_market_filter(text)
        quality = content_quality_filter(text)
        combined = geo * quality
        # Either geo_filter or quality_filter should heavily demote this
        assert combined <= 0.15, f"Expected ≤0.15, got {combined}"

    def test_a_share_stock_limit_up(self):
        """A股单票涨停 → 大幅降权"""
        text = "A股：尾盘突变！605358立昂微涨停，封单超10万手"
        geo = geo_market_filter(text)
        quality = content_quality_filter(text)
        combined = geo * quality
        # Should be heavily demoted by quality filter
        assert combined <= 0.30, f"Expected ≤0.30, got {combined}"

    def test_trump_interview_defense(self):
        """Trump CNBC采访辩解 → 降权"""
        text = "President Donald Trump defends business dealings, his children in exclusive interview with CNBC"
        geo = geo_market_filter(text)
        quality = content_quality_filter(text)
        combined = geo * quality
        # Trump is a US entity so geo passes, but quality should catch it
        assert combined <= 0.30, f"Expected ≤0.30, got {combined}"

    def test_us_gov_quantum_investment(self):
        """美国政府入股量子计算公司 → 满分通过"""
        text = "美国政府宣布入股量子计算行业三家公司，DARPA拨款120亿美元"
        geo = geo_market_filter(text)
        quality = content_quality_filter(text, tickers_found="IONQ,QBTS", has_strategic=True)
        combined = geo * quality
        assert combined == 1.0, f"Expected 1.0, got {combined}"


class TestChineseLanguageDemotion:
    """Chinese-language content is supplementary — must earn full weight."""

    def test_chinese_no_us_signal_demoted(self):
        """Chinese text with no US market signal → ×0.5"""
        from engine.content_filter import _is_chinese_dominant, _has_us_market_signal
        text = "国内成品油价格迎年内最大降幅 汽油每吨下调950元"
        assert _is_chinese_dominant(text.lower())
        assert not _has_us_market_signal(text.lower(), has_tickers=False)

    def test_chinese_with_us_stock_passes(self):
        """Chinese text mentioning NVIDIA → passes signal check"""
        from engine.content_filter import _has_us_market_signal
        assert _has_us_market_signal("英伟达股价暴跌8% 拖累纳斯达克指数 市场担忧AI泡沫", has_tickers=False)

    def test_chinese_with_ticker_passes(self):
        """Chinese text with ticker match → language check bypassed"""
        from engine.content_filter import _has_us_market_signal
        assert _has_us_market_signal("特斯拉发布新款车型", has_tickers=True)

    def test_english_not_cjk_dominant(self):
        """English text must NOT be flagged as Chinese-dominant"""
        from engine.content_filter import _is_chinese_dominant
        assert not _is_chinese_dominant("Federal Reserve holds rates steady")
        assert not _is_chinese_dominant("Apple stock surges 5% on earnings beat")

    def test_chinese_macro_with_us_link(self):
        """Chinese text about US macro → has US market signal"""
        from engine.content_filter import _has_us_market_signal
        assert _has_us_market_signal("美联储紧急降息50基点 标普500暴涨", has_tickers=False)

    def test_mixed_cn_en_not_cjk_dominant(self):
        """Mixed CN/EN with mostly English → not dominant Chinese"""
        from engine.content_filter import _is_chinese_dominant
        text = "NVIDIA stock crashes 8%, NASDAQ plunges, 英伟达市值蒸发"
        assert not _is_chinese_dominant(text.lower())


class TestMajorStockEvents:
    """Single-stock events that ARE major enough to warrant push."""

    def test_megacap_surge_30_percent(self):
        """TSLA surges 30% — major event, NOT noise"""
        from engine.content_filter import _is_single_stock_noise, _is_major_stock_event
        text = "Tesla stock surges 32% after Q2 deliveries blow past estimates"
        assert _is_major_stock_event(text.lower(), has_tickers=True)
        assert not _is_single_stock_noise(text.lower(), has_tickers=True)

    def test_fda_approval_passes(self):
        """FDA accelerated approval for biotech — major event"""
        from engine.content_filter import _is_single_stock_noise, _is_major_stock_event
        text = "FDA grants accelerated approval to Moderna's personalized cancer vaccine"
        assert _is_major_stock_event(text.lower(), has_tickers=True)
        assert not _is_single_stock_noise(text.lower(), has_tickers=True)

    def test_billion_dollar_acquisition_passes(self):
        """$5B acquisition — major event, NOT noise"""
        from engine.content_filter import _is_single_stock_noise, _is_major_stock_event
        text = "Microsoft acquires AI startup for $5.2 billion in all-cash deal"
        assert _is_major_stock_event(text.lower(), has_tickers=True)
        assert not _is_single_stock_noise(text.lower(), has_tickers=True)

    def test_ceo_resignation_megacap(self):
        """NVIDIA CEO resignation would be major — not noise"""
        from engine.content_filter import _is_single_stock_noise, _is_major_stock_event
        text = "NVIDIA CEO steps down after 30 years, shares tumble 15%"
        assert _is_major_stock_event(text.lower(), has_tickers=True)
        assert not _is_single_stock_noise(text.lower(), has_tickers=True)

    def test_market_cap_wipeout(self):
        """Huge market cap loss — major event"""
        from engine.content_filter import _is_major_stock_event
        text = "Apple loses $200 billion in market cap after guidance cut"
        assert _is_major_stock_event(text.lower(), has_tickers=True)

    def test_analyst_upgrade_still_noise(self):
        """Ordinary analyst upgrade without major move → still noise"""
        from engine.content_filter import _is_single_stock_noise
        text = "Analyst upgrades Tesla to buy, raises price target to $450"
        assert _is_single_stock_noise(text.lower(), has_tickers=True)

    def test_ceo_stock_sale_still_noise(self):
        """CEO sells routine shares → still noise"""
        from engine.content_filter import _is_single_stock_noise
        text = "Crowdstrike CEO George Kurtz sells $1.94m in CRWD stock"
        assert _is_single_stock_noise(text.lower(), has_tickers=True)

    def test_small_price_move_still_noise(self):
        """Stock up 3% → still noise"""
        from engine.content_filter import _is_single_stock_noise
        text = "Netflix shares up 3% on subscriber growth optimism"
        assert _is_single_stock_noise(text.lower(), has_tickers=True)

    def test_megacap_without_major_event_still_noise(self):
        """Apple mentioned but no major event → can still be noise"""
        from engine.content_filter import _is_single_stock_noise
        text = "Apple stock edges higher, analysts remain cautious"
        # No massive move, no FDA, no M&A, no CEO change → noise
        assert _is_single_stock_noise(text.lower(), has_tickers=True)
