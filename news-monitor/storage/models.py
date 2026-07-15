"""Data models for news monitor storage."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class NewsStatus(Enum):
    PENDING = "pending"          # captured, not yet processed
    FAST_PUSHED = "fast_pushed"  # fast lane alert sent
    DEEP_PUSHED = "deep_pushed"  # deep analysis sent
    ARCHIVED = "archived"        # not pushed, daily digest only


class Sentiment(Enum):
    BULLISH = "bullish"
    CAUTIOUSLY_BULLISH = "cautiously_bullish"
    NEUTRAL = "neutral"
    CAUTIOUSLY_BEARISH = "cautiously_bearish"
    BEARISH = "bearish"


@dataclass
class NewsItem:
    id: Optional[int] = None
    title: str = ""
    url: str = ""
    source: str = ""             # e.g. "Bloomberg", "CNBC"
    content_snippet: str = ""    # first ~500 chars
    published_at: datetime = field(default_factory=datetime.now)
    captured_at: datetime = field(default_factory=datetime.now)

    # Fast lane
    tickers_found: str = ""       # comma-separated, e.g. "NVDA,AAPL"
    macro_tags: str = ""          # comma-separated, e.g. "CPI,FOMC"
    is_breaking: bool = False
    priority_score: float = 0.0

    # Deep lane (populated later)
    entities: str = ""            # JSON: {"companies":[], "people":[], "indicators":[]}
    sentiment: Optional[str] = None  # Sentiment enum value
    sentiment_score: float = 0.0
    market_impact: str = ""       # "high", "medium", "low"
    llm_analysis: str = ""        # LLM-generated analysis text
    event_line_id: Optional[int] = None

    # Curator
    relevance_score: float = 5.0   # 0-10 personal relevance
    relevance_reason: str = ""     # Why this score

    status: str = NewsStatus.PENDING.value


@dataclass
class EventLine:
    id: Optional[int] = None
    title: str = ""
    news_ids: str = ""            # comma-separated news item IDs
    source_count: int = 0
    first_seen: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    escalation_state: str = "NONE"   # NONE|ALERTED|CONFIRMED|CLOSED
    peak_impact: float = 0.0
    dominant_category: str = ""
    dominant_sentiment: str = ""
    alerted_at: Optional[datetime] = None


@dataclass
class FeedbackRecord:
    id: Optional[int] = None
    news_id: int = 0
    reaction: str = ""            # "thumbs_up", "thumbs_down", "analyze_click", "ignore"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class UserPreference:
    key: str = ""                 # e.g. "source_weight:bloomberg", "topic:semiconductor"
    value: str = ""               # JSON value
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class ImpactAssessment:
    id: Optional[int] = None
    news_id: int = 0
    impact_score: float = 0.0          # 0-100 LLM prediction
    confidence: float = 0.0            # 0-100
    event_category: str = ""            # monetary|geopolitical|macro_data|corporate|regulatory|other
    surprise_level: str = ""            # expected|minor_surprise|major_surprise|shock
    breadth: str = ""                   # single_stock|sector|broad_market|cross_asset
    urgency: str = "INFO"              # FLASH|ALERT|WATCH|INFO — LLM-determined push priority
    sentiment: str = ""                # BULLISH|CAUTIOUSLY_BULLISH|NEUTRAL|CAUTIOUSLY_BEARISH|BEARISH
    greed_index: int = 50              # 0-100, 0=extreme fear, 100=extreme greed
    reasoning_chain: str = ""           # JSON array of 5 strings
    similar_events: str = ""            # JSON array
    expected_moves: str = ""            # JSON dict
    calibration_note: str = ""
    flash_note: str = ""               # 3-5 sentence push narrative (replaces analyst_note for push)
    analyst_note: str = ""              # legacy, kept for backward compat
    key_points: str = ""               # JSON array of 3-5 bullet points
    risk_flags: str = ""               # JSON array of risk warnings
    low_confidence: bool = False
    prompt_version: str = "v1"
    latency_ms: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ImpactOutcome:
    id: Optional[int] = None
    assessment_id: int = 0
    collection_window: str = ""         # '15m' | '1h' | '4h'
    spx_change_pct: float = 0.0
    vix_change_pct: float = 0.0
    sector_changes: str = ""            # JSON dict
    actual_score: float = 0.0           # 0-100 normalized
    collected_at: datetime = field(default_factory=datetime.now)


@dataclass
class EventDecision:
    """Event-driven evaluator output — persisted for audit, calibration, and debugging.

    Unlike ImpactAssessment (which records the legacy Path B LLM output), this
    table records every event_driven evaluation (Path A), whether it pushed or not.
    This closes the "event_driven 决策完全不落库" gap identified in REQ-training-eval.
    """
    id: Optional[int] = None
    news_id: int = 0
    is_event: bool = False
    event_types: str = ""              # JSON array of catalyst codes [1,3]
    intensity: int = 0                 # 1-5 stars (after code-level caps)
    direction: str = "up"              # up/down/neutral
    confirmed: bool = False            # source reliability
    timeliness: str = "immediate"      # immediate|recent|retrospective_new|retrospective
    sector_tags: str = ""              # JSON array
    headline_signal: str = ""          # Chinese push text
    ticker_hint: str = ""              # JSON array of ticker codes
    risk_snapshot: str = ""            # Chinese risk note
    notable: bool = False              # safety-net flag
    filter_reason: str = ""            # why filtered (if is_event=False)
    alert_level: str = "normal"        # final channel level (critical/important/notable/normal)
    raw_json: str = ""                 # raw LLM response for audit
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class CalibrationState:
    id: Optional[int] = None
    category: str = ""                  # event_category or 'global'
    bias: float = 0.0                   # positive = over-estimate
    sample_count: int = 0
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class HealthEvent:
    id: Optional[int] = None
    event_type: str = ""                # quality_reject|llm_timeout|llm_parse_error|degraded
    news_id: int = 0
    detail: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class FundFlowRecord:
    """Single day of capital flow data from East Money per ticker."""
    id: Optional[int] = None
    ticker: str = ""
    date: str = ""                     # "YYYY-MM-DD"
    main_net: float = 0.0              # 主力净流入 (CNY)
    super_big_net: float = 0.0         # 超大单净流入
    big_net: float = 0.0               # 大单净流入
    mid_net: float = 0.0               # 中单净流入
    small_net: float = 0.0             # 小单净流入
    main_pct: float = 0.0              # 主力净占比 (%)
    source: str = ""                   # "push2his" | "ff"
    fetched_at: float = 0.0            # unix timestamp
    created_at: datetime = field(default_factory=datetime.now)
