# 📰 News Assessment Training Dataset — US Government Strategic Intervention & Jensen Huang Market Impact Cases

> **Purpose**: Train the News Monitor system on financial news importance assessment, priority scoring, and impact evaluation
> **Source**: User-provided training document (训练资料.docx)
> **Time Span**: 2008 – July 2026
> **Coverage**: Government Equity Investment / Strategic Subsidies / Jensen Huang Market Influence
> **Total Events**: 21 cases (11 Government + 10 Jensen Huang)
> **Format**: Each entry includes date, event, impact level, market reaction, affected tickers, and category tags

---

# PART A: US Government Strategic Intervention Cases

## A-I. Direct Equity Investment / Shareholding Cases

### A1. Intel — Subsidy-to-Equity Conversion: $8.9 Billion for 9.9% Stake
- **Date**: 2025-08
- **Event**: The US Commerce Department converted $5.7 billion in grants and $3.2 billion in government awards (totaling approximately $8.9 billion) into a 9.9% equity stake in Intel, purchasing 433.3 million shares at $20.47 per share. This marked a historic shift in US industrial policy from "no-strings subsidies" to "state equity ownership."
- **Background**: In FY2024, Intel posted a net loss of $18.8 billion, with its foundry business losing $13.4 billion for the full year. The government had originally planned to issue grants to Intel under the CHIPS and Science Act.
- **Impact Level**: 🔴 CRITICAL
- **Market Reaction**:
  - Nasdaq fell sharply on announcement day; Nvidia, Intel, and Micron led chip-sector losses
  - Subsequently, Intel stock exploded upward, rising over 300% cumulatively over 8 months
  - April 2026: Intel posted the best single-month performance in Nasdaq's 55-year history, doubling in one month
  - By mid-June 2026, the US government's unrealized gain exceeded $43 billion
  - Trump later remarked he "regretted only taking 10%, should have asked for more"
- **Follow-on Effects**: Apple reached a preliminary agreement with Intel to produce chips for select Apple devices; Tesla CEO Elon Musk plans to use Intel's future chips in the Terafab project
- **Affected Tickers**: INTC, NVDA, MU, AAPL, TSLA, QQQ
- **Category Tags**: `government_equity`, `semiconductor`, `industrial_policy`, `chip_act`, `intel`
- **Priority Score Reference**: 0.95 (breaking + multi-sector + government intervention)
- **Analysis Takeaway**: Government endorsement reshaped market expectations of Intel's long-term value, attracting major customers like Apple and Tesla and creating a positive feedback loop.

### A2. Quantum Computing Industry — $2 Billion Equity Stake Across 9 Companies
- **Date**: 2026-05-21
- **Event**: The US Commerce Department announced $2 billion in total funding distributed to 9 quantum computing companies, using a "fiscal subsidy + strategic shareholding" model to acquire non-controlling minority stakes in all recipient companies. Funding sourced from CHIPS and Science Act early-stage technology project allocations. IBM alone received $1 billion to build America's first "dedicated quantum wafer foundry"; GlobalFoundries received $375 million; remaining companies each received approximately $100 million.
- **Background**: The Trump administration identified quantum computing as a strategic priority for economic and national security.
- **Impact Level**: 🟠 HIGH
- **Market Reaction**:
  - Quantum concept stocks surged pre-market
  - Closing: IBM +12%, D-Wave Quantum +33%, Rigetti Computing +30%, Infleqtion +31%
- **Affected Tickers**: IBM, GFS, QBTS, RGTI
- **Category Tags**: `government_equity`, `quantum_computing`, `strategic_industry`, `chip_act`
- **Priority Score Reference**: 0.78
- **Analysis Takeaway**: Government simultaneously invests across multiple technology pathways to "diversify risk" — the same model previously used with rare-earth magnet producer Vulcan Elements and mining company MP Materials.

### A3. MP Materials (Rare Earth) — Defense Department $400 Million, Becomes Largest Shareholder
- **Date**: 2025-07
- **Event**: The US Department of Defense agreed to acquire newly issued convertible preferred shares from MP Materials for $400 million, along with warrants. Upon full exercise, the DoD would hold approximately 15% of shares, becoming the largest shareholder of America's biggest rare earth producer.
- **Background**: The US seeks to build a domestic rare-earth full supply chain, reducing dependence on Chinese rare earths.
- **Impact Level**: 🟡 MEDIUM
- **Affected Tickers**: MP
- **Category Tags**: `government_equity`, `rare_earth`, `defense`, `supply_chain_security`
- **Priority Score Reference**: 0.55
- **Analysis Takeaway**: The Defense Department directly invests in critical mineral enterprises to secure supply chains for defense and new-energy industries.

