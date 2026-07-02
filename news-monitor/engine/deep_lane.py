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
from typing import Optional

from config.loader import ConfigLoader
from storage.database import Database
from storage.models import NewsItem, Sentiment
from engine.entity_extractor import EntityExtractor
from engine.sentiment import SentimentAnalyzer
from engine.priority import PriorityScorer, URGENT_THRESHOLD, IMPORTANT_THRESHOLD

logger = logging.getLogger(__name__)

# Default LLM prompt template — 4-step structured Chain-of-Thought
ANALYSIS_PROMPT = """You are a financial markets strategist serving a professional investor. Analyze this news with structured reasoning — do NOT just summarize.

Title: {title}
Source: {source}
Tickers: {tickers}
Macro indicators: {macro_tags}
Sentiment: {sentiment} (score: {sentiment_score:.2f})

{extra_context}

Follow this exact 4-step structure. If you lack information for any step, state "信息不足" rather than guessing.

Step 1 — 事件定性: Classify this event. Is it Macro (interest rate / policy), Sector (supply-demand / technology), or Company-specific (earnings / management)? State the category and why.

Step 2 — 传导路径: Trace the impact chain. Which sectors/positions are directly affected? Through what mechanism (cost, demand, valuation multiples)? Be specific about the causal logic.

Step 3 — 组合映射: Map to the investor's portfolio. Given the holdings and investment rules in the knowledge base, provide 1-3 concrete action scenarios (观望 / 减仓 / 加仓) with trigger conditions for each.

Step 4 — 置信度: Rate your analysis confidence as 高 / 中 / 低. If 低, explicitly state what information is missing and what to monitor.

Respond in Chinese. Be analytical, not journalistic."""

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
        self._max_tokens = 800
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
    # Internal
    # ------------------------------------------------------------------

    async def _call_llm(self, item: NewsItem) -> str:
        """Call LLM for analysis — supports DeepSeek and Anthropic.

        Uses the user's custom analysis framework if set via /analyze set,
        otherwise defaults to the built-in 4-step CoT prompt.

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

        # Get training context from knowledge base
        extra_context = ""
        if self.db:
            try:
                ctx = self.db.get_training_context(max_chars=1500)
                if ctx:
                    extra_context = f"Knowledge Base (investor's framework):\n{ctx}"
            except Exception:
                pass

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
