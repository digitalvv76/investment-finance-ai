"""Strategic relationship detector — government intervention + NVIDIA investments.

Detects high-value structural events that require immediate push:
  1. US government / regulator invests, subsidizes, or supports a company
  2. NVIDIA or Jensen Huang invests in or acquires a company

Uses regex-based relationship templates — no LLM needed (fast, cheap, reliable).
"""
import logging
import re
from typing import List, Optional, Tuple, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entity dictionaries
# ---------------------------------------------------------------------------

# US government entities — full names, abbreviations, departments
GOVERNMENT_ENTITIES = [
    # Federal departments
    "商务部", "财政部", "能源部", "国防部", "国土安全部", "交通部", "农业部",
    "Department of Commerce", "Commerce Department", "Commerce Dept",
    "Department of Treasury", "Treasury Department",
    "Department of Energy", "Energy Department", "Energy Dept",
    "Department of Defense", "Defense Department", "Defense Dept", "DoD", "DOE", "DOC", "DHS",
    "Pentagon", "五角大楼",
    # Agencies
    "SEC", "CFTC", "FTC", "FCC", "FDA", "EPA", "NASA", "DARPA", "CFIUS",
    "美国证券交易委员会", "美国商品期货交易委员会", "联邦贸易委员会",
    "美国食品药品监督管理局", "美国环保署",
    # Government programs
    "CHIPS Act", "芯片法案", "Inflation Reduction Act", "通胀削减法案",
    "IRA", "美国政府", "US Government", "US govt", "US invests",
    "白宫", "White House", "Washington",
    "国会", "Congress", "参议院", "Senate", "众议院", "House",
    # Industry regulators
    "行业主管部门", "监管机构", "regulator", "美联储", "Federal Reserve",
    # State-level
    "州政府", "state government",
    # Generic government signals (must be specific enough to avoid false positives)
    "federal government", "United States",
    "government backstop", "government backing", "government bailout",
    "government support", "government rescue",
    "state-backed", "state backed", "government-backed", "government backed",
]

# NVIDIA related entities
NVIDIA_ENTITIES = [
    "英伟达", "NVIDIA", "Nvidia", "nvidia",
    "黄仁勋", "Jensen Huang", "jensen huang", "JENSEN HUANG",
    "NVDA", "Nvidia CEO", "NVIDIA CEO",
    "Huang",  # Covers "Huang says", "Huang endorses", etc.
]

# Investment / support action verbs (Chinese + English)
INVESTMENT_ACTIONS_CN = [
    "入股", "注资", "投资", "收购", "并购", "控股", "参股",
    "战略投资", "战略入股", "增持", "定向增发", "战投",
    "领投", "跟投", "天使轮", "A轮", "B轮", "C轮", "D轮",
    # Government financial instruments (from training docs)
    "补贴转股权", "可转换优先股", "黄金股", "贷转股",
    "债转股", "优先股", "认股权证", "少数股权",
]

INVESTMENT_ACTIONS_EN = [
    "invest", "invests", "investment", "investing",
    "acquire", "acquires", "acquisition", "merge", "merger",
    "take stake", "takes stake", "stake in", "stake", "stakes",
    "lead round", "leads round", "funding round",
    "series A", "series B", "series C", "series D",
    "strategic investment", "strategic stakes", "strategic",
    "minority stake", "majority stake",
    # Government financial instruments
    "convertible preferred", "golden share", "equity stake",
    "loan-to-equity", "debt-to-equity", "preferred stock",
    "converts into equity", "swap for equity",
    "bailout", "bailouts",
    "converts", "swap", "takes equity", "acquires equity",
    "grant converts", "convert grants",
    "distributes", "allocates", "allocate",
]

# NVIDIA/Jensen Huang endorsement / partnership signals
# (Not investment, but strong market signal)
ENDORSEMENT_ACTIONS_CN = [
    "站台", "背书", "同台", "力挺", "看好", "公开支持",
    "直言", "将成为", "下一家万亿", "万亿美元公司",
    "战略合作", "深度合作", "独家合作", "联合发布",
    "推荐", "点名", "押注",
    # Verbal market signals (from training docs)
    "喊话增产", "请多生产", "买他们的股票", "买它的股票",
    "做得非常好", "重返赛场",
]