### A4. L3Harris (Defense) — $1 Billion Convertible Preferred Stock
- **Date**: 2026-01
- **Event**: The Department of Defense announced a $1 billion convertible preferred stock investment in L3Harris's missile solutions business, which would be spun off as an independent company as part of the transaction. This marked the first time in decades that the DoD directly took equity in a defense supplier.
- **Background**: The DoD seeks to strengthen control over the defense supply chain through direct shareholding.
- **Impact Level**: 🟡 MEDIUM
- **Affected Tickers**: LHX
- **Category Tags**: `government_equity`, `defense`, `missile_systems`, `supply_chain`
- **Priority Score Reference**: 0.55
- **Analysis Takeaway**: 73% of Lockheed Martin's 2024 net sales came from the US government (65% from the DoD). The government is considering expanding the equity-stake model to more defense contractors.

### A5. General Motors (2008 Financial Crisis) — $49.5 Billion for 61% Stake
- **Date**: 2008-2009
- **Event**: As part of the Troubled Asset Relief Program (TARP), the US Treasury provided $49.5 billion in bailout loans to General Motors, receiving 912 million shares (~61% ownership). The government injected massive capital to prevent bankruptcy liquidation, comprehensively restructured the company via "loan-to-equity conversion," and ultimately exited through market mechanisms.
- **Background**: GM was on the brink of bankruptcy during the 2008 financial crisis.
- **Impact Level**: 🔴 CRITICAL (historical benchmark case)
- **Exit Outcome**: The US government recovered $39 billion through a series of share sales, for a loss of $10.5 billion.
- **Affected Tickers**: GM
- **Category Tags**: `government_bailout`, `financial_crisis`, `tarp`, `auto_industry`, `loan_to_equity`
- **Priority Score Reference**: 0.90 (historical significance)
- **Analysis Takeaway**: Crisis-bailout equity stakes often yield poor financial returns, but the strategic value lies in preventing systemic risk.

### A6. U.S. Steel — "Golden Share" Veto Power
- **Date**: 2025-2026 (Nippon Steel acquisition period)
- **Event**: In the Nippon Steel acquisition of U.S. Steel case, the US government embedded a special "golden share" clause granting veto power over core corporate decisions, strictly preventing the outflow of critical domestic industrial assets.
- **Impact Level**: 🟡 MEDIUM
- **Affected Tickers**: X
- **Category Tags**: `golden_share`, `national_security`, `steel_industry`, `foreign_acquisition`
- **Priority Score Reference**: 0.50
- **Analysis Takeaway**: Even without direct shareholding, special equity arrangements can preserve government control — another form of government intervention.

---

## A-II. Key Funding / Subsidy Cases (No Direct Shareholding)

### A7. CHIPS and Science Act — $52 Billion in Semiconductor Subsidies
- **Date**: Through end of 2024
- **Event**: Twelve companies including Intel, TSMC, Samsung, Micron, GlobalFoundries, and Texas Instruments received 61% of the $52 billion total, approximately $31.582 billion.
- **Key Allocations**:
  - **TSMC**: $6.6 billion grant + $5 billion loan for a third chip fab in Arizona
  - **Samsung**: $4.745 billion
  - **Texas Instruments**: $1.61 billion
  - **GlobalFoundries**: $1.5 billion for new facilities in New York and Vermont expansion
  - **Micron**: $610 million
  - **Microchip**: $162 million for mature-node chip and microcontroller expansion
- **Impact Level**: 🟠 HIGH
- **Catalyst Effect**: The CHIPS Act and related incentives have catalyzed over $450 billion in private-sector investment.
- **Affected Tickers**: TSM, INTC, MU, GFS, TXN, SAMSUNG
- **Category Tags**: `government_subsidy`, `semiconductor`, `chip_act`, `industrial_policy`
- **Priority Score Reference**: 0.72

