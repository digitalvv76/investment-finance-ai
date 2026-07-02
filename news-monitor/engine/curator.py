"""AI-powered news curator — personalizes news feed via LLM.

Uses the user's natural-language interest profile to semantically
score each incoming article for relevance. Replaces simple keyword
matching with contextual understanding.
"""
import json
import logging
import os
from typing import List, Dict, Optional

from storage.database import Database
from storage.models import NewsItem

logger = logging.getLogger(__name__)

CURATOR_PROMPT = """You are a personal news curator. Your job is to score how relevant each news headline is to the user's interests, and assess potential market impact.

=== USER PROFILE ===
{profile_description}

=== LEARNED KNOWLEDGE (from user-provided documents) ===
{learned_knowledge}

=== POSITIVE EXAMPLES (news user found relevant) ===
{positive_examples}

=== NEGATIVE EXAMPLES (news user does NOT want) ===
{negative_examples}

=== SCORING RULES ===
- Score 9-10: Directly about user's core interests. Would be the first thing they read.
- Score 7-8: Clearly relevant. User would want to know.
- Score 5-6: Somewhat relevant. Worth a glance.
- Score 3-4: Tangentially related. Probably skip.
- Score 1-2: Not relevant. Skip.
- Score 0: User explicitly does not want this.
- Consider the LEARNED KNOWLEDGE: if the user has uploaded analysis frameworks or investment theses, use them to judge relevance and market impact.

=== NEWS HEADLINES TO SCORE ===
{headlines}

=== OUTPUT FORMAT ===
Return ONLY a JSON array. Each item: {{"id": <number>, "score": <0-10>, "reason": "<brief Chinese reason>"}}

JSON:"""

DEFAULT_PROFILE = {
    "description": "我是一名全球宏观投资者，关注美联储货币政策、通胀数据、地缘政治风险、以及大型科技股（尤其是AI和半导体行业）的动态。同时也关注重大市场事件和系统性风险。",
    "examples": [
        "美联储宣布加息25个基点，暗示进一步紧缩",
        "NVDA发布新一代AI芯片，性能大幅提升",
        "CPI数据超预期，市场大幅下跌",
    ],
    "anti_examples": [
        "某小型生物科技公司获得FDA批准",
        "比特币短线波动分析",
        "日本央行维持利率不变",
    ],
    "focus_tickers": ["NVDA", "AMD", "MSFT", "GOOGL", "AAPL", "TSLA"],
    "focus_sectors": ["半导体", "AI", "云计算", "金融"],
    "ignore_sectors": ["加密货币", "能源", "大宗商品"],
    "language": "zh",
}


