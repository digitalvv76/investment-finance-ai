"""Tests for message formatters."""
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
    assert 'NVDA' in result
    assert 'Bloomberg' in result
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
    assert 'Reuters' in result
    assert 'CPI data released' in result


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
    assert 'high' in result
    assert 'bearish' in result
    assert '-0.72' in result
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