### A8. Critical Minerals — Nearly $1 Billion Accelerated Development Fund
- **Date**: 2025-08
- **Event**: The US Department of Energy announced a nearly $1 billion fund to accelerate the development and production of critical minerals and materials spanning applications from EV batteries to semiconductors. Additionally, the US launched a $2.5 billion Critical Minerals Reserve Program aimed at stabilizing market prices and encouraging domestic mining and smelting.
- **Impact Level**: 🟡 MEDIUM
- **Category Tags**: `government_funding`, `critical_minerals`, `supply_chain`, `energy_transition`
- **Priority Score Reference**: 0.45

### A9. Nuclear Energy — Westinghouse $80 Billion Reactor Plan
- **Date**: 2025-2026
- **Event**: Washington plans to adopt Westinghouse nuclear reactor technology and invest at least $80 billion in building new nuclear reactors across the US. Once completed, these are expected to support the power demands of large-scale data centers and AI development.
- **Impact Level**: 🟠 HIGH
- **Category Tags**: `nuclear_energy`, `ai_infrastructure`, `data_center`, `energy_policy`
- **Priority Score Reference**: 0.62

### A10. Coal Power — $350 Million to Support Four Coal Plants
- **Date**: 2025-2026
- **Event**: The US Department of Energy finalized up to $350 million in funding to support four coal facility projects, including new power plants in Alaska and West Virginia, aimed at securing electricity supply for AI data centers.
- **Impact Level**: 🟡 MEDIUM
- **Category Tags**: `coal_power`, `energy_policy`, `ai_data_center`, `electricity_supply`
- **Priority Score Reference**: 0.40

### A11. Quantum Computing Industry Funding (Supplemental)
- **Date**: 2025-2026
- **Event**: In addition to the $2 billion equity investment detailed in Case A2, the US Commerce Department separately announced $2 billion in grants to 9 quantum computing companies.
- **Market Reaction**: Listed companies surged on the announcement: IBM and GlobalFoundries rose ~7%, Rigetti Computing +15%, D-Wave Quantum +17%, IONQ +8%.
- **Affected Tickers**: IBM, GFS, RGTI, QBTS, IONQ
- **Category Tags**: `government_funding`, `quantum_computing`, `strategic_industry`
- **Priority Score Reference**: 0.55

---

## A-III. Government Intervention Trend Summary (AI Learning Framework)

### Policy Paradigm Shift
Since January 2025, the federal government has invested nearly $21 billion in purchasing stock and equity across 17 enterprises — semiconductors account for 52.4%, critical minerals for 42.5%. Policy is transitioning from "handing out subsidies and reducing taxes" to "direct equity acquisition."

### Market Reaction Patterns
1. **Announcement-Day Effect**: On the day government equity/funding news breaks, affected individual stocks typically rise 5%-30%
2. **Endorsement Effect**: Government shareholding is perceived as the "Washington Seal of Approval," altering market expectations of a company's long-term value
3. **Chain-Reaction Effect**: Government endorsement can attract major customer partnerships (e.g., Intel securing Apple and Tesla orders), creating a positive feedback loop
4. **Uncertainty Risk**: Politicized capital intervention may trigger market concerns about policy uncertainty, causing sector volatility

### Risk Warning
The government equity model has also sparked controversy — some analysts argue that politicized capital injection may distort corporate governance or create subsidy dependency. Frontier sectors carry excessive risk, making them unsuitable for government equity investment.

---

# PART B: Jensen Huang Market Influence Cases

## B-I. Positive Impact Cases

### B1. Marvell Technology — One Sentence Creates $62.4 Billion in Market Cap
- **Date**: 2026-06-02
- **Event**: During the Taipei Computex exhibition, Jensen Huang shared the stage with Marvell CEO Matt Murphy and declared Marvell would become "the next trillion dollar company, ladies and gentlemen." He explained that Marvell's networking and interconnect chips are critical to data centers — when computing tasks are distributed across thousands of interconnected chips, data transmission speed determines everything, and Marvell is the core supplier in this segment.
- **Background**: Computex Taipei, Jensen Huang keynote attendance.
- **Impact Level**: 🔴 CRITICAL
- **Market Reaction**:
  - Marvell stock surged 32.52% the next trading day — the largest single-day gain in company history
  - Market cap jumped from ~$192 billion to ~$254 billion — a single trading day added $62.4 billion in market cap
  - The entire optical communications supply chain soared: Coherent +17%, Lumentum +14%, Corning +13%
