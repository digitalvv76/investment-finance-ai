"""Pipeline item — the typed contract flowing through all 5 pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AlertLevel(str, Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"


@dataclass
class DispatchDecision:
    """Output of EVALUATE stage, consumed by DISPATCH stage."""
    alert_level: AlertLevel = AlertLevel.NORMAL
    alert_reason: str = ""
    impact_score: int = 0
    signal_score: float = 0.0
    urgency: str = "INFO"          # FLASH|ALERT|WATCH|INFO — LLM-determined push priority
    sentiment: str = ""            # BULLISH|CAUTIOUSLY_BULLISH|NEUTRAL|CAUTIOUSLY_BEARISH|BEARISH
    greed_index: int = 50          # 0-100 fear/greed context
    analyst_note: str = ""
    flash_note: str = ""           # 3-5 sentence push narrative
    key_points: str = ""           # JSON array of bullet takeaways
    risk_flags: str = ""           # JSON array of risk warnings
    needs_deep: bool = False
    event_category: str = ""
    strategic_matches: list = field(default_factory=list)
    # ── Event-driven evaluation fields ──
    event_types: list[int] = field(default_factory=list)  # catalyst type codes 1-5
    intensity: int = 0           # 1-5 stars, only meaningful when is_event=True
    sector_tags: list[str] = field(default_factory=list)
    headline_signal: str = ""    # 中文一句话交易逻辑
    ticker_hint: list[str] = field(default_factory=list)
    risk_snapshot: str = ""      # 中文最大风险点
    filter_reason: str = ""      # 过滤原因（非事件时）


@dataclass
class PipelineItem:
    """News item flowing through the pipeline. Each stage appends fields."""
    # ── INGEST output ──
    id: int
    title: str
    source: str = ""
    url: str = ""
    snippet: str = ""
    published_at: str = ""
    raw_tickers: list[str] = field(default_factory=list)

    # ── SCREEN output ──
    priority_score: float = 0.0
    tickers_found: str = ""
    macro_tags: str = ""
    is_breaking: bool = False
    people_tier: int = 0

    # ── EVALUATE output ──
    decision: DispatchDecision = field(default_factory=DispatchDecision)

    # ── internal bookkeeping ──
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_raw(cls, raw: dict) -> PipelineItem:
        """Create from raw scheduler dict (INGEST stage input)."""
        return cls(
            id=raw.get("id", 0),
            title=raw.get("title", ""),
            source=raw.get("source", ""),
            url=raw.get("url", ""),
            snippet=raw.get("snippet", raw.get("summary", "")),
            published_at=raw.get("published_at", raw.get("published", "")),
            raw_tickers=raw.get("tickers_found", "").split(",") if raw.get("tickers_found") else [],
            _raw=raw,
        )
