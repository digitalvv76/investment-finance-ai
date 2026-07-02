"""Daily digest generator — aggregates 24h news into formatted summary."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict

from storage.database import Database

logger = logging.getLogger(__name__)

DIGEST_TEMPLATE = """📰 *每日市场简报*
{date}

━━━━━━━━━━━━━━━━━━━━
📊 *概览*
━━━━━━━━━━━━━━━━━━━━
总文章数: {total_articles}
快速推送: {fast_count}
深度分析: {deep_count}
活跃事件: {event_count}

{movers_section}
{top_stories_section}
{events_section}
━━━━━━━━━━━━━━━━━━━━
🤖 金融智能监控系统
"""


class DigestGenerator:
    """Generate daily news digest from database.

    Queries the last 24 hours of news and formats a structured
    summary suitable for Telegram delivery.
    """

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, hours: int = 24) -> str:
        """Generate a formatted daily digest.

        Args:
            hours: Lookback window in hours. Default 24.

        Returns:
            Formatted markdown string ready for Telegram.
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d %A")

        # Gather data
        recent = self.db.get_recent_news(hours=hours)
        fast_items = [r for r in recent if r.get('status') == 'fast_pushed']
        deep_items = [r for r in recent if r.get('status') == 'deep_pushed']
        urgent_items = [r for r in recent if r.get('priority_score', 0) >= 0.7]

        # Build sections
        movers_section = self._build_movers_section(recent)
        top_section = self._build_top_stories(recent, limit=5)
        events_section = self._build_events_section()

        # If no content, return minimal digest
        if not recent:
            return f"📰 *每日简报*\n{date_str}\n\n过去 {hours} 小时没有采集到新闻。"

        return DIGEST_TEMPLATE.format(
            date=date_str,
            total_articles=len(recent),
            fast_count=len(fast_items),
            deep_count=len(deep_items),
            event_count=len(events_section.split('\n')) - 2 if events_section else 0,
            movers_section=movers_section,
            top_stories_section=top_section,
            events_section=events_section,
        )

    def generate_minimal(self) -> str:
        """Generate a compact digest for quick status checks."""
        recent = self.db.get_recent_news(hours=24)
        fast_count = len([r for r in recent if r.get('status') == 'fast_pushed'])
        deep_count = len([r for r in recent if r.get('status') == 'deep_pushed'])

        lines = [
            f"📊 24小时: {len(recent)} 条新闻",
            f"⚡ 快推: {fast_count} | 🧠 深度: {deep_count}",
        ]

        # Top 3 highest priority
        top = sorted(
            [r for r in recent if r.get('priority_score', 0) > 0],
            key=lambda x: x.get('priority_score', 0),
            reverse=True,
        )[:3]

        if top:
            lines.append("")
            lines.append("🔝 头条新闻:")
            for item in top:
                tickers = item.get('tickers_found', '')
                ticker_str = f" [{tickers}]" if tickers else ""
                score = item.get('priority_score', 0)
                lines.append(f"  [{score:.2f}]{ticker_str} {item['title'][:60]}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_movers_section(self, items: List[dict]) -> str:
        """Build a 'market movers' section showing ticker mentions."""
        if not items:
            return ""

        # Count ticker mentions
        ticker_count: Dict[str, int] = {}
        for item in items:
            tickers = item.get('tickers_found', '')
            if tickers:
                for t in tickers.split(','):
                    t = t.strip()
                    if t:
                        ticker_count[t] = ticker_count.get(t, 0) + 1

        if not ticker_count:
            return ""

        # Top 5 most mentioned tickers
        top_tickers = sorted(ticker_count.items(), key=lambda x: x[1], reverse=True)[:5]
        lines = [
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "🏷️ *最热门标的*",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        for ticker, count in top_tickers:
            lines.append(f"  ${ticker}: {count} 次提及")

        return "\n".join(lines)

    def _build_top_stories(self, items: List[dict], limit: int = 5) -> str:
        """Build top stories section sorted by priority."""
        if not items:
            return ""

        scored = [r for r in items if r.get('priority_score', 0) > 0]
        top = sorted(scored, key=lambda x: x.get('priority_score', 0), reverse=True)[:limit]

        if not top:
            return ""

        lines = [
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "📈 *头条新闻*",
            "━━━━━━━━━━━━━━━━━━━━",
        ]

        for i, item in enumerate(top, 1):
            title = item.get('title', 'No title')[:80]
            source = item.get('source', 'Unknown')
            score = item.get('priority_score', 0)
            sentiment = item.get('sentiment', '')
            sent_emoji = self._sentiment_emoji(sentiment)
            lines.append(f"  {i}. {sent_emoji} [{score:.2f}] {title}")
            lines.append(f"     *{source}*")

        return "\n".join(lines)

    def _build_events_section(self) -> str:
        """Build active event lines section."""
        try:
            with self.db._get_conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM event_lines
                       WHERE is_active = 1 AND source_count >= 2
                       AND last_updated > datetime('now', '-24 hours')
                       ORDER BY source_count DESC
                       LIMIT 5"""
                ).fetchall()
        except Exception:
            return ""

        if not rows:
            return ""

        lines = [
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "🔥 *活跃事件* (多源确认)",
            "━━━━━━━━━━━━━━━━━━━━",
        ]

        for row in rows:
            title = row['title'][:60] if row['title'] else 'Untitled'
            count = row['source_count']
            lines.append(f"  • {title} ({count} 个来源)")

        return "\n".join(lines)

    @staticmethod
    def _sentiment_emoji(sentiment: str) -> str:
        emoji_map = {
            'bullish': '🟢',
            'cautiously_bullish': '🟡',
            'neutral': '⚪',
            'cautiously_bearish': '🟠',
            'bearish': '🔴',
        }
        return emoji_map.get(sentiment, '⚪')