- **Affected Tickers**: MRVL, COHR, LITE, GLW
- **Category Tags**: `jensen_huang`, `endorsement`, `ai_infrastructure`, `networking`, `marvell`
- **Priority Score Reference**: 0.95 (single-sentence trillion-dollar endorsement)
- **Analysis Takeaway**: No earnings guidance, no order announcement — with one sentence, Jensen Huang triggered a complete market repricing. The market was not buying his opinion; it was buying his decision-making power. His identity simultaneously encompasses **analyst, customer, and industry architect** — every sentence is simultaneously a judgment, an order forecast, and a top-level ecosystem roadmap.

### B2. Nokia — $1 Billion Investment Lifts Stock 20%
- **Date**: 2025-10
- **Event**: At GTC Washington, Jensen Huang announced Nvidia's $1 billion investment in Nokia, subscribing to 166.4 million new Nokia shares at €6.01 per share. The two parties are collaborating to advance 6G network infrastructure. Huang called telecommunications "the lifeblood of the economy and national security," noting that US communications technology has long relied on foreign technology and "it's time to get back in the game."
- **Background**: GTC Washington event.
- **Impact Level**: 🟠 HIGH
- **Market Reaction**:
  - Nokia stock shot up nearly 20% on the news
  - Nvidia's own stock rose nearly 5%, pushing its market cap close to $5 trillion
- **Affected Tickers**: NOK, NVDA
- **Category Tags**: `jensen_huang`, `strategic_investment`, `6g`, `telecom`, `nvidia`
- **Priority Score Reference**: 0.82
- **Analysis Takeaway**: Government equity stakes (US government has invested nearly $21 billion across 17 companies) and Jensen Huang's personal endorsement combine to form a dual-signal overlay — the market is extremely sensitive to such "strategic-level cooperation."

### B3. SK Hynix — Production-Increase Call Reverses Decline
- **Date**: 2026-06
- **Event**: During Jensen Huang's visit to South Korea, SK Hynix shares were under sustained pressure from external headwinds, closing down 7.69% on June 8. Huang publicly called on SK Hynix to "please produce more" memory chips. The two sides announced a multi-year technology partnership to jointly develop next-generation AI memory around Nvidia's Vera Rubin AI supercomputer, Vera CPU, RTX Spark-powered PCs, and Jetson Thor robotics platform.
- **Background**: Huang's South Korea visit; SK Hynix is Nvidia's sole HBM supplier.
- **Impact Level**: 🟠 HIGH
- **Market Reaction**: SK Hynix's losses rapidly narrowed. The term **"Jensen Effect"** began circulating in the market.
- **Affected Tickers**: SK HYNIX, NVDA
- **Category Tags**: `jensen_huang`, `hbm`, `memory_chips`, `supply_chain`, `sk_hynix`
- **Priority Score Reference**: 0.75
- **Analysis Takeaway**: As Nvidia's sole HBM (high-bandwidth memory) supplier, SK Hynix's performance is deeply tied to Nvidia's roadmap. Huang's "produce more" call essentially conveys **demand certainty** — the market heard not encouragement, but a commitment to future orders.

### B4. Qualcomm — Directly Tells Market "Buy Their Stock"
- **Date**: 2026-06
- **Event**: During Jensen Huang's Asia tour, when asked about Nvidia's interest in the smartphone market, Huang candidly admitted Nvidia "has not done well in mobile devices, and there's no need" to enter that space. He then pivoted to lavish praise on Qualcomm — "they've done a great job" — and **directly told the audience to "buy their stock."** He added with self-deprecating humor: "I spend all day helping other people sell their stock."
- **Background**: Huang's Asia tour interviews.
- **Impact Level**: 🟠 HIGH
- **Market Reaction**: Qualcomm shares rose ~2% in after-hours trading immediately following the remarks, gained another 3%+ pre-market, and at one point surged over 8% in after-hours.
- **Affected Tickers**: QCOM
- **Category Tags**: `jensen_huang`, `stock_recommendation`, `qualcomm`, `mobile_chips`, `competition`
- **Priority Score Reference**: 0.78
- **Analysis Takeaway**: This is Jensen Huang's **most explicit "stock recommendation"** — a clear suggestion to buy a specific stock. The subtext: Nvidia has no intention of entering the mobile chip market to compete with Qualcomm; Qualcomm's moat is secure.

