"""Deep lane orchestrator — full NLP pipeline with optional LLM analysis.

Pipeline:
    1. Entity extraction (spaCy NER + rules)
    2. Sentiment analysis (VADER + financial lexicon)
    3. Priority scoring (multi-factor weight)
    4. LLM analysis (Anthropic Claude, gated by priority threshold)

Thresholds (from settings.yaml):
    Urgent (≥0.7)  → auto LLM call
    Important (0.4-0.69) → on-demand (user clicks "analyze")
    General (<0.4) → no LLM, archive only
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

from config.loader import ConfigLoader
from storage.database import Database
from storage.models import NewsItem, Sentiment
from engine.entity_extractor import EntityExtractor
from engine.sentiment import SentimentAnalyzer
from engine.priority import PriorityScorer, URGENT_THRESHOLD, IMPORTANT_THRESHOLD

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market enrichment — fetched before LLM analysis to ground reasoning in
# real-time price data.  Runs with a hard 8-second timeout so it never
# blocks the user-facing deep analysis button.
# ---------------------------------------------------------------------------
_ENRICH_TIMEOUT = 8.0         # total budget for all market data fetches
_SPX_SYMBOL = "^GSPC"
_VIX_SYMBOL = "^VIX"

# Default LLM prompt template — concise, action-oriented flash note.
# 150-250 words, 3 sections, single recommendation.  No academic essays.
ANALYSIS_PROMPT = """You are a buy-side analyst writing a flash note for a portfolio manager. Be CONCISE. Be ACTIONABLE. Do NOT write an academic essay.

Title: {title}
Source: {source}
Tickers: {tickers}
Macro indicators: {macro_tags}
Sentiment: {sentiment} (score: {sentiment_score:.2f})

{extra_context}

Write a short flash note in Chinese with exactly these 3 sections. 150-250 words total.

CRITICAL RULES:
- Only quote numbers that are explicitly provided in the market data above. If no real-time data is available, say "需查当前价格" rather than guessing.
- ONLY mention tickers listed in the investor's watchlist or the news tickers. Do not invent unrelated stocks.
- The "Action" must be ONE recommendation. Pick one and commit.

1. What happened (1-2 sentences)

2. Market impact (2-3 sentences)

3. Action (1-2 sentences)

Confidence: High/Medium/Low"""

# User-customizable analysis framework (stored in DB preferences)
DEFAULT_ANALYSIS_FRAMEWORK = "default"

# ---------------------------------------------------------------------------
# Anti-fabrication (SPEC-deep-analysis-stale-data.md)
# ---------------------------------------------------------------------------
# When real-time market data is unavailable (timeout / fetch failure), the LLM
# was inventing specific prices, percentages, and trade calls that matched the
# NEWS TONE rather than reality (e.g. "short META -7.64%" when META was +4.70%).
# The soft prompt constraint failed to stop this. These enforce it at code level.

# Banner shown at the top of a card when we have no real-time quotes.
NO_DATA_BANNER = "⚠️ 行情数据缺失 — 本条仅做定性事件解读，无实时价位/涨跌幅/买卖建议"

# Prompt used when NO market data is available — forbids any concrete numbers
# or trade recommendations. Qualitative event interpretation only.
NO_DATA_PROMPT = """You are a buy-side analyst writing a flash note for a portfolio manager. Be CONCISE. Be ACTIONABLE where possible.

Title: {title}
Source: {source}
Tickers: {tickers}
Macro indicators: {macro_tags}
Sentiment: {sentiment} (score: {sentiment_score:.2f})

{extra_context}

⚠️ NO REAL-TIME MARKET DATA IS AVAILABLE FOR THIS ITEM.

Write a short flash note in Chinese with exactly these 2 sections. 100-180 words total.

ABSOLUTE RULES (violating these is a critical error):
- DO NOT output ANY specific price (e.g. $649), percentage change (e.g. -7.64%), moving average, target price, or stop-loss.
- DO NOT give a buy/sell/long/short recommendation — you have no price data to justify it.
- ONLY provide qualitative event interpretation: what happened and the likely DIRECTION of impact (bullish/bearish/neutral) with reasoning.
- ONLY mention tickers listed in the news tickers or watchlist. Do not invent stocks.

1. What happened (2-3 sentences)

2. Qualitative impact & what to watch (2-3 sentences, direction only, NO numbers)

