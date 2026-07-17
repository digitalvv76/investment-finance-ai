#!/usr/bin/env python
"""System acceptance test - verifies all modules end-to-end."""
import asyncio, sys, os, logging, subprocess, time, tempfile
logging.disable(logging.CRITICAL)

def banner(title):
    print()
    print('-' * 56)
    print('  ' + title)
    print('-' * 56)

results = {}
start = time.time()
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root)
sys.path.insert(0, root)

# ---- 1. Unit Tests ----
banner('1/8 Unit Tests')
r = subprocess.run(
    [sys.executable, '-m', 'pytest', 'tests/', '-q', '--tb=line'],
    capture_output=True, text=True, timeout=120
)
passed = ' passed' in r.stdout and ' failed' not in r.stdout
results['Unit Tests'] = 'PASS' if passed else 'FAIL'
# Extract pass count from output
import re as _re
m = _re.search(r'(\d+) passed', r.stdout)
count = m.group(1) if m else '?'
print('  ' + ('PASS ({}/{})'.format(count, count) if passed else 'FAIL: ' + r.stdout[-200:]))

# ---- 2. Config ----
banner('2/8 Configuration')
from config.loader import ConfigLoader
cfg = ConfigLoader('config')
s = cfg.load_settings()
src = cfg.load_sources()
kw = cfg.load_keywords()
assert len(src['tier_1_rss']) == 5
assert len(kw['macro_alerts']) >= 20
results['Config'] = 'PASS'
print('  RSS: {} | PW: {} | Keywords: {} macro + {} breaking'.format(
    len(src['tier_1_rss']), len(src['tier_2_playwright']),
    len(kw['macro_alerts']), len(kw['breaking_markers'])))
print('  PASS')

# ---- 3. Database ----
banner('3/8 Database')
from storage.database import Database
from storage.models import NewsItem, FeedbackRecord
tmp = tempfile.mktemp(suffix='.db')
db = Database(tmp)
db.init_db()
item = NewsItem(title='Test', url='https://t.com/1', source='T')
db.insert_news(item)
assert item.id > 0
db.update_news_status(item.id, 'fast_pushed', priority_score=0.5)
row = db.get_news_by_id(item.id)
assert row['status'] == 'fast_pushed'
db.insert_feedback(FeedbackRecord(news_id=item.id, reaction='thumbs_up'))
db.set_preference('k', 'v')
assert db.get_preference('k') == 'v'
os.unlink(tmp)
results['Database'] = 'PASS'
print('  CRUD + feedback + preferences: OK')
print('  PASS')

# ---- 4. Fast Lane ----
banner('4/8 Fast Lane')
from unittest.mock import MagicMock
from engine.fast_lane import FastLane
mock_db = MagicMock()
mock_db.get_recent_news.return_value = []
mock_cfg = MagicMock()
mock_cfg.load_keywords.return_value = kw
fl = FastLane(mock_cfg, mock_db)
items = [
    NewsItem(title='BREAKING: NVDA beats earnings by 40%', url='x/1', source='Bloomberg'),
    NewsItem(title='CPI inflation cools to 2.1%, Fed may cut rates', url='x/2', source='Reuters'),
    NewsItem(title='Local weather: sunny', url='x/3', source='Local'),
]
pushed = fl.process(items)
assert len(pushed) == 2
assert pushed[0].is_breaking
assert 'NVDA' in pushed[0].tickers_found
results['Fast Lane'] = 'PASS'
for p in pushed:
    print('  [{:.2f}] {}'.format(p.priority_score, p.title[:55]))