class Curator:
    """AI-powered news curator using DeepSeek.

    Loads the user's interest profile and training knowledge from DB,
    then scores incoming news batches for personal relevance.
    """

    def __init__(self, db: Database, trainer=None):
        self.db = db
        self.trainer = trainer
        self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_profile(self) -> dict:
        """Load the user's curator profile."""
        raw = self.db.get_preference("curator_profile")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return DEFAULT_PROFILE.copy()

    def save_profile(self, profile: dict):
        """Save the user's curator profile."""
        self.db.set_preference("curator_profile", json.dumps(profile, ensure_ascii=False))

    def set_description(self, text: str):
        """Set the core interest description."""
        profile = self.get_profile()
        profile["description"] = text
        self.save_profile(profile)

    def add_example(self, headline: str):
        """Add a positive example headline."""
        profile = self.get_profile()
        if headline not in profile.get("examples", []):
            profile.setdefault("examples", []).append(headline)
        self.save_profile(profile)

    def add_anti_example(self, headline: str):
        """Add a negative example headline."""
        profile = self.get_profile()
        if headline not in profile.get("anti_examples", []):
            profile.setdefault("anti_examples", []).append(headline)
        self.save_profile(profile)

    def add_focus_ticker(self, ticker: str):
        """Add a ticker to focus list."""
        profile = self.get_profile()
        if ticker.upper() not in profile.get("focus_tickers", []):
            profile.setdefault("focus_tickers", []).append(ticker.upper())
        self.save_profile(profile)

    def reset_profile(self):
        """Reset to default profile."""
        self.save_profile(DEFAULT_PROFILE.copy())

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    async def score_batch(self, items: List[NewsItem]) -> List[NewsItem]:
        """Score a batch of news items for personal relevance.

        Each item gets a `relevance_score` (0-10) and `relevance_reason`.

        If no API key or profile is default/empty, falls back to
        simple ticker + sector matching without LLM.
        """
        profile = self.get_profile()

        # If no profile set and no examples, use fast keyword scoring
        if not profile.get("examples") and not profile.get("anti_examples"):
            return self._keyword_score(items, profile)

        # Use LLM for semantic scoring
        client = self._get_client()
        if not client:
            return self._keyword_score(items, profile)

        try:
            scores = await self._llm_score(items, profile, client)
            for item, (score, reason) in zip(items, scores):
                item.relevance_score = score
                item.relevance_reason = reason
        except Exception as e:
            logger.warning("LLM curation failed, using keyword fallback: %s", e)
            return self._keyword_score(items, profile)

        return items

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            key = os.environ.get("DEEPSEEK_API_KEY", "")
            if key:
                try:
                    from openai import OpenAI
                    self._client = OpenAI(
                        api_key=key,
                        base_url="https://api.deepseek.com",
                    )
                except ImportError:
                    pass
        return self._client

    async def _llm_score(self, items, profile, client) -> List[tuple]:
        """Score items via DeepSeek LLM."""
        # Build headlines list
        headlines = "\n".join(
            f"ID:{i} | {item.title[:120]}"
            for i, item in enumerate(items)
        )

        # Get training context
        learned = "无"
        if self.trainer:
            ctx = self.trainer.get_context()
            if ctx:
                learned = ctx

        prompt = CURATOR_PROMPT.format(
            profile_description=profile.get("description", "未设置"),
            learned_knowledge=learned,
            positive_examples="\n".join(f"- {e}" for e in profile.get("examples", [])[:5]) or "无",
            negative_examples="\n".join(f"- {e}" for e in profile.get("anti_examples", [])[:5]) or "无",
            headlines=headlines,
        )

        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=500,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
        )

        raw = response.choices[0].message.content.strip()
        # Extract JSON from response (may have markdown fences)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)

        # Build score map
        score_map = {}
        for entry in result:
            score_map[entry["id"]] = (
                min(10, max(0, entry.get("score", 5))),
                entry.get("reason", ""),
            )

        return [score_map.get(i, (5, "")) for i in range(len(items))]

    def _keyword_score(self, items: List[NewsItem], profile: dict) -> List[NewsItem]:
        """Fast keyword-based scoring (no LLM needed)."""
        focus_tickers = set(t.upper() for t in profile.get("focus_tickers", []))
        focus_sectors = set(s.lower() for s in profile.get("focus_sectors", []))
        ignore_sectors = set(s.lower() for s in profile.get("ignore_sectors", []))
        anti_keywords = set()
        for anti in profile.get("anti_examples", []):
            anti_keywords.update(anti.lower().split())

        for item in items:
            text = f"{item.title or ''} {item.content_snippet or ''}".lower()
            score = 5  # Neutral baseline
            reasons = []

            # Ticker match
            tickers = set((item.tickers_found or "").split(","))
            ticker_hits = tickers & focus_tickers
            if ticker_hits:
                score += 3
                reasons.append(f"关注标的: {','.join(ticker_hits)}")

            # Sector match
            for sector in focus_sectors:
                if sector in text:
                    score += 2
                    reasons.append(f"关注领域: {sector}")
                    break

            # Sector ignore
            for sector in ignore_sectors:
                if sector in text:
                    score -= 3
                    reasons.append(f"忽略领域: {sector}")
                    break

            # Anti-keyword penalty
            anti_hits = sum(1 for kw in anti_keywords if kw in text and len(kw) > 2)
            if anti_hits >= 3:
                score -= 3
                reasons.append("匹配反例特征")

            item.relevance_score = min(10, max(0, score))
            item.relevance_reason = "; ".join(reasons) if reasons else "综合评估"

        return items
