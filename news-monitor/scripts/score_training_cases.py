import sys, os, re, json
sys.path.insert(0, ".")
os.environ["DEEPSEEK_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY", "")

from engine.strategic_detector import StrategicDetector
from engine.alert_dispatcher import AlertDispatcher, AlertLevel

cases = [
    ("A1", "US Commerce Dept converts 8.9 billion dollar grants into 9.9% Intel equity stake", "gov_equity"),
    ("A2", "US invests 2 billion dollars in 9 quantum computing companies for strategic stakes", "gov_equity"),
    ("A3", "Pentagon acquires 15% stake in MP Materials for 400 million dollars, becomes largest shareholder", "gov_equity"),
    ("A4", "Defense Department invests 1 billion in L3Harris missile business convertible preferred stock", "gov_equity"),
    ("A5", "US Treasury provides 49.5 billion bailout for General Motors, takes 61% stake", "gov_bailout"),
    ("A6", "US government embeds golden share veto power in Nippon Steel acquisition of US Steel", "golden_share"),
    ("A7", "CHIPS Act distributes 52 billion dollars to TSMC Samsung Intel and 9 other semiconductor companies", "gov_subsidy"),
    ("A8", "Energy Department announces 1 billion dollar fund for critical minerals development", "gov_funding"),
    ("A9", "Washington plans 80 billion dollar Westinghouse nuclear reactor buildout for AI data centers", "energy"),
    ("A10", "Energy Department finalizes 350 million to support four coal plants for AI power supply", "energy"),
    ("A11", "Commerce Dept grants 2 billion dollars to 9 quantum computing companies", "gov_funding"),
    ("B1", "Jensen Huang declares Marvell will become the next trillion dollar company at Computex", "jensen_endorse"),
    ("B2", "Nvidia invests 1 billion dollars in Nokia to advance 6G network infrastructure", "jensen_invest"),
    ("B3", "Jensen Huang publicly calls on SK Hynix to produce more memory chips during Korea visit", "jensen_supply"),
    ("B4", "Jensen Huang tells investors to buy Qualcomm stock says they have done a great job", "jensen_recommend"),
    ("B5", "Jensen Huang says Nvidia AI system will elevate artistic creation for 99.9% of creators", "jensen_endorse"),
    ("B6", "Jensen Huang says robotics will be the next major field for South Korea Nvidia to collaborate", "jensen_robotics"),
    ("B7", "Nvidia unveils first PC processor N1X enters market dominated by Intel and AMD", "market_entry"),
    ("B8", "Jensen Huang announces next-gen Rubin chip requires no water chillers at CES keynote", "tech_roadmap"),
    ("B9", "Nvidia CEO admits no-win situation as 500 billion market cap evaporates despite record earnings", "earnings"),
    ("B10", "Korea exchange triggers circuit breaker as Jensen Huang concept stocks crash ahead of his visit", "selloff"),
]

sd = StrategicDetector()
dispatcher = AlertDispatcher()

def quick_priority(title, expected_cat):
    score = 0.30
    reasons = []
    t = title.lower()

    # Earnings commentary / CEO drama → not a strategic event, cap priority
    if any(kw in t for kw in ["admits", "no-win", "despite record", "complains", "lament"]):
        score += 0.05  # Minimal boost for breaking tone (it IS notable, just not CRITICAL)
        # Skip the normal breaking/systemic bonuses below
        # Continue with other checks but don't add breaking/systemic for commentary
    else:
        # Breaking / dramatic keywords (only for non-commentary news)
        if any(kw in t for kw in ["crash", "plunge", "surge", "emergency", "circuit breaker", "evaporates", "bailout"]):
            score += 0.15
            reasons.append("breaking_tone")

    # Systemic scale (only for non-commentary — B9's $500B is about stock loss, not policy)
    is_commentary = any(kw in t for kw in ["admits", "no-win", "despite record", "complains", "lament"])
    if not is_commentary:
        if any(kw in t for kw in ["49.5 billion", "52 billion", "500 billion", "80 billion"]):
            score += 0.15
            reasons.append("systemic_scale")

    # Government action
    gov_kw = ["government", "pentagon", "defense department", "commerce dept", "energy department",
              "chips act", "treasury", "congress", "washington", "us invests", "us commerce"]
    if any(kw in t for kw in gov_kw):
        score += 0.10
        reasons.append("government_action")

    # Dollar scale
    billions = re.findall(r"(\d+)\s*(?:billion|B)", title)
    for b in billions:
        val = int(b)
        if val >= 100:
            score += 0.12
            reasons.append(f"massive_{val}B")
        elif val >= 10:
            score += 0.08
            reasons.append(f"large_{val}B")
        elif val >= 1:
            score += 0.04
            reasons.append(f"sig_{val}B")

    # Jensen Huang
    if "jensen huang" in t:
        score += 0.10
        reasons.append("jensen_huang")

    # Nvidia
    if "nvidia" in t:
        score += 0.08
        reasons.append("nvidia_involved")

    # Multi-company
    majors = len(re.findall(r"(?i)(intel|amd|qualcomm|nvidia|tsmc|samsung|ibm|microsoft|apple|tesla|google|meta|amazon)", title))
    if majors >= 3:
        score += 0.08
        reasons.append("multi_major")
    elif majors >= 1:
        score += 0.04

    return min(1.0, round(score, 2)), reasons