# NVIDIA competitive threat actions (entering new markets → bearish for incumbents)
COMPETITIVE_THREAT_CN = [
    "入局", "进入", "进军", "发布首款", "首款处理器", "首款芯片",
    "重新发明", "不需要", "无需", "不再需要",
    "正式进入", "跨界", "杀入",
]

COMPETITIVE_THREAT_EN = [
    "enter the", "enters the", "entering", "enters",
    "launch its first", "launches its first", "first processor", "first cpu",
    "unveils", "unveil", "unveils first",
    "compete with", "competes with", "competing with", "directly competing",
    "disrupt", "disrupts", "disrupting",
    "no longer need", "no longer needs", "no longer require", "no longer requires",
    "doesn't require", "does not require",
    "reinvent the", "reinventing the",
    "dominated by",
]

ENDORSEMENT_ACTIONS_EN = [
    "endorse", "endorses", "partnership", "strategic partner", "collaboration",
    "trillion dollar", "trillion-dollar", "next trillion-dollar",
    "bet on", "bets on", "bet big", "bullish on", "tout", "touts", "champion",
    "joint venture", "exclusive partner",
    # Verbal market signals
    "buy their stock", "produce more", "ramp up production",
    "they are great", "reinvent", "reinventing",
    "critical partner", "key partner",
    # Jensen-specific endorsement signals (broad matching: verb + target company)
    "declares", "calls them", "says they", "praises", "hails",
    "will become", "elevate", "elevates",
    "urges", "urged", "tell investors", "tells investors",
    "collaborate", "collaborates", "collaborating",
    "next major field", "the next",
    # Catch "Jensen Huang says Marvell is doing incredible work"
    "says", "calls", "said", "called", "is doing", "are doing",
    "\"incredible", "\"amazing", "\"extraordinary", "\"critical",
    "\"game-changing", "\"breakthrough",
]

SUBSIDY_ACTIONS_CN = [
    "资助", "扶持", "补贴", "拨款", "减税", "免税", "税收优惠",
    "贷款担保", "低息贷款", "研发资助", "专项资金",
    "产业基金", "引导基金", "国有资本", "授予",
]

SUBSIDY_ACTIONS_EN = [
    "subsidize", "subsidizes", "subsidy", "subsidies",
    "grant", "grants", "fund", "funding", "funds",
    "tax credit", "tax break", "loan guarantee", "bailout",
    "award contract", "award", "awards", "allocate", "allocates", "appropriation",
    "contract to", "contract for",
    "finalizes", "finalize", "announces", "announce", "plans", "pledges", "commits",
    "supports", "support", "backs", "backing",
    "package", "packages",
    "provides", "provide", "provided",  # "federal government provides subsidies"
]

POLICY_ACTIONS_CN = [
    "出台扶持", "签署", "批准", "立法", "颁布",
    "行政命令", "executive order", "总统令",
    "关税豁免", "出口管制放松", "放宽限制",
    "制裁", "限制出口", "实体清单",
]

POLICY_ACTIONS_EN = [
    "executive order", "sign into law", "signs into law",
    "pass legislation", "passes legislation", "passed legislation",
    "tariff exemption", "export control ease", "deregulate",
    "sanctions", "sanction", "imposes sanctions", "impose sanctions",
    "ban", "banning", "restrict",
    "approves", "approve", "approved",  # regulatory approval
]

ALL_ACTIONS = (
    INVESTMENT_ACTIONS_CN + INVESTMENT_ACTIONS_EN +
    SUBSIDY_ACTIONS_CN + SUBSIDY_ACTIONS_EN +
    POLICY_ACTIONS_CN + POLICY_ACTIONS_EN +
    ENDORSEMENT_ACTIONS_CN + ENDORSEMENT_ACTIONS_EN
)

# ---------------------------------------------------------------------------
# Regex patterns for relationship detection
# ---------------------------------------------------------------------------

# Build combined regex patterns
_GOV_PATTERN = '|'.join(re.escape(e) for e in GOVERNMENT_ENTITIES)
_NVDA_PATTERN = '|'.join(re.escape(e) for e in NVIDIA_ENTITIES)
_ACTION_PATTERN = '|'.join(re.escape(a) for a in ALL_ACTIONS)
_ENDORSE_PATTERN = '|'.join(re.escape(a) for a in (ENDORSEMENT_ACTIONS_CN + ENDORSEMENT_ACTIONS_EN))
_THREAT_PATTERN = '|'.join(re.escape(a) for a in (COMPETITIVE_THREAT_CN + COMPETITIVE_THREAT_EN))

