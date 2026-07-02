"""Message formatters for Telegram Bot output."""
from typing import Dict


def format_fast_alert(item: dict) -> str:
    """Format a fast lane breaking news alert.

    Expected format:
    🔔 NVDA · Bloomberg
    Nvidia cuts Q3 revenue guidance amid export restrictions
    🔗 https://bloomberg.com/...
    """
    tickers = item.get('tickers_found', '')
    source = item.get('source', 'Unknown')
    title = item.get('title', '')
    url = item.get('url', '')
    macro_tags = item.get('macro_tags', '')

    # Strategic alert badge
    if 'STRATEGIC_' in macro_tags:
        if 'COMPETITIVE_THREAT' in macro_tags:
            prefix = "⚠️ 竞争威胁 · "
        elif 'ENDORSEMENT' in macro_tags:
            prefix = "🤝 战略背书 · "
        elif 'NVDA_INVESTMENT' in macro_tags:
            prefix = "💰 英伟达投资 · "
        elif 'GOV_INTERVENTION' in macro_tags:
            prefix = "🏛️ 政府干预 · "
        else:
            prefix = "🎯 战略警报 · "
    else:
        prefix = "🔔 "

    # Build ticker badge
    ticker_str = f"{prefix}{tickers} · " if tickers else prefix

    msg = f"{ticker_str}{source}\n{title}"

    if url:
        msg += f"\n🔗 {url}"

    return msg


def format_deep_analysis(item: dict) -> str:
    """Format deep lane analysis message.

    Expected format:
    📊 分析 · NVDA

    市场冲击: 高 | 方向: 🔴 Bearish
    关联持仓: NVDA (权重 8%)
    情感分: -0.72 (强烈负面)

    影响分析:
    • Point 1
    • Point 2

    AI 短评:
    [LLM analysis]
    """
    tickers = item.get('tickers_found', '')
    impact = item.get('market_impact', 'N/A')
    sentiment = item.get('sentiment', 'neutral')
    sentiment_score = item.get('sentiment_score', 0)
    analysis = item.get('llm_analysis', '')

    # Sentiment emoji
    emoji_map = {
        'bullish': '🟢',
        'cautiously_bullish': '🟡',
        'neutral': '⚪',
        'cautiously_bearish': '🟠',
        'bearish': '🔴',
    }
    emoji = emoji_map.get(sentiment, '⚪')

    lines = [
        f"📊 分析 · {tickers}",
        "",
        f"市场冲击: {impact} | 方向: {emoji} {sentiment}",
        f"情感分: {sentiment_score:.2f}",
    ]

    if analysis:
        lines.append("")
        lines.append("AI 短评:")
        lines.append(analysis)

    return "\n".join(lines)


# Inline keyboard markup helpers
def build_feedback_keyboard(news_id: int) -> dict:
    """Build inline keyboard with semantically separated feedback buttons.

    Row 1: Content quality (📰 内容优质)
    Row 2: Prediction accuracy (📉 判断准确 / 📈 判断错误)
    Row 3: Deep analysis (📊 分析)
    """
    return {
        'inline_keyboard': [
            [
                {'text': '📰 内容优质', 'callback_data': f'content_good:{news_id}'},
            ],
            [
                {'text': '📉 判断准确', 'callback_data': f'prediction_right:{news_id}'},
                {'text': '📈 判断错误', 'callback_data': f'prediction_wrong:{news_id}'},
            ],
            [
                {'text': '📊 深度分析', 'callback_data': f'analyze:{news_id}'},
            ]
        ]
    }
