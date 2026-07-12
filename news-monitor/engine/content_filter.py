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

# Military conflict escalation keywords — these override the non-US political
# demotion because cross-border military conflict has global market implications
# (oil supply risk, defense spending, risk-off sentiment) regardless of whether
# US forces are explicitly mentioned.
_MILITARY_CONFLICT_ESCALATION = [
    # Missile / nuclear
    "missile", "ballistic", "ICBM", "warhead", "nuclear facility",
    "uranium enrichment", "centrifuge",
    # Airstrike / drone
    "airstrike", "air strike", "air raid", "bombardment",
    "drone strike", "drone attack", "UAV", "cruise missile",
    # Naval
    "warship", "destroyer", "aircraft carrier", "submarine",
    "naval deployment", "naval exercise", "naval blockade",
    # Military mobilization / exercise
    "military exercise", "war game", "troop deployment",
    "mobilization", "military buildup", "call-up",
    "reservist", "active duty",
    # Escalation / retaliation
    "retaliatory strike", "military retaliation",
    "military escalation", "heightened alert",
    "precision strike", "targeted strike",
    "preemptive strike", "surgical strike",
    # Standoff / confrontation
    "military standoff", "military confrontation",
    "showdown", "red line", "ultimatum",
    # Iran-specific military entities
    "IRGC", "Revolutionary Guard", "Quds Force",
    "Basij", "IRGC-N", "IRGC-QF",
    # Strait of Hormuz (already in US connectors, but also a military flashpoint)
    "mine-laying", "speedboat swarm", "fast attack craft",
    # Chinese equivalents
    "导弹", "弹道导弹", "洲际导弹", "核弹头", "核设施",
    "铀浓缩", "离心机",
    "空袭", "轰炸", "无人机袭击", "无人机攻击", "巡航导弹",
    "军舰", "驱逐舰", "航母", "潜艇", "海军部署", "海军演习",
    "军事演习", "军演", "实战化演训", "兵力部署",
    "动员令", "军事集结", "征召", "预备役",
    "报复性打击", "军事报复", "军事升级", "高度警戒",
    "精确打击", "定点清除", "先发制人",
    "军事对峙", "对峙", "最后通牒", "红线",
    "革命卫队", "圣城旅", "巴斯杰",
    "布雷", "快艇 swarm", "封锁海峡",
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

    # Military conflict escalation override: cross-border military conflict
    # involving any country has global market implications (oil supply, defense
    # spending, risk-off sentiment) even without explicit US connector.
    has_military_escalation = any(
        kw.lower() in text_lower for kw in _MILITARY_CONFLICT_ESCALATION
    )
    if has_military_escalation:
        logger.debug(
            "Geo-filter: military conflict '%s' → ×0.80", matched_country
        )
        return 0.80

    if has_political_action:
        # E.g., "Venezuela government collapses" with no US connection
        multiplier = 0.15 if matched_country == "China-CCP" else 0.2
        logger.debug("Geo-filter: NON-US politics '%s' → ×%.2f", matched_country, multiplier)
        return multiplier

    # Ambiguous — non-US country mentioned but unclear if political
    return 0.6


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
