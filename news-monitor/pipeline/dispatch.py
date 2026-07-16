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
        # Companion cache: topic_key → headline_signal text (for cross-key similarity)
        self._headline_cache: dict[str, str] = {}

    # ── Phone threshold gate ──
    # IMPORTANT alerts only reach phone for watchlist stocks or macro ≥85.
    # Non-watchlist events still hit Telegram, just don't vibrate the phone.
    _PHONE_MACRO_MIN_SCORE = 85

    def _phone_threshold_ok(self, item: PipelineItem) -> tuple[bool, str]:
        """Check if an IMPORTANT item is phone-worthy.

        Returns (ok, reason). ok=False means skip phone, TG only.
        """
        d = item.decision
        tickers = d.ticker_hint or []
        is_macro = bool(item.macro_tags)
        impact = d.impact_score or 0

        # Watchlist / tracked tickers → phone
        if tickers:
            try:
                from engine.relevance import get_tracked_tickers
                tracked = get_tracked_tickers()
                if any(t.upper().strip() in tracked for t in tickers if t and t.strip()):
                    return True, "watchlist_ticker"
            except Exception:
                pass

        # Macro shock ≥ 85 → phone
        if is_macro and impact >= self._PHONE_MACRO_MIN_SCORE:
            return True, f"macro_shock(impact={impact})"

        return False, (
            f"below_phone_threshold(tickers={tickers}, macro={is_macro}, impact={impact})"
        )

    # ── headline_signal similarity threshold for cross-ticker dedup ──
    # When two articles about the same event use different ticker names
    # (e.g. "台积电" vs "TSM"), the ticker-based dedup key won't match.
    # If headline_signal word-level Jaccard ≥ this threshold, treat as
    # same topic and suppress the phone push.
    _HEADLINE_SIMILARITY_THRESHOLD = 0.22

    def _phone_should_skip(self, item: PipelineItem) -> tuple[bool, str]:
        """Check same-topic dedup for phone push.

        Two-tier dedup:
          1. Exact key match (ticker or macro topic)
          2. Cross-key headline_signal similarity (catches 台积电/TSM
             where LLM ticker_hint differs across sources)

        Returns (skip, reason). skip=True means don't push to Pushover.
        """
        key = _dedup_key(item)
        # Fallback key: when ticker_hint is empty and no macro pattern matches,
        # use a headline-content hash so cross-key dedup can still find it.
        if key is None:
            headline_fb = (item.decision.headline_signal or item.title or "").strip()
            if len(headline_fb) > 10:
                import hashlib
                key = f"headline:{hashlib.md5(headline_fb.encode('utf-8', errors='replace')).hexdigest()[:12]}"
        intensity = getattr(item.decision, "intensity", 0) or 0
        headline = (item.decision.headline_signal or item.title or "").strip()
        now = time.time()

        if key is not None:
            prev = self._phone_push_log.get(key)
            if prev is not None:
                prev_intensity, prev_ts, prev_id = prev
                age = now - prev_ts
                if age < _DEDUP_WINDOW_SECONDS:
                    if intensity > prev_intensity:
                        self._phone_push_log[key] = (intensity, now, item.id or 0)
                        self._headline_cache[key] = headline
                        return False, f"intensity_upgrade({prev_intensity}→{intensity})"
                    else:
                        return True, (
                            f"same_topic_dedup(key={key}, prev_id={prev_id}, "
                            f"prev_intensity={prev_intensity}, age={age:.0f}s)"
                        )

        # ── Tier 2: cross-key headline_signal similarity ──
        # Catches 台积电/TSM and other Chinese/English ticker-name mismatches
        # where the LLM ticker_hint differs but the headline describes the
        # same event.  Only runs when there IS a key to log (skip None).
        if headline and key is not None:
            for existing_key, (prev_intensity, prev_ts, prev_id) in self._phone_push_log.items():
                # Skip exact matches (already handled above)
                if existing_key == key:
                    continue
                age = now - prev_ts
                if age >= _DEDUP_WINDOW_SECONDS:
                    continue
                # Compare headline_signal against this entry's key
                # We need the previous item's headline — extract from key
                # or fall back to checking the key itself
                if self._headlines_similar(headline, existing_key, item):
                    if intensity > prev_intensity:
                        self._phone_push_log[key] = (intensity, now, item.id or 0)
                        return False, (
                            f"intensity_upgrade_cross_key({prev_intensity}→{intensity}, "
                            f"prev_key={existing_key})"
                        )
                    return True, (
                        f"headline_similarity_dedup(headline≈prev_key={existing_key}, "
                        f"prev_id={prev_id}, prev_intensity={prev_intensity}, age={age:.0f}s)"
                    )

        # First occurrence or window expired: record and allow
        if key is not None:
            self._phone_push_log[key] = (intensity, now, item.id or 0)
            if headline:
                self._headline_cache[key] = headline
        return False, ""

    def _headlines_similar(
        self, headline: str, existing_key: str, item: PipelineItem,
    ) -> bool:
        """Check if headline is semantically similar to a previously-pushed item.

        Uses word-level Jaccard on headline_signal text.  The existing_key is
        a ticker: or macro: prefix; we store the headline text alongside it
        in a companion dict for lookup.
        """
        prev_text = self._headline_cache.get(existing_key, "")
        if not prev_text:
            return False
        return _jaccard_similarity(headline, prev_text) >= self._HEADLINE_SIMILARITY_THRESHOLD

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

                    # ── Phone threshold gate ──
                    # IMPORTANT alerts only push to phone for watchlist stocks
                    # OR macro events with impact_score ≥ 85.  Everything else
                    # stays Telegram-only (no phone vibration).
                    # (V1 spec: phone-threshold-raise — reduce weekly vibrations)
                    if level == AlertLevel.IMPORTANT:
                        ok, gate_reason = self._phone_threshold_ok(item)
                        if not ok:
                            logger.info(
                                "DISPATCH: phone threshold SKIP #%d: %s",
                                item.id, gate_reason,
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


# ── headlne similarity helper ──

def _is_cjk(ch: str) -> bool:
    return '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿'


def _jaccard_similarity(text1: str, text2: str) -> float:
    """Token-aware Jaccard for Chinese/English headlines.

    Chinese: individual CJK characters (unigrams) — robust against different
            phrasing of the same event (涨价 vs 价格上调, both share 价).
    ASCII: whole words + alphanumeric runs.
    """
    if not text1 or not text2:
        return 0.0

    def _tokenize(t: str) -> set[str]:
        t = t.lower().strip()
        tokens: set[str] = set()
        for word in t.split():
            cjk_run = ""
            ascii_run = ""
            for ch in word:
                if _is_cjk(ch):
                    if ascii_run:
                        tokens.add(ascii_run)
                        ascii_run = ""
                    cjk_run += ch
                else:
                    if cjk_run:
                        tokens.update(cjk_run)  # each CJK char = one token
                        cjk_run = ""
                    if ch.isalnum():
                        ascii_run += ch
                    else:
                        if ascii_run:
                            tokens.add(ascii_run)
                            ascii_run = ""
            if cjk_run:
                tokens.update(cjk_run)
            if ascii_run:
                tokens.add(ascii_run)
        return tokens

    t1 = _tokenize(text1)
    t2 = _tokenize(text2)
    if not t1 or not t2:
        return 0.0
    inter = t1 & t2
    union = t1 | t2
    return len(inter) / len(union) if union else 0.0