# Pattern 2a: NVIDIA/Huang + investment action → nvda_investment
# Matches: "英伟达入股XX公司" or "黄仁勋领投YY B轮"
# 80-char window for English (e.g. "Jensen Huang, the CEO of NVIDIA, announced
# yesterday that the company would invest $500M in..."), 30 chars is plenty for
# compact Chinese but breaks on English sentences with appositives/clauses.
NVDA_ACTION_RE = re.compile(
    rf'({_NVDA_PATTERN}).{{0,80}}?({_ACTION_PATTERN}).{{0,80}}?',
    re.IGNORECASE
)

# Pattern 2b: NVIDIA/Huang + endorsement/partnership → nvda_endorsement
# Matches: "黄仁勋站台Marvell" or "NVIDIA announces strategic partnership"
# Wide window for long English sentences (e.g. "Jensen Huang calls SK Hynix the most critical memory partner, urges them to ramp up production")
NVDA_ENDORSE_RE = re.compile(
    rf'({_NVDA_PATTERN}).{{0,80}}?({_ENDORSE_PATTERN}).{{0,80}}?',
    re.IGNORECASE
)

# Pattern 2c: NVIDIA enters new market → competitive threat for incumbents
# Matches: "英伟达发布首款PC处理器" → bearish for INTC/AMD
NVDA_THREAT_RE = re.compile(
    rf'({_NVDA_PATTERN}).{{0,60}}?({_THREAT_PATTERN}).{{0,60}}?',
    re.IGNORECASE
)