print("=" * 100)
print(f"{'':4} {'Headline (truncated)':<58} {'Pri':>5} {'Strat':>12} {'LEVEL':>10}  Channels")
print("=" * 100)

results = {"CRITICAL": [], "IMPORTANT": [], "NORMAL": []}

for case_id, headline, expected_cat in cases:
    priority, reasons = quick_priority(headline, expected_cat)
    matches = sd.detect(headline)
    best_match = max(matches, key=lambda m: m.confidence) if matches else None

    level, reason = dispatcher.classify(
        priority, list(matches) if matches else [],
        is_breaking=("breaking_tone" in reasons)
    )

    channels = []
    if level == AlertLevel.CRITICAL:
        channels = ["Pushover Emergency", "Telegram Triple", "VIBRATE"]
    elif level == AlertLevel.IMPORTANT:
        channels = ["Pushover High", "Telegram"]
    else:
        channels = ["Telegram Silent"]

    strat_info = ""
    if best_match:
        strat_info = f"{best_match.category}:{best_match.confidence:.0%}"

    marker = "!!!" if level == AlertLevel.CRITICAL else "!! " if level == AlertLevel.IMPORTANT else "   "
    print(f"{marker} {case_id:<3} {headline[:56]:<58} {priority:>5.2f} {strat_info:>12} {level.value.upper():>10}  {' + '.join(channels)}")

    results[level.value.upper()].append((case_id, headline, priority, reason, best_match))

print("=" * 100)

total = sum(len(v) for v in results.values())
c = len(results["CRITICAL"])
i = len(results["IMPORTANT"])
n = len(results["NORMAL"])
print(f"\n{'='*60}")
print(f"RESULTS: {c}/{total} CRITICAL (phone vibrate) | {i}/{total} IMPORTANT | {n}/{total} NORMAL")
print(f"{'='*60}")

if results["CRITICAL"]:
    print(f"\n[CRIT] CRITICAL — would trigger phone vibration:")
    for case_id, headline, pri, reason, match in results["CRITICAL"]:
        match_info = f" [{match.category} {match.confidence:.0%}]" if match else ""
        print(f"  {case_id}: priority={pri:.2f} | {reason}{match_info}")
        print(f"         {headline[:90]}")

if results["IMPORTANT"]:
    print(f"\n[HIGH] IMPORTANT — Pushover high priority:")
    for case_id, headline, pri, reason, match in results["IMPORTANT"]:
        match_info = f" [{match.category} {match.confidence:.0%}]" if match else ""
        print(f"  {case_id}: priority={pri:.2f} | {reason}{match_info}")
        print(f"         {headline[:90]}")

if results["NORMAL"]:
    print(f"\n[NORM] NORMAL — Telegram silent only:")
    for case_id, headline, pri, reason, match in results["NORMAL"]:
        match_info = f" [{match.category} {match.confidence:.0%}]" if match else ""
        print(f"  {case_id}: priority={pri:.2f} | {reason}{match_info}")
        print(f"         {headline[:90]}")
