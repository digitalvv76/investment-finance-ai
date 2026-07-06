"""Push test following push-format-spec.md — run on ECS."""
import asyncio, sys, os, requests, json
from types import SimpleNamespace
sys.path.insert(0, '/app')

from storage.database import Database
from engine.impact_evaluator import ImpactEvaluator
from bot.translator import get_translator
from bot.formatters import _translate_source, _build_ticker_etf_line


def make_news_item(row: dict):
    """Convert dict from DB to NewsItem-like object for ImpactEvaluator."""
    item = SimpleNamespace()
    item.id = row.get('id', 0)
    item.title = row.get('title', '')
    item.url = row.get('url', '')
    item.source = row.get('source', '')
    item.content_snippet = row.get('content_snippet', row.get('title', ''))
    item.tickers_found = row.get('tickers_found', '')
    item.macro_tags = row.get('macro_tags', '')
    item.is_breaking = bool(row.get('is_breaking', False))
    item.priority_score = row.get('priority_score', 0.0)
    item.sentiment = row.get('sentiment')
    item.sentiment_score = row.get('sentiment_score', 0.0)
    return item


async def run():
    db = Database('data/news.db')
    ev = ImpactEvaluator()
    translator = get_translator()

    for news_id in [1, 16]:
        row = db.get_news_by_id(news_id)
        if not row:
            print(f'#{news_id}: not found')
            continue

        item = make_news_item(row)
        title_en = item.title[:200]
        source = item.source
        tickers = item.tickers_found
        macro = item.macro_tags
        url = item.url

        print(f'\n=== #{news_id}: {title_en[:80]} ===')

        # STEP 1: DeepSeek translate title
        title_cn = await translator.translate(title_en)
        if not title_cn:
            title_cn = title_en
        print(f'CN: {title_cn[:80]}')

        # STEP 2: ImpactEvaluator for analyst note
        analyst_note = ''
        impact_score = 55
        confidence = 70
        try:
            assessment = await ev.evaluate(item)
            if assessment:
                impact_score = getattr(assessment, 'impact_score', impact_score)
                confidence = getattr(assessment, 'confidence', confidence)
                analyst_note = getattr(assessment, 'analyst_note', '')
                print(f'Impact: {impact_score}, Conf: {confidence}')
        except Exception as e:
            print(f'Evaluator err: {e}')

        # STEP 3: Build push per push-format-spec.md
        source_cn = _translate_source(source)
        push_title = f"📰 {source_cn}：{title_cn}"[:250]

        # Body: analyst_note → ETF → links → impact
        body_parts = []
        if analyst_note:
            body_parts.append(analyst_note)
        else:
            body_parts.append(f"{source_cn}报道：{title_cn}")

        etf_line = _build_ticker_etf_line(tickers, macro)
        if etf_line:
            body_parts.append('')
            body_parts.append(etf_line)

        body_parts.append('')
        body_parts.append(f'🔍 深度分析 · <a href="{url}">📎 阅读原文</a>')
        body_parts.append(f'💥 冲击: {impact_score}分 | 置信度: {confidence}%')

        push_body = '\n'.join(body_parts)[:1024]

        print(f'\nTitle: {push_title}')
        print(f'Body:\n{push_body[:400]}')

        # STEP 4: Send Telegram
        tg_etf = etf_line.replace('\n', '\n') if etf_line else ''
        tg_msg = f"🔴 {push_title}\n\n{analyst_note or title_cn}\n\n{tg_etf}\n\n💥 冲击: {impact_score}分 | 置信度: {confidence}%\n🔗 {url}"
        # Clean up empty lines
        import re
        tg_msg = re.sub(r'\n{3,}', '\n\n', tg_msg)

        r = requests.post(
            'https://api.telegram.org/bot8221754289:AAF6B9OlaYj97gifqLN6b0xkkAz8f9eqRGI/sendMessage',
            json={'chat_id': 7305690438, 'text': tg_msg}
        )
        print(f'Telegram: {"OK" if r.json().get("ok") else r.json()}')

        # STEP 5: Send Pushover
        prio = 2 if impact_score >= 55 else 1
        po_data = {
            'token': 'ao33n7scppsfi3vp9ieezjwq3my6mm',
            'user': 'ub6itkddwfovz2kni5xzdqo34gthm7',
            'title': push_title,
            'message': push_body,
            'priority': prio,
            'html': 1,
        }
        if prio == 2:
            po_data['expire'] = 3600
            po_data['retry'] = 60
        r2 = requests.post('https://api.pushover.net/1/messages.json', data=po_data)
        print(f'Pushover: {"OK" if r2.json().get("status")==1 else r2.json()}')

asyncio.run(run())
