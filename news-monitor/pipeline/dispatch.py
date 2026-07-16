"""DISPATCH stage: route alert decisions to all registered channels."""

from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem, AlertLevel

if TYPE_CHECKING:
    from pipeline.channel import Channel

logger = logging.getLogger(__name__)

_DRY_RUN = os.environ.get("DRY_RUN_PUSH", "").lower() in ("1", "true", "yes")

# ── Same-topic phone dedup ──
# 同一宏观主题在 DEDUP_WINDOW 内只推强度最高的一条到手机，
# 后续除非强度升级（strictly higher）否则跳过 Pushover。
# 不影响 Telegram（TG 仍全量接收，仅静音控制）。
_DEDUP_WINDOW_SECONDS = 6 * 3600  # 6 hours — 覆盖一个完整交易时段

# 从 headline_signal 提取宏观主题关键词
_MACRO_TOPIC_PATTERNS = [
    # 通胀组 (all normalized to "inflation")
    (r'(?:CPI|通胀|inflation)', 'inflation'),
    # 美联储 / 利率组
    (r'(?:FOMC|美联储|Fed\b|利率|降息|加息|rate\s*(?:cut|hike))', 'fed_rate'),
    # 就业组
    (r'(?:非农|就业|失业|NFP|jobless|payroll)', 'employment'),
    # GDP / 经济增速组
    (r'(?:GDP|经济(?:增速|增长|萎缩|衰退)|recession)', 'gdp'),
    # PMI / ISM 组
    (r'(?:PMI|ISM|采购经理)', 'pmi'),
    # PCE / PPI 组
    (r'(?:PCE|PPI|生产者价格)', 'pce_ppi'),
    # 贸易 / 关税组
    (r'(?:关税|tariff|贸易(?:战|摩擦))', 'trade'),
    # 银行财报季组 (银行股 + 财报关键词)
    (r'(?:银行.*(?:财报|盈利|业绩)|(?:摩根|花旗|高盛|富国|美银|小摩|大摩).*(?:财报|盈利|业绩)|bank.*earn(?:ings)?)', 'bank_earnings'),
]
_MACRO_TOPIC_MAP: dict[str, str] = {}
for _pattern, _topic in _MACRO_TOPIC_PATTERNS:
    _MACRO_TOPIC_MAP[_pattern] = _topic

# Compile a single regex: group index → canonical topic
_MACRO_TOPIC_RE = re.compile(
    '|'.join(f'(?P<t{i}>{p})' for i, (p, _) in enumerate(_MACRO_TOPIC_PATTERNS)),
    re.IGNORECASE,
)


def _dedup_key(item: PipelineItem) -> str | None:
    """Derive a topic dedup key for same-event suppression on phone.

    Returns None if the item doesn't match a dedup-able topic pattern.

    Priority:
      1. Ticker-based: if ticker_hint is non-empty → "ticker:<sorted>:<direction>"
      2. Macro-topic: if headline_signal matches known macro patterns → "macro:<topic>:<direction>"
      3. None — pass through (no dedup)
    """
    d = item.decision
    tickers = d.ticker_hint or []
    direction = getattr(d, "direction", "up") or "up"

    if tickers:
        ticker_key = ",".join(sorted(set(t.upper().strip() for t in tickers if t and t.strip())))
        if ticker_key:
            return f"ticker:{ticker_key}:{direction}"

    # Macro topic extraction from headline_signal
    headline = d.headline_signal or item.title or ""
    m = _MACRO_TOPIC_RE.search(headline)
    if m:
        # Find which named group matched and get canonical topic
        for i, (_, topic) in enumerate(_MACRO_TOPIC_PATTERNS):
            if m.group(f"t{i}"):
                return f"macro:{topic}:{direction}"

    return None