### B5. Adobe — One Sentence Revives Software-Stock Confidence
- **Date**: 2026-04
- **Event**: At the Adobe Investor Session, Jensen Huang stated: "For 99.9% of the world's creators, this intelligent system will elevate your artistic creation."
- **Background**: Adobe Investor Session; software stocks broadly under market pressure.
- **Impact Level**: 🟡 MEDIUM
- **Market Reaction**: In an environment where the market viewed software stocks as being in a "software abyss," Huang's endorsement — combined with Adobe's buyback program — significantly bolstered investor confidence in Adobe.
- **Affected Tickers**: ADBE
- **Category Tags**: `jensen_huang`, `software`, `creative_tools`, `endorsement`
- **Priority Score Reference**: 0.58
- **Analysis Takeaway**: Jensen Huang's influence extends beyond the semiconductor supply chain into the **application software layer** — his endorsement signals deep synergy between Nvidia's AI compute platform and Adobe's creative tools.

### B6. China A-Share Robotics Concept Stocks — Cross-Border Remarks Trigger Limit-Up Wave
- **Date**: 2026-06
- **Event**: Jensen Huang stated that "robotics technology will be the next major field for South Korea," and that Nvidia would collaborate with Korean manufacturing enterprises in robotics and AI.
- **Background**: Huang's South Korea visit; A-share market open.
- **Impact Level**: 🟠 HIGH
- **Market Reaction**:
  - A-share robotics concept stocks surged in the afternoon session
  - **Nearly 50 stocks hit limit-up or surged close to 10%**
  - Over 10 related concept stocks — including Fengguang Precision, Dongtu Technology, Leaderdrive, Zhongda Leader, Sunlord Electronics, Guangyang Shares, and Fuda Shares — hit limit-up in a straight line
  - The exoskeleton robot index closed over 3.70% higher
- **Affected Tickers**: A-share robotics sector (multiple tickers)
- **Category Tags**: `jensen_huang`, `robotics`, `a_shares`, `cross_border_impact`, `concept_stocks`
- **Priority Score Reference**: 0.72
- **Analysis Takeaway**: Jensen Huang's remarks **cross national borders to impact China's A-share market** — Chinese investors mapped "South Korea robotics" onto the "global robotics supply chain" and bid up A-share names. This **indirect transmission** demonstrates the global reach of his influence.

---

## B-II. Negative Impact Cases

### B7. Intel, AMD, Qualcomm — Entry into PC Chips Triggers Collective Plunge
- **Date**: 2026-06-01
- **Event**: Nvidia unveiled its first personal computer processor, the N1X (co-developed with Microsoft), officially entering the PC chip market long dominated by Intel and AMD. Jensen Huang declared that "Microsoft and Nvidia will reinvent the personal computer," and that "over the past 40 years, this is the first personal computer product line to be completely redesigned and reinvented."
- **Background**: Nvidia product launch event.
- **Impact Level**: 🔴 CRITICAL
- **Market Reaction**:
  - Pre-market: **Intel plunged ~6%, AMD fell over 3%, Qualcomm at one point crashed nearly 10%**
  - Close: Intel tumbled 4.67% (4th consecutive decline), Qualcomm crashed 8.78% to the bottom of the Philadelphia Semiconductor Index
  - Nvidia's own stock closed up 6.25%
- **Affected Tickers**: INTC, AMD, QCOM, NVDA, MSFT
- **Category Tags**: `jensen_huang`, `pc_chip`, `market_entry`, `competition`, `zero_sum`
- **Priority Score Reference**: 0.90
- **Analysis Takeaway**: A single product launch by Jensen Huang **simultaneously struck three competitors** — a textbook "zero-sum game" effect. The market interpreted it as a reshaping of the PC chip industry landscape, with capital flowing from legacy players to the new entrant.

### B8. Johnson Controls, Modine Manufacturing — One Technical-Roadmap Sentence Erases Order Expectations
- **Date**: 2026-01
- **Event**: At CES, Jensen Huang announced that the next-generation Rubin chip **requires no water chillers** to operate.
- **Background**: CES trade show keynote.
- **Impact Level**: 🔴 CRITICAL
- **Market Reaction**: That day, **Johnson Controls crashed 11%, Modine Manufacturing plunged 21%**.
- **Affected Tickers**: JCI, MOD
- **Category Tags**: `jensen_huang`, `technical_roadmap`, `cooling_systems`, `supply_chain_disruption`, `data_center`
- **Priority Score Reference**: 0.88
- **Analysis Takeaway**: This is the most classic **"one technical-roadmap sentence rewrites the supply chain"** case. Cooling-system suppliers' order expectations were forcibly erased from the system architecture by a single sentence from Jensen Huang. The market was not buying his opinion — it was buying his **decision-making authority**. As the architect-definer of AI data centers, his "not needed" means the entire supply-chain segment's valuation must be repriced.

