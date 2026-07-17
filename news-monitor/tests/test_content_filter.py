"""Test content filter — geo-market + content quality gates."""
import pytest
from engine.content_filter import (
    geo_market_filter,
    content_quality_filter,
    geo_tier_weight,
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


class TestGeoTierWeight:
    """Geo-tier relevance weighting — US=1.0, non-US=0.25, unclassified=1.0."""

    # ── Tier: US (1.0) ──────────────────────────────────────────────

    def test_us_fed_news(self):
        assert geo_tier_weight("Federal Reserve holds rates steady, S&P 500 rallies", []) == 1.0

    def test_us_fomc_minutes(self):
        assert geo_tier_weight("FOMC minutes show broad support for holding rates", []) == 1.0

    def test_us_powell_speech(self):
        assert geo_tier_weight("Powell says Fed is in no rush to cut rates", []) == 1.0

    def test_us_jobless_claims(self):
        assert geo_tier_weight("US jobless claims fall to 210k, labor market remains tight", []) == 1.0

    def test_us_nonfarm_payrolls(self):
        assert geo_tier_weight("Nonfarm Payrolls surge 275k in June, beating 190k estimate", []) == 1.0

    def test_us_cpi_explicit(self):
        assert geo_tier_weight("US CPI rises 3.2%, above 3.1% consensus estimate", []) == 1.0

    def test_us_retail_sales(self):
        assert geo_tier_weight("US retail sales unexpectedly drop 0.3% in June", []) == 1.0

    def test_us_wall_street(self):
        assert geo_tier_weight("Wall Street bonuses hit record $50B as dealmaking surges", []) == 1.0

    def test_us_chinese_language(self):
        assert geo_tier_weight("美联储紧急降息50基点 纳斯达克暴涨 标普500创新高", []) == 1.0

    def test_us_chinese_language_nonfarm(self):
        assert geo_tier_weight("美国非农数据大超预期 初请失业金人数降至20万以下", []) == 1.0

    # ── Tier: Non-US (0.25) — Europe ────────────────────────────────

    def test_ecb_rate_decision(self):
        assert geo_tier_weight("ECB cuts rates by 25bps as Eurozone inflation finally eases", []) == 0.25

    def test_lagarde_speech(self):
        assert geo_tier_weight("Lagarde signals more rate cuts ahead as growth weakens", []) == 0.25

    def test_uk_cpi(self):
        assert geo_tier_weight("UK inflation falls to 2.0% target, Bank of England eyes rate cut", []) == 0.25

    def test_boe_decision(self):
        assert geo_tier_weight("BoE holds rates at 5.25% in split 7-2 vote", []) == 0.25

    def test_germany_gdp(self):
        assert geo_tier_weight("German GDP contracts 0.3% in Q2, DAX drops 2%", []) == 0.25

    def test_france_political(self):
        assert geo_tier_weight("French bonds sell off as Paris gridlock threatens fiscal stability", []) == 0.25

    def test_europe_chinese_language(self):
        assert geo_tier_weight("欧洲央行维持利率不变 拉加德表示不急于降息 欧元区PMI持续萎缩", []) == 0.25

    # ── Tier: Non-US (0.25) — Japan ─────────────────────────────────

    def test_boj_hike(self):
        assert geo_tier_weight("Bank of Japan unexpectedly hikes rates to 0.5%, yen surges 3%", []) == 0.25

    def test_japan_gdp(self):
        assert geo_tier_weight("Japan GDP growth accelerates to 3.1% annualized in Q2", []) == 0.25

    def test_nikkei_drop(self):
        assert geo_tier_weight("Nikkei plunges 5% as yen strength hits exporters", []) == 0.25

    # ── Tier: Non-US (0.25) — China ─────────────────────────────────

    def test_china_gdp(self):
        assert geo_tier_weight("China Q2 GDP grows 4.7%, misses 5.1% forecast", []) == 0.25

    def test_pboc_rate_cut(self):
        assert geo_tier_weight("PBOC cuts MLF rate by 10bps to boost flagging economy", []) == 0.25

    def test_china_chinese_language(self):
        assert geo_tier_weight("中国央行降准50基点释放1万亿流动性 人民币跌破7.3", []) == 0.25

    def test_provincial_cpi_excluded(self):
        """Guangdong provincial CPI → non-US (0.25). Would be 1.0 if white-listed."""
        assert geo_tier_weight("广东居民消费价格同比上涨2.1% 食品价格领涨", []) == 0.25

    # ── Tier: Non-US (0.25) — Korea / Canada / Australia ─────────────

    def test_korea_exports(self):
        assert geo_tier_weight("South Korea exports surge 12% in June, chip demand strong", []) == 0.25

    def test_canada_cpi(self):
        assert geo_tier_weight("Canada CPI unexpectedly rises to 3.4%, BoC rate cut hopes fade", []) == 0.25

    def test_rba_decision(self):
        assert geo_tier_weight("RBA holds rates at 4.35%, warns inflation still too high", []) == 0.25

    # ── Tier: Non-US (0.25) — India / Brazil / emerging ─────────────

    def test_india_gdp(self):
        assert geo_tier_weight("India GDP growth slows to 6.5%, RBI under pressure to cut", []) == 0.25

    def test_brazil_selic(self):
        assert geo_tier_weight("Brazil central bank BCB raises Selic to 12.25%", []) == 0.25

    def test_turkey_inflation(self):
        assert geo_tier_weight("Turkey inflation surges to 75% as lira collapses", []) == 0.25

    def test_russia_ruble(self):
        assert geo_tier_weight("Russian ruble hits 100 per dollar, CBR considers emergency hike", []) == 0.25

    def test_saudi_oil(self):
        assert geo_tier_weight("Saudi Arabia signals OPEC+ may delay output increase", []) == 0.25

    # ── Ticker exemption ─────────────────────────────────────────────

    def test_ticker_exempts_geo_tier(self):
        """Company news with ticker → 1.0 regardless of geography."""
        assert geo_tier_weight("Sony reports record profit, Japan sales surge 40%", ["SONY"]) == 1.0

    def test_tsmc_earnings_exempt(self):
        """TSMC earnings is company news, not Taiwan macro → 1.0"""
        assert geo_tier_weight("TSMC beats Q2 estimates, Taiwan fab expansion on track", ["TSMC"]) == 1.0

    def test_no_ticker_no_exempt(self):
        """Same Japan text without ticker → non-US weight applies."""
        assert geo_tier_weight("Japan GDP beats expectations, Nikkei rallies", []) == 0.25

    def test_empty_tickers_list_no_exempt(self):
        """Empty ticker list passed explicitly → tiering applies."""
        assert geo_tier_weight("ECB minutes show broad hawkish tilt", []) == 0.25

    # ── US priority ──────────────────────────────────────────────────

    def test_us_wins_over_non_us(self):
        """When both US and non-US mentioned, US signal wins → 1.0"""
        assert geo_tier_weight(
            "S&P 500 falls as Japan GDP miss spooks global investors, Fed speakers due today",
            [],
        ) == 1.0

    def test_nasdaq_plus_china_still_us(self):
        """NASDAQ mention dominates China mention → 1.0"""
        assert geo_tier_weight(
            "NASDAQ futures drop on China trade war fears, tech stocks slide",
            [],
        ) == 1.0

    # ── Unclassified (1.0) ───────────────────────────────────────────

    def test_global_markets_unclassified(self):
        assert geo_tier_weight("Global markets rally on trade deal optimism", []) == 1.0

    def test_bitcoin_unclassified(self):
        assert geo_tier_weight("Bitcoin surges past $100,000 on spot ETF inflows", []) == 1.0

    def test_gold_unclassified(self):
        assert geo_tier_weight("Gold hits new all-time high above $3,000", []) == 1.0

    def test_oil_global_unclassified(self):
        """Oil price move without country mention → global commodity → 1.0"""
        assert geo_tier_weight("Oil prices surge 5% on supply disruption fears", []) == 1.0

    def test_blank_headline(self):
        assert geo_tier_weight("", []) == 1.0
        assert geo_tier_weight("", ["AAPL"]) == 1.0  # ticker still exempts

    # ── Edge cases ───────────────────────────────────────────────────

    def test_bare_cpi_without_country(self):
        """'CPI data surprises' without country → unclassified (not US, not non-US)"""
        assert geo_tier_weight("CPI data surprises markets, rate cut hopes rise", []) == 1.0

    def test_bare_gdp_without_country(self):
        """'GDP beats estimates' without country → unclassified"""
        assert geo_tier_weight("GDP growth beats estimates at 3.2%", []) == 1.0

    def test_provincial_city_alone(self):
        """Shanghai mentioned without China context → non-US"""
        assert geo_tier_weight("Shanghai composite index falls 2% on deleveraging concerns", []) == 0.25

    # ── Adversarial-review fixes ─────────────────────────────────────

    def test_us_and_china_trade_talks(self):
        r"""'U.S. and China trade talks' — US signal must win (was broken: function
        word 'and' blocked the context-list match, now standalone \bU\.?S\.?\b catches it)."""
        assert geo_tier_weight("U.S. and China trade talks resume in Beijing", []) == 1.0

    def test_china_gdp_chinese_language(self):
        """'中国GDP增长4.7%' — '中国' now in CJK non-US list → 0.25"""
        assert geo_tier_weight("中国GDP增长4.7% 低于市场预期", []) == 0.25

    def test_china_stock_market_chinese(self):
        """'中国股市暴跌' → 0.25 (was 1.0 before adding 中国 to CJK list)"""
        assert geo_tier_weight("中国股市今日暴跌 上证指数失守3000点", []) == 0.25

    def test_china_inflation_chinese(self):
        """'中国通胀数据公布' → 0.25"""
        assert geo_tier_weight("中国通胀数据公布 CPI同比上涨2.5%", []) == 0.25

    def test_us_and_will_china(self):
        r"""'U.S. will impose tariffs on China' — 'will' function word blocked old
        pattern, now standalone \bU\.?S\.?\b catches it → 1.0"""
        assert geo_tier_weight("U.S. will impose new tariffs on China imports", []) == 1.0

    def test_snowflake_tokyo_no_ticker(self):
        """Snowflake in Tokyo without ticker extraction → non-US (known limitation:
        EntityExtractor name→ticker mapping doesn't cover all companies)"""
        assert geo_tier_weight("Snowflake opens Tokyo office as Japan business grows", []) == 0.25

    def test_tsmc_taiwan_no_ticker_still_non_us(self):
        """'Taiwan GDP beats on TSMC exports' without ticker → non-US (macro, not company news)"""
        assert geo_tier_weight("Taiwan GDP beats expectations on strong TSMC exports", []) == 0.25
