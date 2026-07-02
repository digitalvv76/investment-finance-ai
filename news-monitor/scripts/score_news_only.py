import sys, os, re
sys.path.insert(0, ".")
os.environ["DEEPSEEK_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY", "")

from engine.strategic_detector import StrategicDetector
from engine.alert_dispatcher import AlertDispatcher, AlertLevel
from engine.priority import PriorityScorer, _DEVIATION_PATTERNS, _SURPRISE_KEYWORDS, _ASSET_CLASSES
from storage.models import NewsItem

sd = StrategicDetector()
dispatcher = AlertDispatcher()
ps = PriorityScorer()

# Helper: extract features from headline text (mimics FastLane entity extraction)
def score_headline(headline):
    """Score a headline string, extracting features from text."""
    t = headline.lower()
    item = NewsItem()
    item.title = headline

    # Breaking detection
    item.is_breaking = any(kw in t for kw in
        ["surge", "surges", "unexpectedly", "plunge", "plunges",
         "shock", "shocks", "crash", "crashes", "panic", "meltdown"])

    # Extract tickers
    TICKER_MAP = {
        "nvidia": "NVDA", "apple": "AAPL", "tesla": "TSLA",
        "alphabet": "GOOGL", "google": "GOOGL", "microsoft": "MSFT",
        "meta": "META", "amazon": "AMZN", "intel": "INTC", "amd": "AMD",
        "qualcomm": "QCOM", "broadcom": "AVGO",
    }
    tickers = set()
    for name, ticker in TICKER_MAP.items():
        if name in t:
            tickers.add(ticker)

    # Extract macro tags
    MACRO_PATTERNS = {
        "cpi": ["cpi", "inflation", "consumer price"],
        "employment": ["payroll", "nonfarm", "unemployment", "jobs", "labor"],
        "fed": ["fed ", "fomc", "federal reserve", "rate cut", "rate hike", "rates at", "holds rates", "stress test"],
        "trade": ["tariff", "trade war", "trade framework", "antitrust", "sanction"],
        "energy": ["opec", "crude", "brent", "oil", "gasoline"],
        "earnings": ["revenue", "earnings", "beat", "guidance", "buyback", "deliveries"],
        "regulation": ["sec", "approves", "etf", "regulator", "restriction"],
        "geopolitics": ["us and china", "eu ", "framework agreement", "geneva"],
        "retail": ["retail sales", "consumer spending"],
    }
    macro_tags = set()
    for tag, keywords in MACRO_PATTERNS.items():
        if any(kw in t for kw in keywords):
            macro_tags.add(tag)

    # Key people detection
    PEOPLE_KEYWORDS = ["powell", "trump", "jensen huang", "musk", "cook", "yellen", "warsh"]
    has_people = any(kw in t for kw in PEOPLE_KEYWORDS)

    # Use the full PriorityScorer pipeline
    priority = ps.score(item, tickers, macro_tags, has_people)
    return priority, tickers, macro_tags, item.is_breaking


# Benchmark scores from external system
BENCHMARK = {
    "N1": 0.76, "N2": 0.68, "N3": 0.84, "N4": 0.78,
    "N5": 0.66, "N6": 0.82, "N7": 0.90, "N8": 0.88,
    "N9": 0.72, "N10": 0.74, "N11": 0.86, "N12": 0.80,
    "N13": 0.60, "N14": 0.70, "N15": 0.62, "N16": 0.64,
}

