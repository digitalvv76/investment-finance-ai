"""Content filter — pre-scoring gate that demotes non-US-market noise.

Two-stage filter that runs before PriorityScorer:

  A) geo_market_filter    — "Does this event affect US capital markets?"
  B) content_quality_filter — "Is this signal or noise?"

Multipliers are combined and applied to the raw priority_score in FastLane.
"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage A — Geographic / market relevance
# ---------------------------------------------------------------------------

# Non-US countries/regions whose POLITICAL events rarely impact US equities.
# We don't block the country entirely — only when the text is about politics,
# not when it's about oil, semiconductors, or other globally-traded assets.
_NON_US_POLITICAL_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(rf'\b({c})\b', re.IGNORECASE), c) for c in [
        "Venezuela", "Caracas", "Maduro",
        "Iran", "Tehran", "Khamenei", "Ayatollah",
        "North Korea", "Pyongyang", "Kim Jong",
        "Myanmar", "Burma", "Naypyidaw",
        "Sudan", "Khartoum", "Darfur",
        "Belarus", "Minsk", "Lukashenko",
        "Cuba", "Havana",
        "Syria", "Damascus",
        "Afghanistan", "Kabul", "Taliban",
        "Somalia", "Mogadishu",
        "Yemen", "Sanaa",
        "Libya", "Tripoli",
        "Zimbabwe", "Harare",
        "Congo", "Kinshasa",
    ]
] + [
    # Chinese party/government entities — detect WITHOUT requiring "China" in text.
    # No \b because Chinese characters don't have ASCII word boundaries.
    (re.compile(rf'({re.escape(kw)})'), "China-CCP") for kw in [
        "总书记", "中共中央", "政治局常委", "国务院",
        "全国人大", "全国政协", "中央纪委",
        "中央委员会", "中央经济工作会议",
    ]
] + [
    # Chinese names for non-US countries — same countries as English list
    (re.compile(rf'({re.escape(kw)})'), c) for kw, c in [
        ("委内瑞拉", "Venezuela"),
        ("加拉加斯", "Venezuela"),
        ("马杜罗", "Venezuela"),
        ("伊朗", "Iran"),
        ("德黑兰", "Iran"),
        ("哈梅内伊", "Iran"),
        ("朝鲜", "North Korea"),
        ("平壤", "North Korea"),
        ("金正恩", "North Korea"),
        ("缅甸", "Myanmar"),
        ("古巴", "Cuba"),
        ("叙利亚", "Syria"),
        ("阿富汗", "Afghanistan"),
        ("塔利班", "Taliban"),
        ("苏丹", "Sudan"),
        ("白俄罗斯", "Belarus"),
        ("卢卡申科", "Belarus"),
    ]
]

# Political event keywords that, when paired with a non-US country,
# indicate the news does NOT affect US equities.
_NON_US_POLITICAL_ACTIONS = [
    "coup", "d'état", "dictator", "regime", "junta",
    "state funeral", "national mourning", "overthrow",
    "insurgency", "rebel", "militia", "civil war",
    "constitutional crisis", "parliament", "dissolve",
    "prime minister", "president", "election", "protest",
    "refugee", "humanitarian", "famine",
    "rigged", "crackdown", "political prisoner",
    "general strike", "curfew", "martial law",
    "succession", "coronation", "royal",
    "union", "parliamentary",
    "government collapse", "collapses",
    # Chinese political actions (non-US)
    "垮台", "流亡", "国葬", "政变", "军政府",
    "军方接管", "内战", "叛军", "游击队",
    "人道主义危机", "饥荒", "难民",
    "戒严", "宵禁", "镇压", "政治犯",
    # Chinese domestic politics that don't affect US markets
    "党委", "全会", "总书记", "政治局", "国务院",
    "中央委员会", "党代会", "人大", "政协",
    "团拜", "民主生活会", "主题教育",
    "学习贯彻", "重要讲话精神", "指示",
    "脱贫攻坚", "乡村振兴", "共同富裕",
    "中国特色", "两个维护", "四个意识",
]

# Keywords that indicate US market connection even when paired
# with a non-US country — these PREVENT the demotion.
_US_MARKET_CONNECTORS = [
    # US military / geopolitical
    "US troops", "American forces", "US military", "Pentagon",
    "美军", "美国军队", "五角大楼",
    # Global commodities / supply chains
    "oil supply", "oil price", "crude", "OPEC", "barrel",
    "油价", "原油", "供应中断", "欧佩克",
    "sanctions", "制裁", "embargo",
    "chip supply", "semiconductor", "rare earth",
    "芯片", "半导体",
    # US equities / indices
    "S&P", "NASDAQ", "Dow", "NYSE",
    "US stock", "US equity", "Wall Street",
    "美股", "美国股市",
    # US policy reaction
    "White House", "白宫", "Congress", "国会",
    "Trump", "Biden", "US administration",
    # Global systemic
    "contagion", "systemic", "IMF", "World Bank",
    "default", "sovereign debt",
    # Strait of Hormuz / global shipping
    "Strait of Hormuz", "Bab el-Mandeb", "Suez",
    "oil tanker", "LNG", "sea lane",
]

# Countries / regions whose economic/political events DO affect US markets
# (No demotion for these — they're globally systemic)
_GLOBAL_SYSTEMIC_COUNTRIES = [
    "China", "Japan", "Germany", "UK", "United Kingdom",
    "France", "EU", "European Union", "ECB",
    "Canada", "Mexico", "South Korea", "Taiwan",
    "India", "Brazil", "Australia", "Italy",
    "Saudi Arabia", "UAE", "Israel",
    "Russia", "Ukraine",
    "中国", "日本", "德国", "英国", "法国",
    "欧盟", "加拿大", "韩国", "台湾",
    "印度", "巴西", "澳大利亚", "意大利",
    "沙特", "阿联酋", "以色列",
    "俄罗斯", "乌克兰",
]


def geo_market_filter(text: str, source: str = "") -> float:
    """Check whether a non-US political event affects US capital markets.

    Returns a multiplier (0.0–1.0) that will be applied to the raw
    priority score.

    1.0  = clearly affects US markets (or not about a non-US country)
    0.6  = ambiguous — non-US country but may have global impact
    0.2  = clearly a domestic political event in a non-US country
    0.1  = Chinese domestic political propaganda with zero market relevance
    """
    if not text:
        return 1.0

    text_lower = text.lower()

    # --- Step 1: Is this about a non-US country? ---
    matched_country = None
    for pattern, country in _NON_US_POLITICAL_PATTERNS:
        if pattern.search(text_lower):
            matched_country = country
            break

    if matched_country is None:
        # Not about a non-US political hot-spot — no demotion
        return 1.0

    # --- Step 2: Is it a globally-systemic country? ---
    # Israel + Iran = US market impact (oil, defense, geopolitics)
    # But "Iran state funeral" alone = NOT US market impact
    if matched_country.lower() in [c.lower() for c in _GLOBAL_SYSTEMIC_COUNTRIES]:
        # Globally systemic — but check if the EVENT itself is political noise
        has_political_action = any(
            kw.lower() in text_lower for kw in _NON_US_POLITICAL_ACTIONS
        )
        has_us_connector = any(
            kw.lower() in text_lower for kw in _US_MARKET_CONNECTORS
        )
        if has_political_action and not has_us_connector:
            # E.g., "UK parliament dissolved" or "China party congress"
            # Global countries get a milder demotion than non-global ones
            if matched_country.lower() in ("china", "中国"):
                # Chinese domestic politics with no US connection
                return 0.15
            return 0.4
        # Global country + US connection → keep
        return 1.0

    # --- Step 3: Non-US country, non-global → check for US connection ---
    has_political_action = any(
        kw.lower() in text_lower for kw in _NON_US_POLITICAL_ACTIONS
    )
    has_us_connector = any(
        kw.lower() in text_lower for kw in _US_MARKET_CONNECTORS
    )

    if has_us_connector:
        # E.g., "Venezuela oil sanctions → US refinery impact"
        return 1.0

    if has_political_action:
        # E.g., "Venezuela government collapses" with no US connection
        multiplier = 0.15 if matched_country == "China-CCP" else 0.2
        logger.debug("Geo-filter: NON-US politics '%s' → ×%.2f", matched_country, multiplier)
        return multiplier

    # Ambiguous — non-US country mentioned but unclear if political
    return 0.6


# ---------------------------------------------------------------------------
# Geo-tier weight — economic relevance by geography for US-centric investing
# ---------------------------------------------------------------------------
# SEPARATE from geo_market_filter() above, which handles political noise
# demotion.  This function classifies news by geographic focus and applies
# a relevance multiplier: US=1.0, non-US=0.25, unclassified=1.0.
#
# Principle: user invests primarily in US stocks.  Non-US macro news
# (ECB, BOJ, China GDP, etc.) is basically never pushed unless it is an
# extreme outlier event (raw_score ≈ 1.0).

# ── US-tier patterns ─────────────────────────────────────────────────
# Only patterns that EXPLICITLY signal US context.  Do NOT include bare
# macro indicator names (CPI/PPI/GDP/PMI/ISM) — those appear globally
# and would false-match "UK GDP", "Eurozone PMI" etc.

_US_TIER_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        # Federal Reserve / monetary policy
        r'\bFederal\s+Reserve\b', r'\bthe\s+Fed\b', r'\bFOMC\b',
        r'\b(?:Jerome\s+)?Powell\b', r'\bWarsh\b',
        # US market indices
        r'\bS&P\s*500\b', r'\bSPX\b', r'\bNASDAQ\b', r'\bNDX\b',
        r'\bNYSE\b', r'\bDow\s+Jones\b',
        # US government institutions
        r'\bWhite\s+House\b', r'\bCongress\b', r'\bSenate\b',
        r'\b(?:US\s+)?Treasury\s+Department\b', r'\bUS\s+Treasury\b',
        r'\bSEC\b',
        # US financial places
        r'\bWall\s+Street\b', r'\bSilicon\s+Valley\b',
        # US dollar / index
        r'\bDXY\b', r'\bdollar\s+index\b',
        # US-specific labour-market releases (unambiguously US)
        r'\bjobless\s+claims\b', r'\binitial\s+claims\b',
        r'\bcontinuing\s+claims\b', r'\bnonfarm\s+payrolls?\b',
        r'\bNFP\b',
        # US-specific housing / mortgage
        r'\bMBA\s+mortgage\b', r'\bFreddie\s+Mac\b', r'\bFannie\s+Mae\b',
        # Regional Fed surveys
        r'\bPhilly\s+Fed\b', r'\bEmpire\s+State\b',
        r'\bRichmond\s+Fed\b', r'\bDallas\s+Fed\b', r'\bChicago\s+PMI\b',
        # Explicit US qualifier + macro indicator
        r'\bUS\s+CPI\b', r'\bUS\s+PPI\b', r'\bUS\s+GDP\b',
        r'\bUS\s+PMI\b', r'\bUS\s+ISM\b',
        r'\bUS\s+consumer\s+(?:confidence|sentiment|spending)\b',
        r'\bUS\s+retail\s+sales\b', r'\bUS\s+manufacturing\b',
        r'\bUS\s+services\b', r'\bUS\s+industrial\s+production\b',
        r'\bUS\s+factory\s+orders\b', r'\bUS\s+trade\s+(?:deficit|balance)\b',
        r'\bUS\s+housing\s+starts\b', r'\bUS\s+existing\s+home\b',
        r'\bUS\s+new\s+home\b', r'\bUS\s+durable\s+goods\b',
        # Standalone "US" / "U.S." followed by a market-context word
        r'\bU\.?S\.?\s+(?:stock|market|econom|government|trade|tariff|'
        r'regulat|consumer|business|housing|job|inflat|data|report|index|'
        r'bond|yield|equity|fund|investor|dollar|treasury|fed|central\s+bank|'
        r'growth|outlook|recession|sentiment|spending|earnings|corporate)',
        # Standalone "US" / "U.S." anywhere in the headline (catch function-word
        # bridges like "U.S. and China trade talks").  Checked AFTER the
        # qualified patterns above so those take priority in logging/debugging.
        r'\bU\.?S\.?\b',
        # "American" / "America" in economic context
        r'\bAmerican\s+(?:economy|market|consumer|business|manufacturing)\b',
    ]
]

# Chinese-language US-tier keywords (substring match on original CJK text)
_US_TIER_CJK: list[str] = [
    "美联储", "联邦储备", "鲍威尔", "沃尔什", "联储主席",
    "标普", "纳斯达克", "道琼斯", "纽交所", "纽约证券交易所",
    "白宫", "美国国会", "美财政部", "美国财政部",
    "非农", "初请失业金", "续请失业金",
    "美股", "美元指数", "华尔街", "硅谷",
    "美国CPI", "美国PPI", "美国GDP", "美国PMI", "美国ISM",
    "美国消费者信心", "美国零售", "美国制造业", "美国服务业",
]

# ── Non-US patterns ──────────────────────────────────────────────────
# Any match here → weight 0.25 (basically never push).  Covers ALL
# regions outside the US: Europe, Japan, China, Korea, Canada, Australia,
# Taiwan, Hong Kong, India, Brazil, Turkey, SE Asia, Russia, etc.

_NON_US_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        # ── Europe ──
        r'\bECB\b', r'\bEuropean\s+Central\s+Bank\b', r'\bEurozone\b',
        r'\bEuro\s+area\b', r'\bEuropean\s+(?:Union|Commission)\b',
        r'\b(?:Christine\s+)?Lagarde\b',
        r'\bEUR\b', r'\beuro\b',
        # UK
        r'\bBank\s+of\s+England\b', r'\bBoE\b', r'\b(?:Andrew\s+)?Bailey\b',
        r'\bUnited\s+Kingdom\b', r'\bUK\b', r'\bBritain\b', r'\bBritish\b',
        r'\bFTSE\b', r'\bGBP\b', r'\bsterling\b',
        # Germany
        r'\bGermany\b', r'\bGerman\b', r'\bBerlin\b', r'\bBundesbank\b',
        r'\bDAX\b',
        # France
        r'\bFrance\b', r'\bFrench\b', r'\bParis\b', r'\bCAC\s*40\b',
        # Italy / Spain / Netherlands / Switzerland / Sweden / Norway
        r'\bItaly\b', r'\bItalian\b',
        r'\bSpain\b', r'\bSpanish\b',
        r'\bNetherlands\b', r'\bDutch\b',
        r'\bSwitzerland\b', r'\bSwiss\b', r'\bSNB\b', r'\bCHF\b',
        r'\bSweden\b', r'\bSwedish\b', r'\bRiksbank\b', r'\bSEK\b',
        r'\bNorway\b', r'\bNorwegian\b', r'\bNorges\s+Bank\b', r'\bNOK\b',

        # ── Japan ──
        r'\bJapan\b', r'\bJapanese\b', r'\bTokyo\b',
        r'\bBank\s+of\s+Japan\b', r'\bBoJ\b', r'\b(?:Kazuo\s+)?Ueda\b',
        r'\bNikkei\b', r'\bJPY\b', r'\bYen\b', r'\bTOPIX\b',

        # ── China ──
        r'\bChina\b', r'\bChinese\b', r'\bBeijing\b',
        r'\bPBOC\b', r'\bPeople\'?s?\s+Bank\s+of\s+China\b',
        r'\bCSRC\b', r'\bShanghai\b', r'\bShenzhen\b',
        r'\bCSI\s*300\b', r'\bCNY\b', r'\bRMB\b', r'\bYuan\b',
        r'\bA-?shares?\b', r'\bA股\b',

        # ── Korea ──
        r'\bKorea\b', r'\bKorean\b', r'\bSeoul\b',
        r'\bBank\s+of\s+Korea\b', r'\bBoK\b',
        r'\bKOSPI\b', r'\bKRW\b', r'\bWon\b',

        # ── Canada ──
        r'\bCanada\b', r'\bCanadian\b', r'\bOttawa\b',
        r'\bBank\s+of\s+Canada\b', r'\bBoC\b',
        r'\bTSX\b', r'\bCAD\b', r'\bLoonie\b',

        # ── Australia / New Zealand ──
        r'\bAustralia\b', r'\bAustralian\b', r'\bSydney\b',
        r'\bRBA\b', r'\bASX\b', r'\bAUD\b',
        r'\bNew\s+Zealand\b', r'\bWellington\b', r'\bRBNZ\b', r'\bNZD\b',

        # ── Taiwan / Hong Kong ──
        r'\bTaiwan\b', r'\bTaipei\b', r'\bTaiwanese\b',
        r'\bTWSE\b', r'\bTWD\b',
        r'\bHong\s+Kong\b', r'\bHK\b',
        r'\bHang\s+Seng\b', r'\bHSI\b', r'\bHKMA\b', r'\bHKD\b',

        # ── India ──
        r'\bIndia\b', r'\bIndian\b', r'\bMumbai\b', r'\bDelhi\b',
        r'\bRBI\b', r'\bNSE\b', r'\bBSE\b', r'\bSensex\b', r'\bNifty\b',
        r'\bINR\b', r'\bRupee\b',

        # ── Brazil ──
        r'\bBrazil\b', r'\bBrazilian\b', r'\bBrasilia\b', r'\bSao\s+Paulo\b',
        r'\bBCB\b', r'\bBovespa\b', r'\bBRL\b', r'\bReal\b',

        # ── Other emerging / non-core ──
        r'\bTurkey\b', r'\bTurkish\b', r'\bAnkara\b', r'\bIstanbul\b',
        r'\bTCMB\b', r'\bLira\b', r'\bTRY\b',
        r'\bSouth\s+Africa\b', r'\bSARB\b', r'\bRand\b', r'\bZAR\b',
        r'\bIndonesia\b', r'\bIndonesian\b', r'\bJakarta\b',
        r'\bBank\s+Indonesia\b', r'\bIDR\b', r'\bRupiah\b',
        r'\bMalaysia\b', r'\bMalaysian\b', r'\bKuala\s+Lumpur\b',
        r'\bBNM\b', r'\bRinggit\b', r'\bMYR\b',
        r'\bThailand\b', r'\bThai\b', r'\bBangkok\b', r'\bBoT\b',
        r'\bBaht\b', r'\bTHB\b',
        r'\bPhilippines\b', r'\bFilipino\b', r'\bManila\b',
        r'\bBSP\b', r'\bPeso\b', r'\bPHP\b',
        r'\bVietnam\b', r'\bVietnamese\b', r'\bHanoi\b', r'\bDong\b', r'\bVND\b',
        r'\bSingapore\b', r'\bSingaporean\b', r'\bMAS\b', r'\bSGD\b', r'\bSTI\b',
        r'\bMexico\b', r'\bMexican\b', r'\bBanxico\b', r'\bMXN\b',
        r'\bChile\b', r'\bSantiago\b', r'\bCLP\b',
        r'\bArgentina\b', r'\bBuenos\s+Aires\b', r'\bARS\b',
        r'\bColombia\b', r'\bBogota\b', r'\bCOP\b',
        r'\bPoland\b', r'\bPolish\b', r'\bWarsaw\b', r'\bNBP\b', r'\bPLN\b',
        r'\bCzech\b', r'\bPrague\b', r'\bCNB\b', r'\bCZK\b',
        r'\bRussia\b', r'\bRussian\b', r'\bMoscow\b', r'\bCBR\b',
        r'\bRuble\b', r'\bRUB\b', r'\bMOEX\b',
        r'\bNigeria\b', r'\bLagos\b', r'\bCBN\b', r'\bNaira\b', r'\bNGN\b',
        r'\bEgypt\b', r'\bCairo\b', r'\bEGP\b',
        r'\bPakistan\b', r'\bKarachi\b', r'\bIslamabad\b', r'\bPKR\b',
        r'\bBangladesh\b', r'\bDhaka\b',
        r'\bSaudi\s+Arabia\b', r'\bSaudi\b', r'\bRiyadh\b', r'\bSAMA\b',
        r'\bUAE\b', r'\bEmirates\b', r'\bDubai\b', r'\bAbu\s+Dhabi\b',
        r'\bIsrael\b', r'\bIsraeli\b', r'\bTel\s+Aviv\b', r'\bBank\s+of\s+Israel\b',
        r'\bQatar\b', r'\bDoha\b',
        r'\bKuwait\b',
        r'\bUkraine\b', r'\bUkrainian\b', r'\bKyiv\b',
    ]
]

# Chinese-language non-US keywords (substring match on original CJK text)
# Note: "中国" is separately guarded (see _NON_US_CJK guard logic below)
# because standalone 中国 can appear in "中美" (US-China) contexts.
_NON_US_CJK: list[str] = [
    # Europe
    "欧洲央行", "欧央行", "拉加德", "欧元区", "欧盟委员会",
    "德国", "柏林", "德联邦银行", "DAX",
    "法国", "巴黎", "CAC40",
    "英国", "伦敦", "英央行", "英镑", "富时", "英格伦",
    "意大利", "西班牙", "荷兰", "瑞士", "瑞典", "挪威",
    # Japan
    "日本", "东京", "日本央行", "日银", "日元", "植田和男", "日经",
    # China — "中国" alone is included; substrings like 中美 are handled
    # by Gate 3 (US patterns checked first — 中美X headlines may also
    # match US CJK keywords like 美联储/标普, in which case US wins).
    "中国", "中国央行", "人民银行", "中国人民银行", "证监会", "银保监",
    "上海", "深圳", "沪深300", "人民币", "在岸", "离岸人民币",
    "A股",
    # Korea
    "韩国", "首尔", "韩元", "韩国央行", "KOSPI",
    # Canada
    "加拿大", "渥太华", "加元", "加拿大央行",
    # Australia
    "澳大利亚", "澳洲", "悉尼", "澳元", "澳洲央行",
    # Taiwan / HK
    "台湾", "台北", "台币", "台股", "加权指数",
    "香港", "恒生", "港币", "金管局", "港股",
    # India / Brazil
    "印度", "孟买", "新德里", "卢比", "印度央行", "Sensex",
    "巴西", "圣保罗", "雷亚尔", "巴西央行",
    # Other
    "土耳其", "里拉", "南非", "兰特",
    "印尼", "雅加达", "印尼盾",
    "马来西亚", "吉隆坡", "令吉",
    "泰国", "曼谷", "泰铢",
    "菲律宾", "马尼拉", "比索",
    "越南", "河内", "胡志明", "越南盾",
    "新加坡", "新元", "新加坡元",
    "墨西哥", "墨西哥比索",
    "阿根廷", "布宜诺斯艾利斯",
    "俄罗斯", "莫斯科", "卢布",
    "沙特", "利雅得", "阿联酋", "迪拜",
    "以色列", "特拉维夫",
    "乌克兰", "基辅",
    # Chinese provincial data (explicitly domestic, not national)
    "广东", "北京", "上海", "深圳", "广州", "浙江", "江苏",
    "山东", "四川", "湖北", "河南", "河北", "湖南", "福建",
    "安徽", "辽宁", "重庆", "天津", "陕西", "江西", "广西",
    "云南", "贵州", "山西", "吉林", "黑龙江", "甘肃", "海南",
    "内蒙古", "宁夏", "青海", "西藏", "新疆",
]


def geo_tier_weight(headline: str, tickers_found: list[str] | None = None) -> float:
    """Assign geographic relevance weight for US-centric investing.

    Returns:
        1.0  — US-market news, company-specific news (has tickers), or unclassified
        0.25 — Non-US macro/regional news (basically never push)

    A ticker hit exempts the item entirely — company news is about the
    company, not the country.  TSMC earnings ≠ Taiwan GDP report.
    """
    # ── Gate 1: company-specific news (has ticker) → exempt ──
    if tickers_found:
        return 1.0

    # ── Gate 2: empty headline → unclassified ──
    if not headline:
        return 1.0

    text_lower = headline.lower()

    # ── Gate 3: US signals → 1.0 (check FIRST) ──
    for pat in _US_TIER_PATTERNS:
        if pat.search(text_lower):
            return 1.0

    for kw in _US_TIER_CJK:
        if kw in headline:
            return 1.0

    # ── Gate 4: non-US signals → 0.25 ──
    for pat in _NON_US_PATTERNS:
        if pat.search(text_lower):
            return 0.25

    for kw in _NON_US_CJK:
        if kw in headline:
            return 0.25

    # ── Gate 5: unclassified (global / crypto / commodity / no geo signal) ──
    return 1.0


# ---------------------------------------------------------------------------
# Stage B — Content quality filter
# ---------------------------------------------------------------------------

# Patterns that indicate POLITICAL INTERVIEW / GOSSIP with no market catalyst.
_POLITICAL_GOSSIP_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        # Trump interview / rally / defense (English)
        r'(trump|biden)\s+(defend|defends|rally|interview|speech|campaign)',
        r'(president|former\s+president)\s+(defend|interview|rally|campaign)',
        r'exclusive\s+interview.*(president|trump|biden)',
        # Political gossip / scandal (English)
        r'(sued|sues|lawsuit|suing)\s+(for|over).*\b(governor|congressman|senator|mayor)\b',
        r'\b(governor|congressman|senator|mayor)\b.*(sued|sues|lawsuit|scandal)',
        # Family / personal (English)
        r'(defend|defends).{0,30}(child|children|son|daughter|family)',
        r'(divorce|affair|scandal)\b.{0,30}(president|senator|congressman)',
        # Chinese political gossip — lawsuit / family settlement
        r'(州长|州政府|市长|议员|州议).{0,20}(诉讼|控告|和解|赔偿)',
        r'(诉讼|控告).{0,20}(州长|州政府|市长|议员)',
        r'家族基金.{0,20}(和解|赔偿|诉讼)',
        r'(丑闻|婚外情|离婚).{0,20}(总统|州长|议员|国会)',
        # Chinese political interview defense
        r'(特朗普|川普).{0,10}(辩护|辩解|回应|采访|集会|竞选)',
        r'(总统|前总统).{0,10}(辩护|辩解|采访|集会)',
    ]
]

# Chinese domestic POLITICAL PROPAGANDA — zero market relevance.
_CCP_PROPAGANDA_KEYWORDS = [
    "党委", "学习贯彻", "全会精神", "主题教育",
    "民主生活会", "团拜", "重要讲话", "指示精神",
    "新时代中国特色社会主义", "中国特色",
    "两个维护", "四个意识", "四个自信",
    "脱贫攻坚", "乡村振兴", "共同富裕",
    "党史学习教育", "不忘初心", "牢记使命",
    "巡视整改", "全面从严治党", "反腐",
    "中心组学习", "意识形态", "统战",
    "党",  # only when combined with other indicators
]

# Stronger patterns: MUST match at least one of these to trigger CCP demotion.
_CCP_STRONG_MARKERS = [
    "党委", "全会精神", "学习贯彻", "重要讲话",
    "主题教育", "民主生活会", "团拜",
    "两个维护", "四个意识", "四个自信",
    "新时代中国特色社会主义",
    "巡视整改", "全面从严治党",
    "党史学习教育", "不忘初心",
]

# Single-stock Chinese A-share noise.
_A_SHARE_NOISE_PATTERNS = [
    re.compile(p) for p in [
        r'\d{6}\s*(涨停|跌停|连续涨停|一字板|封板)',  # "605358 涨停"
        r'(涨停|跌停|一字板|地天板|天地板)',          # "立昂微涨停"
        r'[A股].{0,10}(涨停|跌停)',
        r'(尾盘|午盘|早盘).{0,5}(拉升|跳水|异动)',
        r'\d{6}',  # 6-digit A-share stock code
    ]
]

# Single-stock movements that don't warrant push (unless multi-asset).
_SINGLE_STOCK_NOISE = [
    re.compile(p, re.IGNORECASE) for p in [
        # Major price moves with % — will be overridden by _is_major_stock_event if >10%
        r'(stock|shares?)\s+(up|down|rise|fall|surge|drop|jump)\s+\d+%',
        r'(surge|plunge|soar|tumble|skyrocket)[sd]?\s+\d+%',
        # Minor price movements (no % or small %) → always noise
        r'(stock|shares?)\s+(edge|inch|drift|slip|dip|tick)[sd]?\s+(higher|lower|up|down)',
        r'(stock|shares?)\s+(flat|mixed|little\s+changed|barely\s+moved)',
        r'trade[sd]?\s+(higher|lower|flat|down|up)\s+(in|on|after|amid)',
        r'\b(CEO|CFO|COO)\b.{0,30}(sells?|sold|buy|bought)\s+\$?\d+',
        r'analyst\s+(upgrade|downgrade|initiate|raise|lower|cut|boost)',
        r'price\s+target\s+(raised|lowered|cut|boosted|trimmed)',
        r'(earnings|revenue|eps)\s+(beat|miss|missed).{0,30}(estimate|forecast)',
        # Form 4 / insider filing
        r'form\s+4.{0,20}(by|filing|filed)',
        r'insider\s+(sell|sale|buy|purchase)',
    ]
]

# Routine political appointments without policy action.
_ROUTINE_POLITICAL = [
    re.compile(p, re.IGNORECASE) for p in [
        r'(sworn\s+in|appointed|named\s+as|takes?\s+over|will\s+become)',
        r'(elected|re-elected|won\s+(the\s+)?election|vote\s+of\s+confidence)',
        r'(state\s+funeral|national\s+mourning|day\s+of\s+mourning)',
        r'(lays?\s+wreath|memorial\s+service|tribute\s+to)',
        r'(visits?\s+\w+\s+(?:in|for)\s+\w+\s+talks?)',  # diplomatic visit
        r'(meets?\s+with|held\s+talks|bilateral\s+meeting)',  # diplomatic meeting
    ]
]


def content_quality_filter(text: str, tickers_found: str = "",
                           has_strategic: bool = False) -> float:
    """Filter out content that looks like news but has zero market impact.

    Returns a multiplier (0.0–1.0).  The LOWEST multiplier wins across
    all categories — we pick the most-severe demotion.

    Categories (in order of severity):
      0.15 — Chinese party propaganda (NOT market news)
      0.20 — Non-US routine politics (state funeral, election, appointment)
      0.30 — Political gossip / interview defense without tickers
      0.30 — Single-stock noise (A-share limit-up, analyst rating)
      1.00 — No noise signal detected
    """
    if not text:
        return 1.0

    text_lower = text.lower()
    has_tickers = bool(tickers_found and tickers_found.strip())

    # Override: strategic events ALWAYS pass regardless of other signals
    if has_strategic:
        return 1.0

    multipliers = [1.0]

    # --- Category 0: Chinese-language default demotion ---
    # Chinese is supplementary. Chinese-language news must explicitly
    # prove US market relevance (US tickers, US macro, global commodity)
    # to get full weight.  Otherwise it gets ×0.5.
    if _is_chinese_dominant(text_lower) and not _has_us_market_signal(text_lower, has_tickers):
        multipliers.append(0.5)

    # --- Category 1: CCP propaganda (most severe) ---
    if _is_ccp_propaganda(text_lower):
        logger.debug("Content filter: CCP propaganda → ×0.15")
        return 0.15  # Short-circuit — nothing redeems this

    # --- Category 2: Single-stock noise ---
    if _is_single_stock_noise(text_lower, has_tickers):
        logger.debug("Content filter: single-stock noise → ×0.30")
        multipliers.append(0.30)

    # --- Category 3: Political gossip / interview ---
    if _is_political_gossip(text_lower, has_tickers):
        logger.debug("Content filter: political gossip → ×0.30")
        multipliers.append(0.30)

    # --- Category 4: Routine foreign politics ---
    if _is_routine_foreign_politics(text_lower, has_tickers):
        logger.debug("Content filter: routine foreign politics → ×0.20")
        multipliers.append(0.20)

    return min(multipliers)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_ccp_propaganda(text_lower: str) -> bool:
    """Detect Chinese Communist Party domestic propaganda.

    Must match at least one STRONG marker AND the text must have
    zero US-market-relevant keywords.
    """
    strong_hit = any(kw.lower() in text_lower for kw in _CCP_STRONG_MARKERS)
    if not strong_hit:
        return False

    # Check: is there any saving grace — US market relevance?
    saving_grace = [
        "chip", "semiconductor", "nvidia", "英伟达", "nvda",
        "sanction", "tariff", "制裁", "关税",
        "stock", "market", "股市", "美股",
        "invest", "funding", "入股", "投资",
        "oil", "crude", "原油",
        "war", "military", "战争", "军事",
    ]
    has_market_relevance = any(kw in text_lower for kw in saving_grace)

    return not has_market_relevance


def _is_single_stock_noise(text_lower: str, has_tickers: bool) -> bool:
    """A-share limit-up/down or trivial single-stock noise.

    MAJOR single-stock events ARE allowed through:
      - Mega-cap company events (AAPL, MSFT, NVDA, TSLA, etc.)
      - FDA drug approval / breakthrough therapy
      - Major acquisition / merger (>$1B)
      - Massive stock move (>10% or "plunge"/"surge" with high magnitude)
      - CEO change at a major company
    """
    # A-share stock code + limit → always noise
    for pat in _A_SHARE_NOISE_PATTERNS:
        if pat.search(text_lower):
            return True

    # Check for MAJOR impact signals first — these redeem single-stock news
    if _is_major_stock_event(text_lower, has_tickers):
        return False  # NOT noise — major impact event

    # Trivial single stock noise (analyst rating, minor price movement, CEO stock sale)
    for pat in _SINGLE_STOCK_NOISE:
        if pat.search(text_lower):
            if not _has_multi_asset(text_lower):
                return True

    return False


def _is_major_stock_event(text_lower: str, has_tickers: bool) -> bool:
    """Check if a single-stock event is MAJOR enough to warrant push.

    Criteria (any one is sufficient):
      1. Mega-cap stock (AAPL/MSFT/NVDA/GOOGL/AMZN/META/TSLA) + significant event
      2. Massive price move: "surge 30%", "plunge 15%", "soar 25%"
      3. FDA approval / breakthrough therapy designation
      4. Major acquisition: "acquire for $X billion", "merger worth $X billion"
      5. CEO change at a major company
      6. Direct ticker match with portfolio + major event signal
    """
    # Mega-cap tickers
    mega_caps = [
        "aapl", "msft", "nvda", "googl", "amzn", "meta", "tsla",
        "amd", "intc", "avgo", "orcl", "adbe", "crm", "nflx",
        "jpm", "gs", "bac", "wmt", "xom", "cvx", "pfe", "mrna",
    ]
    is_megacap = any(t in text_lower for t in mega_caps)

    # Massive price move (>10% or extreme language)
    massive_move_patterns = [
        r'(surge|soar|skyrocket|plunge|plummet|crash|tumble|collapse)[sd]?\s+\d{2,}%',
        r'(jump|leap|spike|drop|fall|sink)[sd]?\s+(1[5-9]|[2-9]\d)%',
        r'(up|down|rise|fall)\s+(1[5-9]|[2-9]\d)%',
        r'(record|historic|biggest|largest)\s+(drop|fall|surge|gain|rally)',
        r'market\s+cap\s+(evaporat|wiped|erased|lost)\s+\$?\d+',
        r'(lost|lose|gain|add)[sd]?\s+\$?\d+\s*(billion|trillion)',
    ]
    has_massive_move = any(
        re.search(p, text_lower) for p in massive_move_patterns
    )

    # FDA / drug approval
    fda_signals = [
        "fda approval", "fda approved", "fda clearance",
        "breakthrough therapy", "accelerated approval",
        "priority review", "fast track designation",
        "fda 批准", "突破性疗法", "加速批准",
    ]
    has_fda = any(kw in text_lower for kw in fda_signals)

    # Major acquisition/merger
    mna_signals = [
        r'(acquire|acquisition|buy|takeover|purchase)[sd]?.{0,50}?(for|at|worth)\s+\$?[\d,.]+',
        r'(merge|merger|deal)\s+(worth|valued at|for)\s+\$?[\d,.]+',
        r'\$?[\d,.]+?\s*(billion|bn|million)\s+(acquisition|buyout|takeover|deal)',
        r'(收购|并购|要约收购)\s*\d+\s*(亿|万)',
    ]
    has_mna = any(re.search(p, text_lower) for p in mna_signals)

    # CEO change at major company
    ceo_signals = [
        r'(ceo|chief executive|founder)\s+(step|resign|oust|fir|exit|leav|depart)',
        r'(new|name|appoint)\s+(ceo|chief executive)',
        r'(ceo|总裁|创始人).{0,20}(辞职|离职|卸任|被罢免|被解雇|下课)',
        r'(任命|聘请|委任).{0,20}(ceo|总裁|首席执行官)',
    ]
    has_ceo_change = any(re.search(p, text_lower) for p in ceo_signals)

    # Mega-cap + any significant event = major
    if is_megacap and (has_tickers or has_massive_move or has_mna or has_ceo_change or has_fda):
        return True

    # Massive move alone = major (even non-mega-cap)
    if has_massive_move:
        return True

    # FDA approval = major for any biotech
    if has_fda and has_tickers:
        return True

    # Major M&A = always major
    if has_mna:
        return True

    # CEO change at ticker-matched company = major
    if has_ceo_change and has_tickers:
        return True

    return False


def _is_political_gossip(text_lower: str, has_tickers: bool) -> bool:
    """Political interview / defense / campaign content without tickers."""
    for pat in _POLITICAL_GOSSIP_PATTERNS:
        if pat.search(text_lower):
            if not has_tickers:
                return True
    return False


def _is_routine_foreign_politics(text_lower: str, has_tickers: bool) -> bool:
    """State funerals, elections, diplomatic visits with no US linkage."""
    if has_tickers:
        return False  # Ticker match redeems it — could be market-relevant

    for pat in _ROUTINE_POLITICAL:
        if pat.search(text_lower):
            # Check for US connection
            us_connection = any(
                kw in text_lower for kw in [
                    "us ", "u.s.", "american", "united states",
                    "wall street", "s&p", "nasdaq", "dow",
                    "oil", "crude", "sanction", "trade war",
                    "美国", "美军", "美股",
                ]
            )
            if not us_connection:
                return True

    return False


def _is_chinese_dominant(text_lower: str) -> bool:
    """Check if text is predominantly Chinese-language content.

    Returns True if >25% of characters are CJK (Chinese/Japanese/Korean).
    """
    if not text_lower:
        return False
    cjk_count = sum(1 for c in text_lower if '一' <= c <= '鿿')
    # Only count alphabetic/ideographic characters for the ratio
    meaningful = sum(1 for c in text_lower if c.isalpha() or '一' <= c <= '鿿')
    if meaningful == 0:
        return False
    return cjk_count / meaningful > 0.25


def _has_us_market_signal(text_lower: str, has_tickers: bool) -> bool:
    """Check if Chinese text contains US market relevance signals.

    Chinese content must earn its way past the language demotion by
    explicitly mentioning US-listed companies, US macro events, or
    globally-traded commodities/crypto with US market linkage.
    """
    if has_tickers:
        return True  # Ticker match implies US-listed company

    us_signals = [
        # US indices / exchanges
        "s&p", "nasdaq", "dow", "nyse", "wall street",
        "sp500", "spx", "ndx", "vix",
        # US macro / Fed
        "fomc", "federal reserve", "fed ", "jerome powell",
        "cpi", "ppi", "nfp", "nonfarm", "gdp", "unemployment",
        "treasury", "10-year", "2-year",
        # US stocks (top mega-caps)
        "nvidia", "英伟达", "apple", "苹果", "microsoft", "微软",
        "google", "alphabet", "amazon", "亚马逊", "meta", "tesla", "特斯拉",
        "amd", "intel", "broadcom", "marvell",
        # US gov / policy
        "white house", "白宫", "congress", "国会", "us government",
        "chips act", "芯片法案", "inflation reduction act",
        "executive order", "行政命令",
        # Global systemic with US linkage
        "sanctions", "制裁", "tariff", "关税", "trade war", "贸易战",
        "oil supply", "原油供应", "crude", "opec",
        "gold", "黄金", "bitcoin", "btc", "比特币",
        # US market Chinese keywords
        "美股", "美联储", "纳斯达克", "标普", "道琼斯",
        "华尔街", "硅谷",
    ]
    return any(kw in text_lower for kw in us_signals)


def _has_multi_asset(text_lower: str) -> bool:
    """Check if text mentions 2+ asset CLASSES (indicates broad market impact).

    Uses asset-class-level indicators only — individual company names
    should NOT count as separate asset classes.
    """
    asset_classes = {
        "equities": [
            "s&p", "sp500", "spx", "nasdaq", "ndx", "dow", "nyse",
            "stock market", "equity market", "equities", "indices",
            "板块", "普跌", "普涨",
        ],
        "bonds": [
            "treasury", "yield", "bond", "10-year", "2-year", "30-year",
            "basis point", "fed funds", "国债", "收益率",
        ],
        "currencies": [
            "dollar index", "dxy", "usd", "eur", "jpy", "gbp",
            "forex", "currency", "美元", "汇率",
        ],
        "commodities": [
            "oil", "crude", "brent", "wti", "gold", "silver", "copper",
            "commodity", "opec", "原油", "黄金", "大宗商品",
            "natural gas", "energy",
        ],
        "crypto": [
            "bitcoin", "btc", "ethereum", "eth", "crypto",
            "比特币", "以太坊",
        ],
    }
    classes_hit = 0
    for class_name, kws in asset_classes.items():
        if any(kw in text_lower for kw in kws):
            classes_hit += 1
    return classes_hit >= 2
