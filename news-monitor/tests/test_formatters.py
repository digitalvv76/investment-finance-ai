"""Tests for message formatters — Chinese display."""
from bot.formatters import format_fast_alert, format_deep_analysis, build_feedback_keyboard


def test_format_fast_alert_with_ticker():
    item = {
        'id': 1,
        'tickers_found': 'NVDA',
        'source': 'Bloomberg',
        'title': 'Nvidia beats estimates',
        'url': 'https://bloomberg.com/nvda',
    }
    result = format_fast_alert(item)
    # Chinese format: 📰 【NVDA】彭博社\nNvidia beats estimates\n🔗 url
    assert 'NVDA' in result
    assert '彭博社' in result       # Bloomberg → 彭博社
    assert 'Nvidia beats estimates' in result
    assert 'https://bloomberg.com/nvda' in result


def test_format_fast_alert_no_ticker():
    item = {
        'id': 2,
        'tickers_found': '',
        'source': 'Reuters',
        'title': 'CPI data released',
        'url': '',
    }
    result = format_fast_alert(item)
    assert '路透社' in result       # Reuters → 路透社
    assert 'CPI data released' in result


def test_format_fast_alert_strategic():
    """Strategic events get special Chinese badges."""
    item = {
        'id': 3,
        'tickers_found': 'MRVL',
        'source': 'CNBC',
        'title': 'Jensen Huang calls Marvell the next big thing',
        'url': '',
        'macro_tags': 'STRATEGIC_NVDA_ENDORSEMENT',
    }
    result = format_fast_alert(item)
    assert 'MRVL' in result
    assert '大佬力挺' in result     # nvda_endorsement badge
    assert 'CNBC' in result


def test_format_fast_alert_gov_intervention():
    """Government intervention gets Chinese badge."""
    item = {
        'id': 4,
        'tickers_found': 'IONQ',
        'source': 'Reuters',
        'title': 'US gov invests in quantum',
        'url': '',
        'macro_tags': 'STRATEGIC_GOV_INTERVENTION',
    }
    result = format_fast_alert(item)
    assert '政府干预' in result


def test_format_deep_analysis():
    item = {
        'tickers_found': 'AAPL',
        'market_impact': 'high',
        'sentiment': 'bearish',
        'sentiment_score': -0.72,
        'llm_analysis': 'This is a test analysis.',
    }
    result = format_deep_analysis(item)
    assert 'AAPL' in result
    assert '高' in result             # high → 高 (Chinese)
    assert '看空' in result           # bearish → 看空
    assert '-0.72' in result
    assert '强烈负面' in result       # sentiment score label
    assert 'test analysis' in result


def test_build_feedback_keyboard():
    keyboard = build_feedback_keyboard(42)
    rows = keyboard['inline_keyboard']
    # 3 rows: content quality, prediction accuracy, deep analysis
    assert len(rows) == 3
    # Row 1: content quality
    assert rows[0][0]['text'] == '📰 内容优质'
    assert rows[0][0]['callback_data'] == 'content_good:42'
    # Row 2: prediction accuracy (2 buttons)
    assert len(rows[1]) == 2
    assert rows[1][0]['text'] == '📉 判断准确'
    assert rows[1][1]['text'] == '📈 判断错误'
    # Row 3: deep analysis
    assert rows[2][0]['text'] == '📊 深度分析'
    assert rows[2][0]['callback_data'] == 'analyze:42'
