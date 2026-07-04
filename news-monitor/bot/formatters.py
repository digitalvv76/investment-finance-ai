"""Message formatters for Telegram Bot output — all in Chinese."""

from typing import Dict


def format_fast_alert(item: dict) -> str:
    """Format a fast lane breaking news alert — Chinese display.

    Expected format:
    🔔 【NVDA】彭博社
    Nvidia cuts Q3 revenue guidance amid export restrictions
    🔗 https://bloomberg.com/...
    """
    tickers = item.get('tickers_found', '')
    source = item.get('source', '未知来源')
    title = item.get('title', '')
    url = item.get('url', '')
    macro_tags = item.get('macro_tags', '')
    impact = item.get('impact_assessment', None)

    # Translate source to Chinese if known
    source_cn = _translate_source(source)

    # Strategic alert badge — Chinese
    if 'STRATEGIC_' in macro_tags:
        if 'COMPETITIVE_THREAT' in macro_tags:
            prefix = "⚠️ 竞争威胁"
        elif 'ENDORSEMENT' in macro_tags:
            prefix = "🤝 大佬力挺"
        elif 'NVDA_INVESTMENT' in macro_tags:
            prefix = "💰 英伟达出手"
        elif 'GOV_INTERVENTION' in macro_tags:
            prefix = "🏛️ 政府干预"
        else:
            prefix = "🎯 战略警报"
    elif 'URGENT' in macro_tags:
        prefix = "🚨 紧急"
    else:
        prefix = "📰"

    # Build header
    ticker_badge = f"【{tickers}】" if tickers else ""
    header = f"{prefix} {ticker_badge}{source_cn}"

    # Impact line if available
    impact_line = ""
    if impact:
        impact_score = getattr(impact, 'impact_score', None) or impact.get('impact_score', 0)
        direction = getattr(impact, 'direction', '') or impact.get('direction', '')
        if impact_score:
            dir_label = {"up": "📈", "down": "📉", "flat": "➡️"}.get(direction, "")
            impact_line = f"\n💥 预估冲击: {impact_score}分 {dir_label}"

    msg = f"{header}\n{title}{impact_line}"

    if url:
        msg += f"\n🔗 {url}"

    return msg


def format_deep_analysis(item: dict) -> str:
    """Format deep lane analysis message — Chinese display.

    Expected format:
    📊 【NVDA】深度分析

    市场冲击: 高 | 方向: 🔴 看空
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
    impact_cn = _translate_impact(impact)
    sentiment = item.get('sentiment', 'neutral')
    sentiment_score = item.get('sentiment_score', 0)
    analysis = item.get('llm_analysis', '')

    # Sentiment
    sentiment_map = {
        'bullish': ('🟢', '看多'),
        'cautiously_bullish': ('🟡', '谨慎看多'),
        'neutral': ('⚪', '中性'),
        'cautiously_bearish': ('🟠', '谨慎看空'),
        'bearish': ('🔴', '看空'),
    }
    emoji, label = sentiment_map.get(sentiment, ('⚪', '中性'))

    # Sentiment score descriptor
    if sentiment_score <= -0.5:
        score_label = "强烈负面"
    elif sentiment_score <= -0.2:
        score_label = "偏负面"
    elif sentiment_score <= 0.2:
        score_label = "中性"
    elif sentiment_score <= 0.5:
        score_label = "偏正面"
    else:
        score_label = "强烈正面"

    lines = [
        f"📊 【{tickers}】深度分析",
        "",
        f"市场冲击: {impact_cn} | 方向: {emoji} {label}",
        f"情感分: {sentiment_score:.2f}（{score_label}）",
    ]

    # Portfolio link
    portfolio = item.get('portfolio_impact', '')
    if portfolio:
        lines.append(f"关联持仓: {portfolio}")

    if analysis:
        lines.append("")
        lines.append("🤖 AI 分析:")
        lines.append(analysis)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------

# English source → Chinese display name
_SOURCE_CN: Dict[str, str] = {
    "bloomberg": "彭博社",
    "bloomberg markets": "彭博市场",
    "reuters": "路透社",
    "reuters business": "路透商业",
    "cnbc": "CNBC",
    "cnbc top news": "CNBC头条",
    "cnbc live blog": "CNBC直播",
    "cnbc economy": "CNBC经济",
    "wsj": "华尔街日报",
    "wsj markets": "WSJ市场",
    "marketwatch": "MarketWatch",
    "yahoo finance": "雅虎财经",
    "seeking alpha": "Seeking Alpha",
    "seeking alpha market outlook": "SA市场展望",
    "investing.com": "Investing.com",
    "zerohedge": "ZeroHedge",
    "sec edgar 8-k": "SEC 8-K申报",
    "fred economic releases": "FRED经济数据",
    "@elerianm": "El-Erian推特",
    "@lisaabramowicz1": "Lisa Abramowicz",
    "@bespokeinvest": "Bespoke投资",
    "@newsquawk": "Newsquawk",
    "@zerohedge": "ZeroHedge推特",
    "@fxhedgers": "FxHedgers",
}


def _translate_source(source: str) -> str:
    """Translate English source name to Chinese. Falls back to original."""
    if not source:
        return "未知来源"
    key = source.lower()
    # Try exact match first
    if key in _SOURCE_CN:
        return _SOURCE_CN[key]
    # Try prefix match (e.g. "新浪财经·xxx" or "华尔街见闻·xxx")
    for k, v in _SOURCE_CN.items():
        if key.startswith(k):
            return v
    # Chinese sources keep their original name
    return source


def _translate_impact(impact: str) -> str:
    """Translate impact level to Chinese."""
    impact_map = {
        "high": "🔴 高",
        "medium": "🟡 中",
        "low": "🟢 低",
        "critical": "🚨 极高",
        "N/A": "未知",
    }
    return impact_map.get(str(impact).lower(), str(impact))


# Inline keyboard markup helpers (already Chinese)
def build_feedback_keyboard(news_id: int) -> dict:
    """Build inline keyboard with Chinese feedback buttons.

    Row 1: Content quality
    Row 2: Prediction accuracy
    Row 3: Deep analysis
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
