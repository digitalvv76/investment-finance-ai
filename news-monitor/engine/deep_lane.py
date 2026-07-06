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

        Returns a compact text block suitable for injection into the LLM
        prompt, or an empty string if no data could be fetched within the
        time budget.

        Data collected (all via yfinance, free, no API key):
          - Per-ticker: price, day change %, volume, vs 20/50 MA
          - Macro: SPX change %, VIX level
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
            # Add top watchlist tickers (max 5 extra to avoid rate limiting)
            extra = list(related)[:5]
            for t in extra:
                if t not in tickers:
                    tickers.append(t)
        except Exception:
            pass

        # Map crypto tickers to yfinance symbols
        crypto_map = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}
        symbols = []
        for t in tickers:
            symbols.append(crypto_map.get(t, t))
        symbols += [_SPX_SYMBOL, _VIX_SYMBOL]

        end = datetime.now() + timedelta(days=1)
        start = datetime.now() - timedelta(days=90)  # enough for 20/50 MA

        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: yf.download(
                    symbols, start=start.strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                    progress=False, auto_adjust=True,
                ),
            )
        except Exception:
            return ""

        if data is None or data.empty:
            return ""

        lines = ["[REAL-TIME MARKET DATA — use this to ground your analysis]"]
        closes = data.get("Close")

        # Per-ticker snapshot — use yfinance symbol for column lookup
        lookup = {t: crypto_map.get(t, t) for t in tickers}
        for ticker in tickers:
            try:
                yf_sym = lookup[ticker]
                if len(symbols) == 1:
                    series = closes
                else:
                    series = closes[yf_sym] if yf_sym in closes.columns else None
                if series is None or series.dropna().empty:
                    continue
                series = series.dropna()
                price = round(float(series.iloc[-1]), 2)
                prev = float(series.iloc[-2]) if len(series) >= 2 else price
                chg_pct = round((price - prev) / prev * 100, 2) if prev != 0 else 0.0

                # Moving averages
                ma20 = round(float(series.rolling(20).mean().iloc[-1]), 2) if len(series) >= 20 else None
                ma50 = round(float(series.rolling(50).mean().iloc[-1]), 2) if len(series) >= 50 else None
                vs_ma20 = ""
                if ma20 and ma20 != 0:
                    vs_ma20 = f" ({'above' if price > ma20 else 'below'} 20MA {ma20})"
                vs_ma50 = ""
                if ma50 and ma50 != 0:
                    vs_ma50 = f" ({'above' if price > ma50 else 'below'} 50MA {ma50})"

                # Volume spike
                vol_ok = False
                try:
                    vol_series = data.get("Volume")
                    if vol_series is not None:
                        if len(symbols) == 1:
                            vol = vol_series
                        else:
                            vol = vol_series[ticker] if ticker in vol_series.columns else None
                        if vol is not None and not vol.dropna().empty:
                            vol = vol.dropna()
                            latest_vol = int(vol.iloc[-1])
                            avg_vol = int(vol.rolling(20).mean().iloc[-1]) if len(vol) >= 20 else latest_vol
                            vol_ratio = round(latest_vol / avg_vol, 1) if avg_vol > 0 else 1.0
                            vol_str = f" | Vol {latest_vol:,} ({vol_ratio}x avg)"
                            vol_ok = True
                except Exception:
                    pass
                if not vol_ok:
                    vol_str = ""

                lines.append(
                    f"  {ticker}: ${price} ({chg_pct:+.2f}% today){vs_ma20}{vs_ma50}{vol_str}"
                )
            except Exception:
                continue

        # Macro snapshot (SPX + VIX)
        try:
            for sym, label in [(_SPX_SYMBOL, "SPX"), (_VIX_SYMBOL, "VIX")]:
                if len(symbols) == 1:
                    s = closes
                else:
                    s = closes[sym] if sym in closes.columns else None
                if s is not None and not s.dropna().empty:
                    s = s.dropna()
                    val = round(float(s.iloc[-1]), 2)
                    prev_val = float(s.iloc[-2]) if len(s) >= 2 else val
                    chg = round((val - prev_val) / prev_val * 100, 2) if prev_val != 0 else 0.0
                    lines.append(f"  {label}: {val} ({chg:+.2f}%)")
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
        try:
            enrichment = await asyncio.wait_for(
                self._fetch_market_enrichment(tickers),
                timeout=_ENRICH_TIMEOUT,
            )
            if enrichment:
                extra_parts.append(enrichment)
        except asyncio.TimeoutError:
            logger.debug("Market enrichment timed out — proceeding without it")
        except Exception as e:
            logger.debug("Market enrichment failed: %s — proceeding without it", e)

        extra_context = "\n\n".join(extra_parts) if extra_parts else ""

        # Use custom framework or default
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
            return await self._call_deepseek(prompt)
        else:
            return await self._call_anthropic(prompt)

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
