"""Message formatters for Telegram Bot output — all in Chinese."""

import os
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# ETF / Ticker mapping tables
# ---------------------------------------------------------------------------

# Ticker → Chinese name
_TICKER_CN: Dict[str, str] = {
    # US equities
    "NVDA": "英伟达", "AMD": "超威半导体", "INTC": "英特尔",
    "AVGO": "博通", "TSM": "台积电", "AAPL": "苹果",
    "MSFT": "微软", "GOOGL": "谷歌", "META": "Meta",
    "AMZN": "亚马逊", "TSLA": "特斯拉", "JPM": "摩根大通",
    "GS": "高盛", "BAC": "美国银行", "WFC": "富国银行",
    "C": "花旗", "XOM": "埃克森美孚", "CVX": "雪佛龙",
    "JNJ": "强生", "PFE": "辉瑞", "LLY": "礼来",
    "SPY": "标普500", "QQQ": "纳指100",
    # Crypto-exposed equities (publicly traded stocks)
    "COIN": "Coinbase", "MSTR": "MicroStrategy",
    "RIOT": "Riot区块链", "MARA": "Marathon挖矿",
    "CLSK": "CleanSpark", "HUT": "Hut 8挖矿", "WULF": "TeraWulf挖矿",
    # Fintech
    "SQ": "Block", "AFRM": "Affirm", "SOFI": "SoFi", "HOOD": "Robinhood",
}

# Ticker → related sector ETFs
_TICKER_TO_ETF: Dict[str, List[str]] = {
    # US equities
    "NVDA": ["SMH", "SOXX", "QQQ"], "AMD": ["SMH", "SOXX"],
    "INTC": ["SMH", "SOXX"], "AVGO": ["SMH", "SOXX", "QQQ"],
    "TSM": ["SMH", "SOXX"], "AAPL": ["QQQ", "XLK"],
    "MSFT": ["QQQ", "XLK"], "GOOGL": ["QQQ", "XLK"],
    "META": ["QQQ", "XLK"], "AMZN": ["QQQ", "XLK"],
    "TSLA": ["QQQ"], "JPM": ["XLF"], "GS": ["XLF"],
    "BAC": ["XLF"], "WFC": ["XLF"], "C": ["XLF"],
    "XOM": ["XLE"], "CVX": ["XLE"],
    "JNJ": ["XLV"], "PFE": ["XLV"], "LLY": ["XLV"],
    # Crypto-exposed equities → fintech/blockchain ecosystem
    "COIN": ["QQQ", "XLK", "IBIT", "MSTR"],
    "MSTR": ["QQQ", "IBIT", "COIN"],
    "RIOT": ["MARA", "COIN"],
    "MARA": ["RIOT", "COIN"],
    "CLSK": ["COIN"], "HUT": ["COIN"], "WULF": ["COIN"],
    # Fintech
    "SQ": ["QQQ", "XLK"], "AFRM": ["QQQ"], "SOFI": ["XLF"], "HOOD": ["QQQ", "XLF"],
}

# ETF → Chinese name
_ETF_CN: Dict[str, str] = {
    "SMH": "半导体", "SOXX": "半导体", "QQQ": "纳指100",
    "SPY": "标普500", "XLK": "科技板块", "XLF": "金融板块",
    "XLE": "能源板块", "XLV": "医疗保健", "XLI": "工业板块",
    "TLT": "长期国债", "GLD": "黄金", "USO": "原油",
    "IWM": "罗素2000",
    # Crypto-exposed equities
    "IBIT": "比特币ETF", "COIN": "Coinbase", "MSTR": "MicroStrategy",
}

# Event category → related ETFs (for macro/news-driven events)
_EVENT_TO_ETF: Dict[str, List[str]] = {
    "monetary": ["TLT", "SPY", "GLD"],
    "geopolitical": ["GLD", "USO", "XLE"],
    "macro_data": ["TLT", "SPY", "XLF"],
    "CHIPS": ["SMH", "SOXX"],
    "TARIFF": ["XLI", "XLE", "SPY"],
    "AI": ["SMH", "QQQ", "XLK"],
    "ENERGY": ["XLE", "USO"],
    "REGULATORY": ["XLF", "SPY", "QQQ"],
}