### B9. Nvidia Itself — "No-Win Situation" and $500 Billion Evaporated
- **Date**: 2025-11
- **Event**: Nvidia reported Q3 FY2026 earnings — **revenue $57.006 billion (+62% YoY), net profit $31.91 billion (+65% YoY)** — both beating expectations.
- **Background**: Nvidia quarterly earnings release.
- **Impact Level**: 🔴 CRITICAL
- **Market Reaction**: Nvidia initially rose nearly 5% on earnings day, but ultimately **closed down 3.15%**.
- **Jensen Huang's Internal Remarks** (leaked): At an all-hands meeting, Huang admitted Nvidia is trapped in a **"no-win situation"** — *"If we deliver a bad quarter, even by a tiny bit, the whole world will collapse... If we deliver a lousy quarter, it's proof of the AI bubble; if we deliver a stellar quarter, we're fueling the AI bubble."* He lamented the company's market cap "evaporated by $500 billion in a few days," noting "there's never been a case in history where $500 billion could be lost in just a few days."
- **Affected Tickers**: NVDA, SMH, QQQ
- **Category Tags**: `jensen_huang`, `earnings`, `ai_bubble`, `expectations_mismatch`, `nvidia`
- **Priority Score Reference**: 0.92
- **Analysis Takeaway**: Huang's remarks reveal the **"expectations management" dilemma** — when market expectations for a company are "absurdly high," even results that beat estimates can still send the stock lower. Though his internal complaint did not directly move the market when made, the leak further amplified AI-bubble concerns.

### B10. South Korea Stock Market — "Jensen Huang Concept Stocks" Collective Pullback and Circuit Breaker
- **Date**: 2026-06-04 to 06-05
- **Event**: Ahead of Jensen Huang's visit to South Korea, the market had front-run "Jensen Huang concept stocks."
- **Background**: Huang's scheduled South Korea visit; pre-visit speculation.
- **Impact Level**: 🟠 HIGH
- **Market Reaction**:
  - June 4: Previously hot LG Electronics **crashed 16.43%**, SK Telecom fell 13.26%, Naver fell 4.99%; multiple Korean robotics company stocks dropped 6%-12%. KOSPI closed down 1.84%.
  - June 5 morning: KOSPI 200 futures fell 5%, triggering the **Korean Exchange's program trading halt mechanism (circuit breaker)**. Samsung Electronics fell over 6%, SK Hynix fell over 8%.
- **Affected Tickers**: SAMSUNG ELECTRONICS, SK HYNIX, LG ELECTRONICS, SK TELECOM, NAVER, KOSPI
- **Category Tags**: `jensen_huang`, `sell_the_fact`, `circuit_breaker`, `korean_market`, `concept_stocks`
- **Priority Score Reference**: 0.80
- **Analysis Takeaway**: This is a classic **"sell-the-fact after buy-the-rumor"** case — the market had pre-priced the benefits of Huang's visit, and when he actually arrived, a "sell the news" reaction materialized. Jensen Huang's influence is not only about *what* he says, but also *when* he says it — the market front-runs his itinerary and remarks.

---

## B-III. Jensen Huang Influence Trend Summary (AI Learning Framework)

### Three Sources of Jensen Huang's Influence

1. **Information-Hub Position**: Jensen Huang stands at the absolute geometric center of the global AI compute funnel — cloud providers collaborate with him, model companies use his GPUs, server manufacturers design around his architecture, HBM suppliers expand capacity per his roadmap. **No second person can simultaneously see so much core information across the AI infrastructure stack.**

2. **Triple-Role Overlay**: His words are simultaneously **an analyst's judgment, a customer's order forecast, and a top-level ecosystem industry roadmap**. The market defaults to assuming "he knows things others don't yet know, and sees trends others haven't yet seen."

3. **Architecture-Definition Authority**: Nvidia doesn't just sell chips — it defines the entire AI computing architecture. When Huang says "water chillers are unnecessary," the cooling supply chain crashes — because **he has the authority to decide how data centers are built**.

### Market Reaction Patterns

