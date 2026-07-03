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
    reasoning_chain: str = ""           # JSON array of 5 strings
    similar_events: str = ""            # JSON array
    expected_moves: str = ""            # JSON dict
    calibration_note: str = ""
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