Confidence: Low (no live data)"""

# Regex for concrete market numbers. Must catch REAL Chinese LLM output, not
# just English half-width formats (adversarial review found 美元/％/百分之/裸点位
# all bypassed the naive $/% patterns — same-model blind spot).
#   prices:   $649.2 | $1,234 | 649.2美元 | 649元 | 目标580 | 止损600
#   percents: -7.64% | +4.70% | 7.64％ (full-width) | 7.64个百分点 | 百分之七
_PRICE_DOLLAR_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
_PRICE_CNY_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s?(?:美元|元)")
# Bare number attached to a trade-level keyword (target / stop / position price)
_PRICE_KEYWORD_RE = re.compile(
    r"(?:目标价?|止损|止盈|支撑位?|阻力位?|点位|建仓|买入价|卖出价)\s*[:：]?\s*\d[\d,]*(?:\.\d+)?"
)
_PCT_RE = re.compile(r"[+-]?\d+(?:\.\d+)?\s?(?:%|％|个百分点)")
# Any concrete number token (used only to decide if a sentence carries a claim)
_ANY_PRICE_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:美元|元)"
)

# Trade-action keywords — pure-text calls (no number) still get stripped in
# no-data mode, because a directional call with zero price data is exactly the
# fabrication the soft prompt failed to stop.
_TRADE_KEYWORDS = (
    "做多", "做空", "买入", "卖出", "加仓", "减仓", "抄底", "止损", "止盈",
    "建仓", "清仓", "空头", "多头", "逢高", "逢低",
    "short ", "long ", "buy ", "sell ", "short the", "buy the",
)

# Sentence splitter for Chinese + English punctuation (include full-width comma
# and semicolon so a long comma-joined sentence still gets split).
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;\n])")


def _has_valid_market_data(enrichment: str | None) -> bool:
    """True iff the enrichment block contains at least one real price/quote row.

    A block with only the header line (or empty/whitespace) means the fetch
    produced nothing usable → the hard gate must engage.
    """
    if not enrichment or not enrichment.strip():
        return False
    for line in enrichment.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("["):
            continue  # skip header / bracketed lines
        # A genuine data row carries a price ($) or a percentage.
        if _PRICE_DOLLAR_RE.search(stripped) or _PCT_RE.search(stripped):
            return True
    return False


def _has_ticker_data(enrichment: str | None, tickers_field: str) -> bool:
    """True iff enrichment has a data row for at least one of the news tickers.

    Guards the middle-state bug: enrichment may carry only SPX/VIX macro rows
    (→ _has_valid_market_data True) while every individual stock is missing.
    In that state per-stock numbers would still be fabricated, so we treat the
    item as no-data for gating purposes.
    """
    if not enrichment:
        return False
    tickers = [t.strip().upper() for t in (tickers_field or "").split(",") if t.strip()]
    if not tickers:
        # No specific tickers → macro-level data is acceptable grounding.
        return _has_valid_market_data(enrichment)
    for line in enrichment.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("["):
            continue
        for t in tickers:
            # Row format: "  META: $654.7 (...)". Match the leading label.
            if re.match(rf"{re.escape(t)}\s*[:：]", stripped):
                if _PRICE_DOLLAR_RE.search(stripped) or _PCT_RE.search(stripped):
                    return True
    return False


def _has_trade_recommendation(text: str) -> bool:
    """True iff the text contains a directional trade action keyword."""
    if not text:
        return False
    low = text.lower()
    for kw in _TRADE_KEYWORDS:
        if kw.strip() and (kw in text or kw in low):
            return True
    return False


def _extract_grounded_numbers(enrichment: str) -> set[str]:
    """Collect the numeric tokens that legitimately appear as PRICES/PERCENTS.

    Only pull numbers that are themselves prices ($/美元/元) or percentages
    (%/％/个百分点). Deliberately do NOT harvest bare numbers like MA periods
    ("20MA") or volumes — those would launder fabricated "-20%" claims
    (adversarial review found 20% washed by 20MA).
    """
    grounded: set[str] = set()
    if not enrichment:
        return grounded
    for m in _PRICE_DOLLAR_RE.finditer(enrichment):
        grounded.add(m.group().lstrip("$").replace(",", "").strip())
    for m in _PRICE_CNY_RE.finditer(enrichment):
        grounded.add(re.sub(r"(?:美元|元)", "", m.group()).replace(",", "").strip())
    for m in _PCT_RE.finditer(enrichment):
        grounded.add(re.sub(r"(?:%|％|个百分点)", "", m.group()).lstrip("+-").strip())
    # MA levels are real prices too — pull the number after "MA".
    for m in re.finditer(r"\d+MA\s+(\d[\d,]*(?:\.\d+)?)", enrichment):
        grounded.add(m.group(1).replace(",", ""))
    return grounded


def _sentence_numbers(sentence: str) -> list[str]:
    """Extract normalized price/percent tokens from a sentence."""
    nums: list[str] = []
    for m in _PRICE_DOLLAR_RE.finditer(sentence):
        nums.append(m.group().lstrip("$").replace(",", "").strip())
    for m in _PRICE_CNY_RE.finditer(sentence):
        nums.append(re.sub(r"(?:美元|元)", "", m.group()).replace(",", "").strip())
    for m in _PRICE_KEYWORD_RE.finditer(sentence):
        num = re.search(r"\d[\d,]*(?:\.\d+)?", m.group())
        if num:
            nums.append(num.group().replace(",", ""))
    for m in _PCT_RE.finditer(sentence):
        nums.append(re.sub(r"(?:%|％|个百分点)", "", m.group()).lstrip("+-").strip())
    return nums


def _strip_fabricated_numbers(
    llm_text: str, enrichment: str, no_data: bool = False,
) -> tuple[str, list[str]]:
    """Remove sentences whose prices/percents are NOT grounded in enrichment.

    Last line of defence: any concrete number the LLM produced that can't be
    matched to the real market block is treated as fabricated and its sentence
    is dropped. Handles Chinese/full-width formats (美元/元/％/个百分点) and
    bare target/stop prices.

    When ``no_data`` is True, sentences carrying a directional trade call
    (做空/买入/...) are ALSO stripped even without a number — a trade
    recommendation with zero price data is unjustifiable.

    Returns (cleaned_text, flagged_fragments).
    """
    grounded = _extract_grounded_numbers(enrichment)
    kept: list[str] = []
    flagged: list[str] = []

    for sentence in _SENT_SPLIT_RE.split(llm_text):
        if not sentence.strip():
            continue
        nums = _sentence_numbers(sentence)

        if nums and any(n not in grounded for n in nums):
            flagged.append(sentence.strip())
            continue  # drop the whole sentence — ungrounded number
        if no_data and _has_trade_recommendation(sentence):
            flagged.append(sentence.strip())
            continue  # no data → no directional call allowed
        kept.append(sentence)

    return "".join(kept), flagged


class DeepLane:
    """Deep analysis pipeline for financial news.

    Runs after fast lane has pushed an alert. Processes items through
    entity extraction -> sentiment -> priority -> (optional) LLM analysis.

    LLM Provider Support:
    - Anthropic Claude: set ANTHROPIC_API_KEY, model='claude-fable-5'
    - DeepSeek: set DEEPSEEK_API_KEY, model='deepseek-chat'
    - Auto-detect: checks DEEPSEEK_API_KEY first, then ANTHROPIC_API_KEY

    LLM calls are gated:
    - priority >= 0.7: auto-call LLM immediately
    - priority 0.4-0.69: LLM on-demand (triggered by user)
    - priority < 0.4: no LLM, just tag and archive
    """

    # Provider configurations
    PROVIDERS = {
        "deepseek": {
            "env_key": "DEEPSEEK_API_KEY",
            "default_model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
        },
        "anthropic": {
            "env_key": "ANTHROPIC_API_KEY",
            "default_model": "claude-fable-5",
            "base_url": None,  # Uses SDK default
        },
    }

    def __init__(self, config: ConfigLoader = None, db: Database = None):
        self.db = db
        self._extractor = EntityExtractor(config)
        self._sentiment = SentimentAnalyzer()
        self._scorer = PriorityScorer()

        # Detect LLM provider from environment
        self._provider = self._detect_provider()
        self._model = self._provider["default_model"]
        self._max_tokens = 1500
        self._api_key = os.environ.get(self._provider["env_key"], "")

        if config:
            try:
                settings = config.load_settings()
                deep = settings.get("deep_lane", {})
                configured_model = deep.get("llm_model", "")
                if configured_model:
                    self._model = configured_model
                self._max_tokens = deep.get("max_tokens", self._max_tokens)
            except Exception:
                pass

    @classmethod
    def _detect_provider(cls) -> dict:
        """Auto-detect which LLM provider to use based on env vars."""
        if os.environ.get("DEEPSEEK_API_KEY"):
            return cls.PROVIDERS["deepseek"]
        if os.environ.get("ANTHROPIC_API_KEY"):
            return cls.PROVIDERS["anthropic"]
        # Default to deepseek if no keys set (will use fallback analysis)
        return cls.PROVIDERS["deepseek"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process(self, item: NewsItem) -> NewsItem:
        """Run the full deep lane pipeline on a news item.

        This mutates the item in place and writes results back to DB.

        Args:
            item: The news item to analyze (must have id and be in DB).

        Returns:
            The same item, enriched with deep analysis fields.
        """
        text = f"{item.title or ''} {item.content_snippet or ''}"

        # 1. Entity extraction
        entities = self._extractor.extract(text)
        tickers = set(entities.get("tickers", []))
        macro_tags = set(entities.get("indicators", []))
        has_people = len(entities.get("people", [])) > 0

        # Update tickers/macro if fast lane missed any
        existing_tickers = set(item.tickers_found.split(',')) if item.tickers_found else set()
        existing_macros = set(item.macro_tags.split(',')) if item.macro_tags else set()
        all_tickers = existing_tickers | tickers
        all_macros = existing_macros | macro_tags

        item.tickers_found = ','.join(all_tickers) if all_tickers else ''
        item.macro_tags = ','.join(all_macros) if all_macros else ''
        item.entities = json.dumps(entities, ensure_ascii=False)

        # 2. Sentiment analysis
        sentiment, score = self._sentiment.analyze(text)
        item.sentiment = sentiment.value
        item.sentiment_score = round(score, 4)

        # 3. Priority rescoring (with full entity context)
        item.priority_score = self._scorer.score(
            item,
            tickers=all_tickers,
            macro_tags=all_macros,
            has_people=has_people,
        )

        # 4. Determine market impact
        item.market_impact = self._assess_impact(item.priority_score, len(all_tickers))

        # 5. LLM analysis (gated)
        if item.priority_score >= URGENT_THRESHOLD:
            item.llm_analysis = await self._call_llm(item)
            item.status = 'deep_pushed'
            logger.info(
                "Deep lane: auto LLM for #%d (priority=%.2f, %d tickers)",
                item.id, item.priority_score, len(all_tickers),
            )
        elif item.priority_score >= IMPORTANT_THRESHOLD:
            # Important but not urgent — mark for on-demand analysis
            item.status = 'fast_pushed'  # Keep fast_pushed; user can trigger
            logger.info(
                "Deep lane: on-demand ready for #%d (priority=%.2f)",
                item.id, item.priority_score,
            )
        else:
            item.status = 'archived'
            logger.debug("Deep lane: archived #%d (priority=%.2f)", item.id, item.priority_score)

        # Persist to DB
        if self.db and item.id:
            self.db.update_news_status(
                item.id, item.status,
                entities=item.entities,
                sentiment=item.sentiment,
                sentiment_score=item.sentiment_score,
                market_impact=item.market_impact,
                llm_analysis=item.llm_analysis or '',
                tickers_found=item.tickers_found,
                macro_tags=item.macro_tags,
                priority_score=item.priority_score,
            )

        return item

    async def process_on_demand(self, item: NewsItem) -> NewsItem:
        """Run deep analysis on user request (via Telegram button).

        Forces LLM call regardless of priority threshold.
        """
        text = f"{item.title or ''} {item.content_snippet or ''}"

        # Run entity extraction if not yet done
        if not item.entities:
            entities = self._extractor.extract(text)
            item.entities = json.dumps(entities, ensure_ascii=False)

        # Run sentiment if not yet done
        if not item.sentiment:
            sentiment, score = self._sentiment.analyze(text)
            item.sentiment = sentiment.value
            item.sentiment_score = round(score, 4)

        # Force LLM call
        item.llm_analysis = await self._call_llm(item)
        item.status = 'deep_pushed'

        # Persist
        if self.db and item.id:
            self.db.update_news_status(
                item.id, item.status,
                entities=item.entities,
                sentiment=item.sentiment or '',
                sentiment_score=item.sentiment_score,
                llm_analysis=item.llm_analysis or '',
            )

        return item

    # ------------------------------------------------------------------
    # Market enrichment (real-time data → grounds LLM analysis)
    # ------------------------------------------------------------------

    async def _fetch_market_enrichment(self, tickers_field: str) -> str:
        """Fetch real-time market data for the tickers mentioned in the news.

        Three-phase fetch:
          1. Daily bars (90 days) → 20/50 MA and volume baseline.
          2. Ticker.info per stock → real-time price (pre/regular/post-market).
          3. Intraday 5-min bars → real-time for indices (^GSPC, ^VIX) and
             crypto (BTC-USD, etc.) which don't have standard info fields.

        Phase label comes from Ticker.info ``marketState`` (more accurate than
        clock-based guessing): PRE → pre-market, REGULAR → today,
        POST → after-hours, CLOSED → close.

        Returns a compact text block for LLM prompt injection, or "" on failure.
        """
        tickers = [t.strip().upper() for t in tickers_field.split(",") if t.strip()]
        tickers = [t for t in tickers if t.isalpha() and 1 <= len(t) <= 5]

        # Also include watchlist tickers most likely impacted by this news
        try:
            from engine.relevance import _get_watchlist
            wl = _get_watchlist()
            related = set()
            for wt in wl:
                if wt in ("BTC", "ETH", "SOL"):
                    continue  # handled via crypto suffixes below
                related.add(wt)
            extra = list(related)[:5]
            for t in extra:
                if t not in tickers:
                    tickers.append(t)
        except Exception:
            pass

        # Separate equity tickers from crypto (different price sources)
        crypto_map = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}
        equity_tickers = [t for t in tickers if t not in crypto_map]
        cryptos = [crypto_map[t] for t in tickers if t in crypto_map]

        # All yfinance symbols for the daily download
        daily_symbols = list(equity_tickers) + cryptos + [_SPX_SYMBOL, _VIX_SYMBOL]

        end = datetime.now() + timedelta(days=1)
        start = datetime.now() - timedelta(days=90)

        loop = asyncio.get_event_loop()

        # ---- Phase 1: daily bars for MAs + volume baseline ----
        try:
            daily = await loop.run_in_executor(
                None,
                lambda: yf.download(
                    daily_symbols, start=start.strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                    progress=False, auto_adjust=True,
                ),
            )
        except Exception:
            return ""

        if daily is None or daily.empty:
            return ""

        # ---- Phase 2: Ticker.info per equity ticker (parallel, real-time) ----
        # info dicts include: regularMarketPrice, preMarketPrice, postMarketPrice,
        # regularMarketChangePercent, preMarketChangePercent, postMarketChangePercent,
        # regularMarketVolume, marketState, previousClose
        info_map: dict = {}   # ticker → info dict
        phase = "latest"
        if equity_tickers:
            def _fetch_one_info(tkr: str):
                try:
                    return yf.Ticker(tkr).info
                except Exception:
                    return None
            infos = await loop.run_in_executor(
                None,
                lambda: [_fetch_one_info(t) for t in equity_tickers],
            )
            for tkr, info in zip(equity_tickers, infos):
                if info:
                    info_map[tkr] = info
            # Derive market phase from the first available info
            for info in info_map.values():
                state = info.get("marketState", "")
                if state == "PRE":
                    phase = "pre-market"
                elif state == "REGULAR":
                    phase = "today"
                elif state == "POST":
                    phase = "after-hours"
                if phase != "latest":
                    break

        # Fallback: clock-based phase if no info could determine it
        if phase == "latest":
            now = datetime.now()
            is_weekday = now.weekday() < 5
            hour = now.hour + now.minute / 60.0
            if is_weekday and 4 <= hour < 9.5:
                phase = "pre-market"
            elif is_weekday and 9.5 <= hour < 16:
                phase = "today"
            elif is_weekday and 16 <= hour < 20:
                phase = "after-hours"

        # ---- Phase 3: intraday 5-min for indices + crypto (no Ticker.info) ----
        intraday_needed = cryptos + [_SPX_SYMBOL, _VIX_SYMBOL]
        intraday = None
        if intraday_needed:
            try:
                intraday = await loop.run_in_executor(
                    None,
                    lambda: yf.download(
                        intraday_needed, period="1d", interval="5m",
                        progress=False, auto_adjust=True,
                    ),
                )
            except Exception:
                logger.debug("Intraday download failed — falling back to daily")

        # ---- Assemble output ----
        lines = ["[REAL-TIME MARKET DATA — use this to ground your analysis]"]
        daily_closes = daily.get("Close")
        daily_volumes = daily.get("Volume")
        single_sym = len(daily_symbols) == 1

        def _d_series(col: str):
            """Extract clean daily Close series for a symbol."""
            if daily_closes is None:
                return None
            if single_sym:
                s = daily_closes.dropna()
            else:
                s = daily_closes[col].dropna() if col in daily_closes.columns else None
            return s if (s is not None and not s.empty) else None

        def _v_series(col: str):
            """Extract clean daily Volume series for a symbol."""
            if daily_volumes is None:
                return None
            if single_sym:
                s = daily_volumes.dropna()
            else:
                s = daily_volumes[col].dropna() if col in daily_volumes.columns else None
            return s if (s is not None and not s.empty) else None

        def _intraday_price(col: str):
            """Return current price from intraday data if it's from today, else None."""
            if intraday is None or intraday.empty:
                return None
            ic = intraday.get("Close")
            if ic is None:
                return None
            if single_sym:
                i_s = ic.dropna()
            else:
                i_s = ic[col].dropna() if col in ic.columns else None
            if i_s is None or i_s.empty:
                return None
            last_ts = i_s.index[-1]
            last_date = last_ts.date() if hasattr(last_ts, "date") else last_ts
            if last_date != datetime.now().date():
                return None
            return round(float(i_s.iloc[-1]), 2)

        # ---- Per-ticker lines ----
        for ticker in tickers:
            try:
                if ticker in crypto_map:
                    # Crypto: intraday → daily fallback
                    col = crypto_map[ticker]
                    d_s = _d_series(col)
                    if d_s is None:
                        continue
                    price = _intraday_price(col) or round(float(d_s.iloc[-1]), 2)
                    # Previous close = last daily close before today
                    prev = float(d_s.iloc[-2]) if len(d_s) >= 2 else price
                elif ticker in info_map:
                    # Equity stock: use Ticker.info for real-time price
                    info = info_map[ticker]
                    d_s = _d_series(ticker)
                    if d_s is None:
                        continue
                    state = info.get("marketState", "")
                    price = None
                    if state == "PRE":
                        price = info.get("preMarketPrice")
                    elif state == "POST":
                        price = info.get("postMarketPrice")
                    if price is None:
                        price = info.get("regularMarketPrice")
                    if price is None:
                        price = round(float(d_s.iloc[-1]), 2)
                    price = round(float(price), 2)
                    prev = float(info.get("previousClose", d_s.iloc[-2] if len(d_s) >= 2 else price))
                else:
                    # Equity stock without info (shouldn't happen) — daily fallback
                    d_s = _d_series(ticker)
                    if d_s is None:
                        continue
                    price = round(float(d_s.iloc[-1]), 2)
                    prev = float(d_s.iloc[-2]) if len(d_s) >= 2 else price

                chg_pct = round((price - prev) / prev * 100, 2) if prev != 0 else 0.0

                # MAs from daily data
                d_s = _d_series(crypto_map.get(ticker, ticker))
                ma20 = round(float(d_s.rolling(20).mean().iloc[-1]), 2) if d_s is not None and len(d_s) >= 20 else None
                ma50 = round(float(d_s.rolling(50).mean().iloc[-1]), 2) if d_s is not None and len(d_s) >= 50 else None
                vs_ma20 = f" ({'above' if price > ma20 else 'below'} 20MA {ma20})" if ma20 else ""
                vs_ma50 = f" ({'above' if price > ma50 else 'below'} 50MA {ma50})" if ma50 else ""

                # Volume spike
                vol_str = ""
                v_s = _v_series(crypto_map.get(ticker, ticker))
                if v_s is not None:
                    try:
                        latest_vol = int(v_s.iloc[-1])
                        avg_vol = int(v_s.rolling(20).mean().iloc[-1]) if len(v_s) >= 20 else latest_vol
                        ratio = round(latest_vol / avg_vol, 1) if avg_vol > 0 else 1.0
                        vol_str = f" | Vol {latest_vol:,} ({ratio}x avg)"
                    except Exception:
                        pass

                lines.append(
                    f"  {ticker}: ${price} ({chg_pct:+.2f}% {phase}){vs_ma20}{vs_ma50}{vol_str}"
                )
            except Exception:
                continue

        # ---- Macro snapshot (SPX + VIX) ----
        try:
            for sym, label in [(_SPX_SYMBOL, "SPX"), (_VIX_SYMBOL, "VIX")]:
                d_s = _d_series(sym)
                if d_s is None:
                    continue
                price = _intraday_price(sym) or round(float(d_s.iloc[-1]), 2)
                prev = float(d_s.iloc[-2]) if len(d_s) >= 2 else price
                chg = round((price - prev) / prev * 100, 2) if prev != 0 else 0.0
                lines.append(f"  {label}: {price} ({chg:+.2f}%)")
        except Exception:
            pass

        if len(lines) == 1:
            return ""  # no data collected

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _call_llm(self, item: NewsItem) -> str:
        """Call LLM for analysis — supports DeepSeek and Anthropic.

        Uses the user's custom analysis framework if set via /analyze set,
        otherwise defaults to the built-in 4-step CoT prompt.

        Before calling the LLM, fetches real-time market data (price,
        technicals, macro) for the tickers mentioned in the news so the
        analysis is grounded in current conditions, not just the text.

        Returns the LLM's analysis text, or fallback on failure.
        """
        provider_name = self._provider["env_key"]
        if not self._api_key:
            logger.warning(
                "%s not set — skipping LLM analysis", provider_name
            )
            return self._fallback_analysis(item)

        # Load user-customized framework if available
        custom_framework = ""
        if self.db:
            try:
                custom_framework = self.db.get_preference("analysis_framework") or ""
            except Exception:
                pass

        # Build extra context: portfolio/watchlist + knowledge base + market data
        extra_parts = []

        # 1. Watchlist & portfolio — gives LLM the investor's actual holdings
        from engine.relevance import get_portfolio_summary
        try:
            ps = get_portfolio_summary()
            wl = ps.get("watchlist_tickers", [])
            pf = ps.get("portfolio_tickers", [])
            if wl or pf:
                lines = ["[INVESTOR PORTFOLIO — focus your analysis here]"]
                if pf:
                    lines.append(f"Portfolio: {', '.join(pf)}")
                if wl:
                    lines.append(f"Watchlist: {', '.join(wl)}")
                extra_parts.append("\n".join(lines))
        except Exception:
            pass

        # 2. Training / knowledge base context
        if self.db:
            try:
                ctx = self.db.get_training_context(max_chars=800)
                if ctx:
                    extra_parts.append(f"Knowledge Base:\n{ctx}")
            except Exception:
                pass

        # 2. Real-time market enrichment (with hard timeout)
        tickers = item.tickers_found or ""
        enrichment = ""
        try:
            enrichment = await asyncio.wait_for(
                self._fetch_market_enrichment(tickers),
                timeout=_ENRICH_TIMEOUT,
            )
            if enrichment:
                extra_parts.append(enrichment)
        except asyncio.TimeoutError:
            # WARNING (not debug) — this is the trigger for the fabrication bug,
            # must be visible in production logs. (SPEC §4④)
            logger.warning(
                "Market enrichment TIMED OUT after %.1fs for #%s — "
                "engaging no-data hard gate (no numbers allowed)",
                _ENRICH_TIMEOUT, getattr(item, "id", "?"),
            )
        except Exception as e:
            logger.warning(
                "Market enrichment FAILED for #%s: %s — engaging no-data hard gate",
                getattr(item, "id", "?"), e,
            )

        extra_context = "\n\n".join(extra_parts) if extra_parts else ""

        # ── ① HARD GATE: no valid ticker data → forbid concrete numbers ──
        # Use per-ticker check (not just macro rows) to close the middle-state
        # gap where only SPX/VIX are present but every stock is missing.
        has_data = _has_ticker_data(enrichment, tickers)

        # Use custom framework or default. When no data, custom frameworks are
        # bypassed in favour of the no-data prompt (safety over customization).
        if not has_data:
            template = NO_DATA_PROMPT
            logger.info(
                "Deep lane: #%s has NO ticker market data → qualitative-only prompt",
                getattr(item, "id", "?"),
            )
        else:
            template = custom_framework if custom_framework else ANALYSIS_PROMPT

        prompt = template.format(
            title=item.title or '(no title)',
            source=item.source or 'unknown',
            tickers=item.tickers_found or 'none',
            macro_tags=item.macro_tags or 'none',
            sentiment=item.sentiment or 'neutral',
            sentiment_score=item.sentiment_score,
            extra_context=extra_context,
        )

        if provider_name == "DEEPSEEK_API_KEY":
            analysis = await self._call_deepseek(prompt)
        else:
            analysis = await self._call_anthropic(prompt)

        # ── ② OUTPUT VALIDATION: strip ungrounded price/percent + (no-data)
        #     pure-text trade calls ──
        cleaned, flagged = _strip_fabricated_numbers(
            analysis, enrichment, no_data=not has_data,
        )
        if flagged:
            logger.warning(
                "Deep lane: #%s LLM produced %d ungrounded/unjustified fragment(s) "
                "— stripped: %s",
                getattr(item, "id", "?"), len(flagged),
                " | ".join(f[:50] for f in flagged),
            )
            analysis = cleaned

        # Prepend the missing-data banner so the card is visibly qualitative-only.
        if not has_data:
            if not analysis.strip():
                # Everything the LLM said was fabricated and got stripped —
                # don't return an empty card; state the situation plainly.
                analysis = "本条暂无可靠分析（实时行情缺失，已过滤未经证实的数据）。"
            if NO_DATA_BANNER not in analysis:
                analysis = f"{NO_DATA_BANNER}\n\n{analysis}"

        return analysis

    # ------------------------------------------------------------------
    # Analysis framework management
    # ------------------------------------------------------------------

    def get_framework(self) -> str:
        """Get the current analysis framework (user-customized or default)."""
        if self.db:
            custom = self.db.get_preference("analysis_framework") or ""
            if custom:
                return custom
        return ANALYSIS_PROMPT

    def set_framework(self, framework: str):
        """Save a user-customized analysis framework."""
        if self.db:
            self.db.set_preference("analysis_framework", framework)
            logger.info("Custom analysis framework saved (%d chars)", len(framework))

    def reset_framework(self):
        """Reset to the default analysis framework."""
        if self.db:
            self.db.set_preference("analysis_framework", "")
            logger.info("Analysis framework reset to default")

    async def _call_deepseek(self, prompt: str) -> str:
        """Call DeepSeek API (OpenAI-compatible) — non-blocking.

        Wraps the synchronous OpenAI client call in run_in_executor to
        avoid blocking the asyncio event loop.
        """
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=self._api_key,
                base_url=self._provider["base_url"],
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content.strip()
        except ImportError:
            logger.warning("openai package not installed — run: pip install openai")
        except Exception as e:
            logger.error("DeepSeek call failed: %s", e)

        return self._fallback_analysis(None)

    async def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic Claude API — non-blocking.

        Wraps the synchronous Anthropic client call in run_in_executor to
        avoid blocking the asyncio event loop.
        """
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            if response.content and len(response.content) > 0:
                return response.content[0].text.strip()
        except ImportError:
            logger.warning("anthropic package not installed — run: pip install anthropic")
        except Exception as e:
            logger.error("Anthropic call failed: %s", e)

        return self._fallback_analysis(None)

    @staticmethod
    def _fallback_analysis(item=None) -> str:
        """Generate a simple rule-based analysis when LLM is unavailable."""
        if item is None:
            return "LLM analysis unavailable. Check API key and network."
        parts = []
        impact = item.market_impact or 'medium'
        direction = item.sentiment or 'neutral'
        tickers = item.tickers_found or ''

        if direction in ('bullish', 'cautiously_bullish'):
            parts.append(f"市场影响: {impact} | 方向: 偏多")
        elif direction in ('bearish', 'cautiously_bearish'):
            parts.append(f"市场影响: {impact} | 方向: 偏空")
        else:
            parts.append(f"市场影响: {impact} | 方向: 中性")

        if tickers:
            parts.append(f"相关标的: {tickers}")

        if item.macro_tags:
            parts.append(f"宏观主题: {item.macro_tags}")

        return '; '.join(parts)

    @staticmethod
    def _assess_impact(priority: float, ticker_count: int) -> str:
        """Assess market impact level from priority and ticker count."""
        if priority >= 0.7 or ticker_count >= 3:
            return "high"
        elif priority >= 0.4 or ticker_count >= 1:
            return "medium"
        else:
            return "low"