# ---- 5. Deep Lane ----
banner('5/8 Deep Lane (NER + Sentiment + Priority)')
from engine.entity_extractor import EntityExtractor
from engine.sentiment import SentimentAnalyzer
from engine.priority import PriorityScorer
ex = EntityExtractor(mock_cfg)
ent = ex.extract('NVDA record earnings, Jensen Huang says AI demand unprecedented')
assert 'NVDA' in ent['tickers']
assert 'Jensen Huang' in ent['people']
sa = SentimentAnalyzer()
sent, score = sa.analyze('NVDA surges to record high on blowout earnings')
assert 'bullish' in sent.value
ps = PriorityScorer()
pscore = ps.score(
    NewsItem(title='T', url='x', source='Bloomberg', is_breaking=True),
    tickers={'NVDA', 'AAPL'}, macro_tags={'CPI', 'FOMC'},
    has_people=True, similar_count=2
)
assert pscore >= 0.7
assert ps.classify(pscore) == 'urgent'
results['Deep Lane'] = 'PASS'
print('  NER: tickers={} people={}'.format(ent['tickers'], ent['people']))
print('  Sentiment: {} ({:+.2f})'.format(sent.value, score))
print('  Priority: {:.2f} = {}'.format(pscore, ps.classify(pscore)))
print('  PASS')

# ---- 6. Dedup + Digest + Learner ----
banner('6/8 Dedup + Digest + Learner')
from collector.dedup import DedupManager
from bot.digest import DigestGenerator
from engine.learner import Learner
d = DedupManager()
assert not d.is_duplicate(NewsItem(title='X', url='https://x.com/a', source='T'))
assert d.is_duplicate(NewsItem(title='X', url='https://x.com/a', source='T'))
dg = DigestGenerator(mock_db)
mock_db.get_recent_news.return_value = [
    {'id': 1, 'title': 'BREAKING: NVDA', 'source': 'BBG', 'status': 'fast_pushed',
     'priority_score': 0.8, 'tickers_found': 'NVDA', 'sentiment': 'bullish', 'macro_tags': ''}
]
assert 'NVDA' in dg.generate_minimal()
tmp2 = tempfile.mktemp(suffix='.db')
db2 = Database(tmp2)
db2.init_db()
learner = Learner(db2)
learner.update_personal_dict('semi', 'add')
assert 'semi' in learner.get_personal_dict()
os.unlink(tmp2)
results['Supporting'] = 'PASS'
print('  All 3 modules: OK')
print('  PASS')

# ---- 7. Data Sources ----
banner('7/8 Live Data Sources')
from collector.rss_fetcher import RSSFetcher
rss = RSSFetcher(src['tier_1_rss'])
rss_items = asyncio.run(rss.fetch_all())
working = len(set(i.source for i in rss_items))
assert working >= 4
results['Data Sources'] = 'PASS ({}/{})'.format(working, len(rss.sources))
for src_item in rss.sources:
    cnt = sum(1 for i in rss_items if i.source == src_item['name'])
    print('  {} {}: {} items'.format('OK' if cnt else '--', src_item['name'], cnt))
print('  Total: {} items'.format(len(rss_items)))

# ---- 8. Production ----
banner('8/8 Production Readiness')
checks = [
    ('Dockerfile', 'docker/Dockerfile'),
    ('docker-compose', 'docker/docker-compose.yml'),
    ('Windows service', 'scripts/install_service.py'),
    ('VPS guide', 'docs/VPS-MIGRATION.md'),
    ('README', 'README.md'),
    ('Acceptance test', 'scripts/acceptance_test.py'),
]
all_ok = True
for name, path in checks:
    ok = os.path.exists(path)
    if not ok:
        all_ok = False
    print('  {} {}'.format('OK' if ok else 'MISSING', name))
results['Production'] = 'PASS' if all_ok else 'FAIL'

# ---- Final Report ----
elapsed = time.time() - start
print()
print('=' * 56)
print('  ACCEPTANCE TEST RESULTS')
print('=' * 56)
all_pass = True
for name, status in results.items():
    flag = 'PASS' if 'PASS' in status else 'FAIL'
    if flag != 'PASS':
        all_pass = False
    print('  [{}] {}'.format(flag, name))
print('=' * 56)
verdict = 'ALL SYSTEMS GO' if all_pass else 'ISSUES FOUND'
print('  {} ({:.0f}s)'.format(verdict, elapsed))
print('=' * 56)

needs = []
if not os.environ.get('TELEGRAM_BOT_TOKEN'):
    needs.append('TELEGRAM_BOT_TOKEN')
if not os.environ.get('ANTHROPIC_API_KEY'):
    needs.append('ANTHROPIC_API_KEY')
if needs:
    print()
    print('  To go live, set: {}'.format(', '.join(needs)))