def _build_ticker_etf_line(tickers: str, macro_tags: str = "",
                           event_category: str = "") -> str:
    """Build a Chinese display string showing tickers, their Chinese names,
    and related sector ETFs.  Returns empty string when nothing to show."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return ""

    # Build ticker display with Chinese names
    ticker_parts = []
    etf_set: set = set()

    for tk in ticker_list:
        cn = _TICKER_CN.get(tk, "")
        ticker_parts.append(f"{tk}({cn})" if cn else tk)
        # Collect related ETFs
        for etf in _TICKER_TO_ETF.get(tk, []):
            etf_set.add(etf)

    # Also add event-driven ETFs from macro_tags or event_category
    macro_upper = macro_tags.upper() if macro_tags else ""
    cat_lower = (event_category or "").lower()
    for key, etfs in _EVENT_TO_ETF.items():
        key_lower = key.lower()
        if key in macro_upper or key_lower in cat_lower:
            for etf in etfs:
                etf_set.add(etf)

    # Always include SPY as baseline for broad-market events
    if cat_lower in ("monetary", "geopolitical", "macro_data"):
        etf_set.add("SPY")

    parts = [f"🎯 相关标的: {' '.join(ticker_parts)}"]
    if etf_set:
        etf_display = " ".join(
            f"{e}({_ETF_CN.get(e, e)})" for e in sorted(etf_set)
        )
        parts.append(f"  板块ETF: {etf_display}")

    return "\n".join(parts)


def format_fast_alert(item: dict, analyst_note: str = "",
                       event_category: str = "",
                       impact_score: int = 0, confidence: int = 0) -> str:
    """Format a fast lane breaking news alert — Chinese display.

    Expected format:
    🔔 【NVDA】彭博社
    Nvidia cuts Q3 revenue guidance amid export restrictions

    💥 冲击: 78分 | 置信度: 82%

    [analyst note in Chinese]

    🎯 相关标的: NVDA(英伟达)  板块ETF: SMH(半导体) QQQ(纳指100)
    🔗 https://bloomberg.com/...
    """
    tickers = item.get('tickers_found', '')
    source = item.get('source', '未知来源')
    title = item.get('title', '')
    url = item.get('url', '')
    macro_tags = item.get('macro_tags', '')

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

    # Build message body
    msg = f"{header}\n{title}"

    # Impact score + confidence
    if impact_score > 0:
        msg += f"\n\n💥 冲击: {impact_score}分"
        if confidence > 0:
            msg += f" | 置信度: {confidence}%"

    # Analyst note (from ImpactEvaluator LLM)
    note = analyst_note or item.get('analyst_note', '')
    if note:
        msg += f"\n\n{note}"

    # Related tickers + sector ETFs
    etf_line = _build_ticker_etf_line(tickers, macro_tags, event_category)
    if etf_line:
        msg += f"\n\n{etf_line}"

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


def format_pushover_alert(item: dict, title_cn: str = "",
                          analyst_note: str = "",
                          event_category: str = "",
                          impact_score: int = 0, confidence: int = 0) -> tuple[str, str]:
    """Format a Pushover notification in Chinese — returns (title, body).

    Pushover limits: title ≤ 250 chars, body ≤ 1024 chars.

    Args:
        item: News item with title, source, tickers_found, macro_tags, url.
        title_cn: Chinese translation of the title.
        analyst_note: Analyst-style narrative from ImpactEvaluator LLM.
        event_category: Event category for ETF mapping.
        impact_score: 0-100 LLM impact prediction.
        confidence: 0-100 LLM confidence.
    """
    title = item.get("title", "")[:120]
    source = item.get("source", "未知来源")
    tickers = item.get("tickers_found", "")
    macro = item.get("macro_tags", "")
    url = item.get("url", "")
    news_id = item.get("id", 0)

    source_cn = _translate_source(source)

    # Title: source + Chinese title (tickers already shown in body ETF line)
    display_title = title_cn if title_cn else title
    push_title = f"📰 {source_cn}：{display_title}"[:250]

    # Body: analyst note → ETFs → links → impact score at bottom
    parts = []

    # Analyst note
    note = analyst_note or item.get('analyst_note', '')
    if note:
        parts.append(note)

    # Related ETFs
    etf_line = _build_ticker_etf_line(tickers, macro, event_category)
    if etf_line:
        if parts:
            parts.append("")
        parts.append(etf_line)

    # Action links
    links = []
    if news_id:
        dash_url = os.environ.get("WEB_DASHBOARD_URL", "http://localhost:8080")
        links.append(f'<a href="{dash_url}/api/news/{news_id}/analyze">🔍 深度分析</a>')
    if url:
        links.append(f'<a href="{url}">📎 阅读原文</a>')
    if links:
        if parts:
            parts.append("")
        parts.append(" · ".join(links))

    # Impact score + confidence — at the bottom
    if impact_score > 0:
        impact_line = f"💥 冲击: {impact_score}分"
        if confidence > 0:
            impact_line += f" | 置信度: {confidence}%"
        if parts:
            parts.append("")
        parts.append(impact_line)

    body = "\n".join(parts)[:1024]
    if not body.strip():
        body = display_title[:1024]
    return push_title[:250], body


def _translate_macro_tags(macro_tags: str) -> str:
    """Translate macro tag strings to Chinese."""
    _MACRO_CN = {
        "STRATEGIC_GOV_INTERVENTION": "政府干预",
        "STRATEGIC_NVDA_INVESTMENT": "英伟达投资",
        "STRATEGIC_NVDA_ENDORSEMENT": "英伟达代言",
        "STRATEGIC_NVDA_COMPETITIVE_THREAT": "竞争威胁",
        "URGENT": "紧急",
        "BREAKING": "突发",
        "MACRO": "宏观",
        "FOMC": "美联储",
        "CPI": "通胀数据",
        "GDP": "GDP",
        "EARNINGS": "财报",
        "M_AND_A": "并购",
        "FDA": "FDA审批",
        "CEO": "CEO变动",
        "GEO_POLITICAL": "地缘政治",
        "TARIFF": "关税",
        "CHIPS": "芯片法案",
        "AI": "人工智能",
    }
    tags = [t.strip() for t in macro_tags.split(",") if t.strip()]
    translated = [_MACRO_CN.get(t, t) for t in tags]
    return "，".join(translated)


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