cases = [
    ("N1", "2026-01-10", "December nonfarm payrolls surge 285K vs 200K expected, unemployment 3.6%, wages +0.4%"),
    ("N2", "2026-01-29", "Fed holds rates at 4.25-4.50%, says inflation risks remain tilted to upside"),
    ("N3", "2026-02-13", "January CPI rises 2.9% vs 2.7% expected, core CPI 3.2% vs 3.1% expected"),
    ("N4", "2026-02-21", "Nvidia Q4 revenue 42.5 billion beats estimates, Blackwell Ultra enters mass production, guidance above expectations"),
    ("N5", "2026-03-12", "EU announces digital services tax on US big tech, antitrust probes into Apple and Alphabet"),
    ("N6", "2026-03-19", "Fed cuts rates 25bp to 4.00-4.25%, dot plot signals 50bp more cuts in 2026, Powell flags economic downside risks"),
    ("N7", "2026-04-02", "US announces 25% tariff on imported autos and parts, expands tariffs on Chinese clean energy products"),
    ("N8", "2026-04-15", "March retail sales unexpectedly drop 0.8% vs expected 0.2% gain, first monthly decline in half a year"),
    ("N9", "2026-04-22", "Tesla Q1 deliveries 475K beat 450K expected, Full Self-Driving gets China public road testing approval"),
    ("N10", "2026-05-01", "Apple Q2 Services revenue hits record high, Greater China returns to growth, 110 billion buyback approved"),
    ("N11", "2026-05-15", "April CPI plunges to 2.5% from 2.9%, core CPI drops to 2.8% from 3.2%, biggest inflation surprise this year"),
    ("N12", "2026-05-28", "US and China reach preliminary AI safety and trade framework agreement in Geneva, pause some tech investment restrictions"),
    ("N13", "2026-06-04", "OPEC+ unexpectedly announces gradual output increase from July, Brent crude plunges 10% to 62 dollars"),
    ("N14", "2026-06-12", "May nonfarm payrolls 175K vs 190K expected, unemployment rises to 4.0%, wage growth slows to 3.9%"),
    ("N15", "2026-06-18", "SEC approves spot Ethereum ETF options trading, allows ETF structures to include staking yield"),
    ("N16", "2026-06-26", "Fed annual stress test: all 31 major banks pass capital requirements, Fed removes SLR restrictions"),
]

print("=" * 120)
print("{:4} {:12} {:50} {:>6} {:>6} {:>6} {:>14} {:>10}".format(
    "", "Date", "Headline", "My", "Bench", "Diff", "Strat", "ALERT"))
print("=" * 120)

results = {"CRITICAL": [], "IMPORTANT": [], "NORMAL": []}

for case_id, date, headline in cases:
    priority, tickers, macro_tags, is_breaking = score_headline(headline)

    matches = sd.detect(headline)
    best_match = max(matches, key=lambda m: m.confidence) if matches else None

    level, reason = dispatcher.classify(
        priority, list(matches) if matches else [],
        is_breaking=is_breaking
    )

    channels = "VIBRATE" if level == AlertLevel.CRITICAL else "PUSHOVER" if level == AlertLevel.IMPORTANT else "SILENT"

    strat_info = ""
    if best_match:
        strat_info = "{cat}:{conf:.0%}".format(cat=best_match.category[:8], conf=best_match.confidence)

    bench = BENCHMARK.get(case_id, 0)
    diff = priority - bench

    marker = "!!!" if level == AlertLevel.CRITICAL else "!! " if level == AlertLevel.IMPORTANT else "   "
    print("{m} {cid:<4} {d:<12} {h:<50} {p:>6.2f} {b:>6.2f} {df:>+5.2f} {s:>14} {lvl:>10}  {ch}".format(
        m=marker, cid=case_id, d=date, h=headline[:48], p=priority, b=bench,
        df=diff, s=strat_info, lvl=level.value.upper(), ch=channels))

    results[level.value.upper()].append((case_id, date, headline, priority, bench, reason, best_match))

print("=" * 120)

total = sum(len(v) for v in results.values())
c = len(results["CRITICAL"])
i = len(results["IMPORTANT"])
n = len(results["NORMAL"])

gaps = [abs(p - BENCHMARK.get(cid, 0)) for cid, _, _, p, _, _, _ in
        results["CRITICAL"] + results["IMPORTANT"] + results["NORMAL"]]
avg_gap = sum(gaps) / len(gaps) if gaps else 0

print("\nRESULTS: {c}/{t} CRITICAL | {i}/{t} IMPORTANT | {n}/{t} NORMAL".format(c=c, i=i, n=n, t=total))
print("Avg gap vs benchmark: {:.2f}".format(avg_gap))

for level_name, level_label, level_results in [
    ("CRITICAL", "!!! CRITICAL -- VIBRATE:", results["CRITICAL"]),
    ("IMPORTANT", "!!  IMPORTANT -- Pushover:", results["IMPORTANT"]),
    ("NORMAL", "    NORMAL -- silent:", results["NORMAL"]),
]:
    if level_results:
        print("\n" + level_label)
        for case_id, date, headline, pri, bench, reason, match in level_results:
            match_info = ""
            if match:
                match_info = " [{cat} {conf:.0%}]".format(cat=match.category, conf=match.confidence)
            print("  {cid} [{d}] my={p:.2f} bench={b:.2f} gap={g:+.2f} | {r}{mi}".format(
                cid=case_id, d=date, p=pri, b=bench, g=pri-bench, r=reason, mi=match_info))
            print("         " + headline[:100])