# Pattern 3: Action + by + Government (passive / English style)
# Matches: "subsidized by Department of Energy" or "funded by US Government"
GOV_PASSIVE_RE = re.compile(
    rf'({_ACTION_PATTERN}).{{0,15}}?(by|由|被).{{0,15}}?({_GOV_PATTERN})',
    re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class StrategicMatch:
    """A detected strategic relationship event."""
    def __init__(self, category: str, matched_text: str, confidence: float):
        self.category = category        # "gov_investment", "nvda_investment", "gov_policy"
        self.matched_text = matched_text[:200]  # The text snippet that triggered
        self.confidence = confidence

    def __repr__(self):
        return f"StrategicMatch({self.category}, conf={self.confidence:.2f})"


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class StrategicDetector:
    """Detect government/NVIDIA strategic relationship events in news text."""

    # Confidence thresholds
    HIGH_CONFIDENCE = 0.85
    MEDIUM_CONFIDENCE = 0.65

    # False positive exclusion patterns
    _EXCLUSION_PATTERNS = [
        re.compile(p, re.IGNORECASE) for p in [
            # Earnings / financial reports (not strategic)
            r'(财报|earnings|revenue|quarterly|Q\d|财务报告|业绩预告)',
            # Product launches (not strategic)
            r'(发布.*(新品|产品|GPU|芯片|显卡|手机|game|游戏))',
            r'(launch|release).*(product|GPU|chip|graphics card)',
            # Product delays / manufacturing issues (not endorsement)
            r'(delay|delayed|snag|snags|push\s*back|postpone|reschedule)',
            r'(manufacturing|production).*(issue|problem|snag|bottleneck|constraint)',
            # Stock price movements (not strategic)
            r'(股价|stock\s+(price|up|down|rise|fall|surge|drop))',
            # Analyst ratings (not strategic)
            r'(上调|下调|upgrade|downgrade|target\s+price|评级)',
            # FDA/drug approvals (routine regulatory, not gov intervention)
            r'(FDA|药监局).*(批准|approve|approval|clear|clearance)',
            r'(generic|仿制|drug|药品|treatment|therapy)',
            # NVIDIA's own stock movement / market cap (not endorsement of others)
            r'(NVIDIA|英伟达|NVDA).*(蒸发|暴跌|市值|股价|下跌|drop|market\s+cap|wipe)',
            # Geopolitical sanctions (not US government investment)
            # Bidirectional: "Iran ... sanctions" or "sanctions ... Iran"
            r'(sanction|制裁).*(iran|north\s*korea|russia|venezuela)',
            r'(iran|north\s*korea|russia|venezuela).*(sanction|制裁)',
            # Sanction relief / oil export topics are geopolitical, not US investment
            r'sanctions?\s+relief', r'oil\s+(export|inventor|shipment)',
            r'(OPEC|opec|crude\s+oil|oil\s+price).*(iran|sanction)',
            r'(iran|sanction).*(OPEC|opec|crude\s+oil|oil\s+price)',
        ]
    ]

    def _is_endorsement_action(self, action: str) -> bool:
        """Check if an action verb belongs to endorsement/partnership category."""
        action_lower = action.lower()
        all_endorse = [a.lower() for a in (ENDORSEMENT_ACTIONS_CN + ENDORSEMENT_ACTIONS_EN)]
        return action_lower in all_endorse

    def _is_false_positive(self, text: str) -> bool:
        """Check if the text matches known false positive patterns.

        Military conflict override: Iran/Russia/NK/Venezuela sanctions are
        normally excluded (geopolitical ≠ US investment), but when military
        conflict keywords are present the event IS strategically relevant.
        """
        for pattern in self._EXCLUSION_PATTERNS:
            if pattern.search(text):
                # If this is a geopolitical sanctions exclusion, check for
                # military conflict keywords — those override the exclusion.
                if self._is_geopolitical_exclusion(pattern) and self._has_military_conflict(text):
                    logger.debug(
                        "Strategic: military conflict overrides geopolitical exclusion"
                    )
                    continue
                return True
        return False

    # Patterns that indicate geopolitical sanctions (not military conflict)
    _GEOPOLITICAL_EXCLUSION_PATTERNS = [
        re.compile(p, re.IGNORECASE) for p in [
            r'(sanction|制裁).*(iran|north\s*korea|russia|venezuela)',
            r'(iran|north\s*korea|russia|venezuela).*(sanction|制裁)',
            r'sanctions?\s+relief', r'oil\s+(export|inventor|shipment)',
            r'(OPEC|opec|crude\s+oil|oil\s+price).*(iran|sanction)',
            r'(iran|sanction).*(OPEC|opec|crude\s+oil|oil\s+price)',
        ]
    ]

    # Military conflict keywords that override geopolitical exclusion
    _MILITARY_CONFLICT_KEYWORDS = [
        "missile", "ballistic", "airstrike", "air strike", "air raid",
        "drone strike", "drone attack", "warship", "destroyer",
        "aircraft carrier", "submarine", "naval deployment", "naval blockade",
        "military exercise", "war game", "troop deployment", "mobilization",
        "military buildup", "retaliatory strike", "military retaliation",
        "military escalation", "standoff", "military standoff",
        "military confrontation", "showdown", "nuclear facility",
        "IRGC", "Revolutionary Guard", "Quds Force",
        "Strait of Hormuz",
        # Chinese equivalents
        "导弹", "空袭", "军舰", "航母", "驱逐舰", "潜艇",
        "军事演习", "军演", "兵力部署", "动员令", "军事集结",
        "报复性打击", "军事报复", "军事升级", "军事对峙", "对峙",
        "核设施", "革命卫队", "圣城旅", "霍尔木兹海峡",
    ]

    def _is_geopolitical_exclusion(self, pattern: re.Pattern) -> bool:
        """Check if a matched pattern is a geopolitical sanctions exclusion."""
        return pattern in self._GEOPOLITICAL_EXCLUSION_PATTERNS

    def _has_military_conflict(self, text: str) -> bool:
        """Check if text contains military conflict escalation keywords."""
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in self._MILITARY_CONFLICT_KEYWORDS)

    def detect(self, text: str) -> List[StrategicMatch]:
        """Scan text for strategic relationship patterns.

        Returns list of StrategicMatch objects, sorted by confidence descending.
        Empty list if no strategic events detected.
        """
        if not text or len(text) < 6:
            return []

        matches = []
        text_lower = text.lower()

        # --- Check Pattern 1: Government action ---
        # Use a two-pass approach to avoid regex complexity limits with very
        # large alternation patterns.  First locate government entities, then
        # check whether an action verb appears within 80 characters.
        for entity_raw in GOVERNMENT_ENTITIES:
            entity_lower = entity_raw.lower()
            idx = text_lower.find(entity_lower)
            if idx == -1:
                continue
            # Search for an action within 80 chars after the entity
            suffix = text_lower[idx + len(entity_lower):idx + len(entity_lower) + 80]
            for action_raw in ALL_ACTIONS:
                action_lower = action_raw.lower()
                if action_lower in suffix:
                    confidence = self._score_confidence(entity_raw, action_raw, "gov")
                    if confidence >= self.MEDIUM_CONFIDENCE:
                        matches.append(StrategicMatch(
                            category="gov_intervention",
                            matched_text=f"{entity_raw} ... {action_raw}",
                            confidence=confidence,
                        ))
                        break  # found high-confidence match for this entity

        # Also try the passive regex pattern (action by government)
        passive_matches = GOV_PASSIVE_RE.findall(text)
        for m in passive_matches:
            action, _, gov_entity = m[0], m[1], m[2]
            confidence = self._score_confidence(gov_entity, action, "gov") * 0.9
            if confidence >= self.MEDIUM_CONFIDENCE:
                matches.append(StrategicMatch(
                    category="gov_intervention",
                    matched_text=f"{action} by {gov_entity}",
                    confidence=confidence,
                ))
        nvda_matches = NVDA_ACTION_RE.findall(text)
        for m in nvda_matches:
            nvda_entity, action = m[0], m[1]
            # Skip endorsement actions — they go to nvda_endorsement
            if self._is_endorsement_action(action):
                continue
            confidence = self._score_confidence(nvda_entity, action, "nvda")
            if confidence >= self.MEDIUM_CONFIDENCE:
                matches.append(StrategicMatch(
                    category="nvda_investment",
                    matched_text=f"{nvda_entity} ... {action}",
                    confidence=confidence,
                ))

        # --- Check Pattern 2b: NVIDIA endorsement/partnership ---
        endorse_matches = NVDA_ENDORSE_RE.findall(text)
        seen_endorse = set()  # Dedup within endorsement
        for m in endorse_matches:
            nvda_entity, action = m[0], m[1]
            key = (nvda_entity.lower(), action.lower())
            if key in seen_endorse:
                continue
            seen_endorse.add(key)
            confidence = self._score_confidence(nvda_entity, action, "nvda")
            if confidence >= self.MEDIUM_CONFIDENCE:
                matches.append(StrategicMatch(
                    category="nvda_endorsement",
                    matched_text=f"{nvda_entity} ... {action}",
                    confidence=confidence,
                ))

        # --- Check Pattern 2c: NVIDIA competitive threat ---
        threat_matches = NVDA_THREAT_RE.findall(text)
        seen_threats = set()
        for m in threat_matches:
            nvda_entity, action = m[0], m[1]
            key = (nvda_entity.lower(), action.lower())
            if key in seen_threats:
                continue
            seen_threats.add(key)
            confidence = self._score_confidence(nvda_entity, action, "nvda")
            if confidence >= self.MEDIUM_CONFIDENCE:
                matches.append(StrategicMatch(
                    category="nvda_competitive_threat",
                    matched_text=f"{nvda_entity} ... {action}",
                    confidence=confidence,
                ))

        # Apply false positive filter ONLY to medium-confidence matches.
        # High-confidence (≥0.85) matches pass regardless — e.g.
        # "白宫签署行政命令" should trigger even if "NVDA股价" appears later.
        filtered = []
        for m in matches:
            if m.confidence >= self.HIGH_CONFIDENCE:
                filtered.append(m)
            elif not self._is_false_positive(text):
                filtered.append(m)
            else:
                logger.debug("Strategic match filtered: %s (conf=%.2f)", m.category, m.confidence)

        return sorted(filtered, key=lambda x: x.confidence, reverse=True)

    def has_strategic_event(self, text: str) -> bool:
        """Quick check: does this text contain any strategic event?"""
        return len(self.detect(text)) > 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _score_confidence(self, entity: str, action: str, category: str) -> float:
        """Score how confident we are that this is a real strategic event."""
        score = 0.5

        # Higher score for explicit investment/subsidy actions
        entity_lower = entity.lower()
        action_lower = action.lower()

        # Strong actions
        if any(a in action_lower for a in ["入股", "注资", "收购", "并购", "invest", "acquire", "take stake", "lead",
                                            "可转换优先股", "黄金股", "贷转股", "债转股", "优先股", "认股权证",
                                            "loan-to-equity", "debt-to-equity", "equity stake",
                                            "convertible preferred", "golden share"]):
            score += 0.25
        if any(a in action_lower for a in ["资助", "扶持", "补贴", "拨款", "授予", "subsidize", "subsidizes",
                                            "subsidies", "subsidy", "grant", "grants", "fund", "funding",
                                            "award", "awards", "provides", "provide",
                                            "package", "packages",  # rescue/bailout/stimulus package
                                            "converts", "converts into equity", "swap for equity",
                                            "finalizes", "announces", "plans", "pledges", "backs",
                                            "allocates", "allocate", "distributes",
                                            "strategic", "strategic stakes"]):
            score += 0.20
        if any(a in action_lower for a in ["签署", "批准", "行政命令", "executive order", "sign into law",
                                            "signs into law", "passes legislation", "approves", "approve", "approved"]):
            score += 0.15
        if any(a in action_lower for a in ["制裁", "sanction", "实体清单", "entity list", "ban", "banning"]):
            score += 0.15
        if any(a in action_lower for a in ["站台", "背书", "同台", "直言", "endorse", "endorses",
                                            "trillion dollar", "tout", "touts",
                                            "declares", "will become", "the next", "tells investors"]):
            score += 0.20  # Boosted from 0.12 — Jensen Huang endorsement is a strong signal
        if any(a in action_lower for a in ["战略合作", "独家合作", "strategic partner", "partnership", "collaboration"]):
            score += 0.10
        if any(a in action_lower for a in ["入局", "进入", "进军", "enter the", "enters the", "entering", "enters",
                                            "launch its first", "launches its first",
                                            "first processor", "first cpu", "unveils", "unveils first",
                                            "no longer need", "no longer needs", "doesn't require",
                                            "reinvent the", "reinventing the",
                                            "dominated by"]):
            score += 0.20  # Competitive threat / market entry is a strong strategic signal

        # Strong entities
        if any(e in entity_lower for e in ["chips act", "芯片法案", "inflation reduction", "department of energy", "energy department", "dod", "doe", "darpa", "国防部", "商务部", "能源部"]):
            score += 0.15
        if any(e in entity_lower for e in ["pentagon", "五角大楼", "white house", "白宫", "congress", "国会"]):
            score += 0.15
        if any(e in entity_lower for e in ["washington", "us government", "federal government", "united states"]):
            score += 0.15  # was 0.10 — boosted: generic gov entities are strong signals
        if any(e in entity_lower for e in ["黄仁勋", "jensen huang", "nvidia ceo", "huang"]):
            score += 0.20  # Jensen Huang / NVIDIA CEO is the strongest signal
        if any(e in entity_lower for e in ["nvidia", "英伟达", "nvda"]):
            score += 0.15  # Consolidated duplicate bonus

        # Combo bonuses: specific entity+action pairs that are unambiguously strategic
        combo_pairs = [
            (["白宫", "white house"], ["行政命令", "executive order", "签署"]),
            (["商务部", "department of commerce"], ["实体清单", "entity list", "制裁", "sanction"]),
            (["财政部", "treasury"], ["制裁", "sanction", "税收优惠"]),
            (["国防部", "defense department", "dod", "department of defense"], ["授予", "award", "contract", "合同", "golden share", "黄金股"]),
            (["chips act", "芯片法案"], ["拨款", "补贴", "grant", "fund", "注资", "invest"]),
            (["inflation reduction act", "ira"], ["invest", "fund", "grant", "subsidize"]),
            (["能源部", "energy department", "department of energy", "doe"], ["grant", "grants", "fund", "funding", "award", "awards", "invest", "拨款", "资助", "补贴"]),
        ]
        for entities, actions in combo_pairs:
            if any(e in entity_lower for e in entities) and any(a in action_lower for a in actions):
                score += 0.15
                break  # Only apply one combo bonus

        # Penalty: generic terms
        if entity_lower in ["regulator", "监管机构", "行业主管部门"] and action_lower in ["出台", "发布"]:
            score -= 0.15  # Too vague

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Ticker extraction helper
    # ------------------------------------------------------------------

    @staticmethod
    def extract_mentioned_tickers(text: str, known_tickers: Set[str]) -> Set[str]:
        """Extract tickers mentioned near strategic event patterns.

        Scans for uppercase ticker-like tokens near the matched regions.
        """
        found = set()
        text_upper = text.upper()
        for ticker in known_tickers:
            if ticker.upper() in text_upper:
                found.add(ticker)
        return found