| Statement Type | Typical Reaction | Duration | Risk Warning |
| :--- | :--- | :--- | :--- |
| **Naming a company positively** | Single-day surge 20%-32% | Short-term violent, medium-term divergent | Valuation may detach from fundamentals |
| **Announcing investment / partnership** | Target company +10%-20% | Moderate, accompanied by fundamental revaluation | Distinguish strategic from financial investment |
| **Entering a new market** | Competitors crash 3%-10% | Medium-to-long-term landscape reshaping | Industry shakeout, winner-takes-all |
| **Technical roadmap change** | Related suppliers crash 10%-20% | Long-term, order expectations permanently altered | Supply-chain restructuring risk |
| **"Market-saving" rhetoric** | Sector-wide rebound 3%-6% | Short-term, sentiment-driven | May create bubbles rather than provide effective guidance |

### Risk Warning
Bloomberg columns and other media outlets have sounded the alarm: against a backdrop of euphoric retail sentiment and rising leverage, Jensen Huang's optimistic statements and stock endorsements **"are creating potential risks rather than providing effective guidance."** The risk of market froth cannot be ignored — investors are indiscriminately imagining everything from automakers to PC manufacturers as "AI concept stocks," while semiconductor and hard-tech companies themselves carry significant cyclicality.

---

# Appendix A: Impact Level Classification Standards

| Level | Code | Definition | Typical Score Range | Expected Market Impact |
|-------|------|-----------|---------------------|----------------------|
| 🔴 Critical | CRITICAL | Affects overall market direction, monetary policy, geopolitical landscape | 0.85-1.0 | Broad index moves 1%+; cross-sector contagion |
| 🟠 High | HIGH | Affects specific sectors or major companies; cross-sector spillover possible | 0.60-0.84 | Sector indices move 1-3% |
| 🟡 Medium | MEDIUM | Affects individual stocks or sub-industries; moderate market attention | 0.35-0.59 | Individual stocks/sub-sectors move 1-5% |
| 🟢 Low | LOW | Routine industry events; limited impact scope | 0.10-0.34 | Minor individual stock moves <1% |

# Appendix B: News Category Tag System

```
# Primary Categories
government_equity   - Government equity investment / shareholding
government_subsidy   - Government subsidy / funding programs
government_bailout   - Government bailout / crisis intervention
jensen_huang         - Jensen Huang remarks / endorsements
semiconductor        - Semiconductor industry
quantum_computing    - Quantum computing industry
defense              - Defense / military industry
rare_earth           - Rare earth / critical minerals
energy_policy        - Energy policy (nuclear, coal, etc.)
telecom              - Telecommunications
ai_infrastructure    - AI infrastructure (data centers, networking)
robotics             - Robotics industry

# Secondary Tags (nature / sentiment)
endorsement          - Public endorsement of company/sector
strategic_investment - Strategic investment announcement
market_entry         - New market entry / competition
technical_roadmap    - Technical architecture / roadmap change
stock_recommendation - Direct stock recommendation
competition          - Competitive dynamics
supply_chain         - Supply chain impact
cross_border_impact  - Cross-border market impact
sell_the_fact        - Sell-the-fact / buy-the-rumor dynamics
ai_bubble            - AI bubble concern
```

# Appendix C: Training Usage Recommendations

1. **Priority Score Training**: Feed event descriptions into the system; compare against human-labeled impact levels to train PriorityScorer weights
2. **Entity Extraction Training**: Extract names of people (Jensen Huang, CEOs), organizations (companies, government agencies), products (N1X, Rubin, HBM), and financial indicators
3. **Sentiment Analysis Training**: Label each event's market_sentiment (positive/negative/neutral/mixed) and the direction of the affected tickers
4. **Event Clustering Training**: Group same-theme events — e.g., all Jensen Huang Computex remarks into one event_line; all CHIPS Act subsidy cases into another
5. **Strategic Detection Training**: Label government intervention types — direct equity, strategic subsidy, golden share, bailout, etc.
6. **Multi-Source Resonance Training**: Label which events should trigger escalation from fast_lane to deep_lane (e.g., when multiple news sources independently confirm a Jensen Huang remark)

---

> **Source**: User-provided training document (训练资料.docx)
> **Processed**: 2026-07-02
> **Applicable Scope**: News Monitor System Training / PriorityScorer Calibration / StrategicDetector Keyword Expansion / Government Intervention Pattern Recognition