class DispatchStage:
    """Pipeline stage 3: dispatch alerts through all registered channels.

    Each channel receives every item and decides internally whether to
    act based on the alert level. Channel failures are isolated — one
    bad channel never blocks another.

    DRY_RUN_PUSH=true → log push decisions, never send to real channels.
    """

    def __init__(self, channels: list[Channel]) -> None:
        self._channels = channels
        # Ring buffer of recent PUSHED decisions (NOTABLE/IMPORTANT/CRITICAL),
        # for the /health/decisions observability panel. NORMAL is skipped.
        self.recent_decisions: deque = deque(maxlen=50)
        # Same-topic phone dedup: topic_key → (intensity, timestamp, item_id)
        self._phone_push_log: dict[str, tuple[int, float, int]] = {}

    def _phone_should_skip(self, item: PipelineItem) -> tuple[bool, str]:
        """Check same-topic dedup for phone push.

        Returns (skip, reason). skip=True means don't push to Pushover.
        """
        key = _dedup_key(item)
        if key is None:
            return False, ""

        intensity = getattr(item.decision, "intensity", 0) or 0
        now = time.time()

        prev = self._phone_push_log.get(key)
        if prev is not None:
            prev_intensity, prev_ts, prev_id = prev
            age = now - prev_ts
            if age < _DEDUP_WINDOW_SECONDS:
                if intensity > prev_intensity:
                    # Intensity upgrade: allow through, update log
                    self._phone_push_log[key] = (intensity, now, item.id or 0)
                    return False, f"intensity_upgrade({prev_intensity}→{intensity})"
                else:
                    return True, (
                        f"same_topic_dedup(key={key}, prev_id={prev_id}, "
                        f"prev_intensity={prev_intensity}, age={age:.0f}s)"
                    )
        # First occurrence or window expired: record and allow
        self._phone_push_log[key] = (intensity, now, item.id or 0)
        return False, ""

    def _record(self, item: PipelineItem, level: AlertLevel, silent: bool) -> None:
        d = item.decision
        self.recent_decisions.appendleft({
            "id": item.id,
            "title": (item.title or "")[:120],
            "level": level.value,
            "silent": silent,
            "ticker_hint": d.ticker_hint,
            "headline_signal": d.headline_signal,
            "reason": getattr(d, "alert_reason", ""),
        })

    # Per-cycle TG push cap: prevent flooding when new sources add volume.
    # Phone (Pushover) is already deduped by topic; TG is the flood risk.
    _MAX_TG_PER_CYCLE = 5

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []

        tg_pushed = 0
        for item in items:
            decision = item.decision
            level = decision.alert_level

            # NORMAL = skip all push channels
            if level == AlertLevel.NORMAL:
                continue
            silent = level == AlertLevel.NOTABLE
            self._record(item, level, silent)

            if _DRY_RUN:
                self._log_push(item, decision, silent)
                continue

            for channel in self._channels:
                # ── Phone dedup ──
                if channel.name == "pushover" and level != AlertLevel.CRITICAL:
                    skip, reason = self._phone_should_skip(item)
                    if skip:
                        logger.info(
                            "DISPATCH: phone dedup SKIP #%d: %s",
                            item.id, reason,
                        )
                        continue

                # ── TG rate limit ──
                if channel.name == "telegram" and tg_pushed >= self._MAX_TG_PER_CYCLE:
                    continue

                try:
                    success = await channel.send(item, decision, disable_notification=silent)
                    if success:
                        if channel.name == "telegram":
                            tg_pushed += 1
                        logger.debug("DISPATCH: %d sent to %s", item.id, channel.name)
                except Exception:
                    logger.exception("DISPATCH: channel %s failed for id=%d",
                                     channel.name, item.id)

        logger.info("DISPATCH: %d items, %d→TG (cap=%d)%s",
                     len(items), tg_pushed, self._MAX_TG_PER_CYCLE,
                     " [DRY_RUN]" if _DRY_RUN else "")
        return items

    @staticmethod
    def _log_push(item: PipelineItem, decision, silent: bool) -> None:
        """Log what would have been pushed in dry-run mode.

        NORMAL items never reach here (skipped upstream). NOTABLE logs as a
        silent would-push so the shadow comparison can see safety-net hits.
        """
        d = decision
        logger.info(
            "DRY_RUN WOULD-PUSH | level=%s%s intensity=%d | %s | tickers=%s | signal=%s | risk=%s",
            d.alert_level.value, " (silent)" if silent else "", d.intensity,
            (item.title or "")[:80],
            d.ticker_hint, d.headline_signal, d.risk_snapshot,
        )
