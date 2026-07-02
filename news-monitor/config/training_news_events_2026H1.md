# 📰 新闻评估训练数据集 — 2026年上半年影响美股重大事件

> **用途**: 训练 News Monitor 系统对财经新闻的重要性评估、优先级评分和影响力判断
> **时间跨度**: 2026年1月 – 2026年7月
> **覆盖维度**: 货币政策 / 地缘政治 / 宏观经济 / 科技AI / 并购 / IPO / 财报 / 贸易政策 / 银行金融 / 能源商品 / 加密货币 / 医疗生物
> **事件总数**: 60+
> **格式**: 每条含日期、事件、影响级别、市场反应、受影响标的、新闻分类标签

---

## 一、🏛️ 货币政策与美联储 (Monetary Policy & Federal Reserve)

### 1.1 美联储主席换届 — Kevin Warsh 上任
- **日期**: 2026-05-22
- **事件**: Kevin Warsh 宣誓就任美联储主席，接替 Jerome Powell。特朗普总统提名，标志着美联储进入新时代。
- **影响级别**: 🔴 CRITICAL
- **市场反应**: 
  - S&P 500 当日 -1.2%
  - 2年期国债收益率剧烈波动
  - 美元指数突破100
- **受影响标的**: SPY, QQQ, DIA, TLT, UUP
- **分类标签**: `monetary_policy`, `fed`, `leadership_change`, `interest_rate`
- **优先级评分参考**: 0.95 (breaking + macro + multi-sector)
- **深度分析建议**: 分析 Warsh 历史言论、政策倾向、对利率路径的影响

### 1.2 6月 FOMC 会议 — 鹰派转向
- **日期**: 2026-06-17
- **事件**: Warsh 首次主持 FOMC。利率维持 3.50%-3.75% 不变，但点阵图显示约50%官员预计年内至少加息一次（3月时为0%）。政策声明从341字缩减到132字，删除"宽松倾向"措辞，取消前瞻指引。
- **影响级别**: 🔴 CRITICAL
- **市场反应**:
  - S&P 500 -1.2%, Dow -507点, Nasdaq -1.0%
  - 2年期国债收益率 +14bps 至 4.16%
  - 10年期国债收益率升至 4.49%
  - 美元走强
- **受影响标的**: SPY, QQQ, TLT, IEF, UUP, XLF (银行), XLK (科技)
- **分类标签**: `monetary_policy`, `fomc`, `hawkish`, `rate_hike`, `forward_guidance`
- **优先级评分参考**: 0.95
- **深度分析建议**: 对比历次加息周期市场回撤幅度；分析 Warsh "安静美联储"对波动率的影响

### 1.3 美联储取消前瞻指引 — "安静美联储"时代
- **日期**: 2026-06-17 (与FOMC同步)
- **事件**: Warsh 宣布取消自2008年金融危机以来的前瞻指引传统，拒绝提交个人点阵图预测，使美联储政策方向更不透明。
- **影响级别**: 🟠 HIGH
- **市场反应**: VIX 波动率指数上升，市场对每次经济数据公布的反应更加剧烈
- **受影响标的**: VIX, SPY, TLT
- **分类标签**: `fed_policy`, `transparency`, `volatility`
- **优先级评分参考**: 0.75

### 1.4 通胀飙升至三年高点
- **日期**: 2026-05 (数据发布月)
- **事件**: 5月 CPI 同比升至 4.2%（三年新高），核心 PCE 升至 3.3%。受中东冲突、油价上涨和关税效应叠加影响。
- **影响级别**: 🔴 CRITICAL
- **市场反应**: 利率期货重新定价加息概率，国债收益率全线上扬
- **受影响标的**: TLT, SPY, GLD, XLE
- **分类标签**: `inflation`, `cpi`, `macro_data`, `stagflation_risk`
- **优先级评分参考**: 0.90

---

## 二、🌍 地缘政治事件 (Geopolitical Events)

### 2.1 美国-伊朗战争爆发
- **日期**: 2026-02-28
- **事件**: 美国和以色列对伊朗军事、政府和核设施发动军事行动。伊朗反击导致霍尔木兹海峡航运中断。
- **影响级别**: 🔴 CRITICAL
- **市场反应**:
  - Q1: Dow -3.6%, S&P 500 -4.6%, Nasdaq -7.1%
  - WTI 原油从 $67 飙升至 $119 (+78%)
  - 黄金一度冲高至 $5,300/oz
  - VIX 恐慌指数飙升
  - 10年期国债收益率从 ~4.00% 升至 ~4.67%
- **受影响标的**: USO, XLE, GLD, VIX, SPY, LMT (军工), RTX (军工), NOC (军工)
- **分类标签**: `geopolitical`, `war`, `oil_supply`, `energy_crisis`, `defense`
- **优先级评分参考**: 1.0 (breaking + macro + multi-sector + energy)
- **深度分析建议**: 军工复合体受益股筛选；航运中断对全球供应链的二阶效应

### 2.2 霍尔木兹海峡封锁
- **日期**: 2026-03-01 起
- **事件**: 主要保险公司终止霍尔木兹海峡战争险覆盖，油轮通行量从日均56艘骤降至7艘。全球约20%石油运输经此通道。
- **影响级别**: 🔴 CRITICAL
- **市场反应**:
  - 布伦特原油突破 $120/桶
  - 美国汽油价格峰值 $4.56/加仑
  - 全球航运股剧烈波动
- **受影响标的**: USO, BNO, XLE, 航运股 (FRO, NAT, STNG)
- **分类标签**: `supply_chain`, `oil`, `energy_crisis`, `shipping`
- **优先级评分参考**: 1.0

### 2.3 美伊停火协议签署
- **日期**: 2026-06-17
- **事件**: 美国-伊朗停火谅解备忘录签署，霍尔木兹海峡宣布将重新开放（60天窗口期）。卡塔尔和平谈判取得进展，特朗普设定8月18日为谈判截止日。
- **影响级别**: 🟠 HIGH
- **市场反应**:
  - Q2 美股暴涨: S&P 500 +14.9%, Nasdaq +21.4%
  - 油价暴跌30%+: 布伦特回到 $71.57
  - 黄金暴跌13% (Q2), 从 $5,300+ 跌至 $4,082
  - 军工股回落
- **受影响标的**: SPY, QQQ, USO, GLD, XLE
- **分类标签**: `geopolitical`, `ceasefire`, `peace_deal`, `oil_price`, `relief_rally`
- **优先级评分参考**: 0.85

### 2.4 委内瑞拉政权更迭
- **日期**: 2026 Q1
- **事件**: 美国主导行动逮捕马杜罗，委内瑞拉政权更迭。美国公司获得 $20亿基础设施合同，重塑全球能源格局。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 能源基础设施股上涨；Halliburton (HAL)、SLB 受益
- **受影响标的**: HAL, SLB, XLE
- **分类标签**: `geopolitical`, `energy`, `regime_change`, `infrastructure`
- **优先级评分参考**: 0.55

---

## 三、📊 宏观经济数据 (Macroeconomic Data)

### 3.1 ADP 就业数据不及预期
- **日期**: 2026-07-01
- **事件**: 6月 ADP 新增就业 +98,000，远低于预期的 110,000-120,000。劳动力市场降温信号。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 加息预期小幅回落，利率敏感型股票小幅反弹
- **受影响标的**: SPY, TLT, XLF
- **分类标签**: `employment`, `labor_market`, `macro_data`, `adp`
- **优先级评分参考**: 0.50

### 3.2 ISM 制造业指数
- **日期**: 2026-07-01
- **事件**: 6月 ISM 制造业 PMI 53.3 (预期 53.9)，物价支付分项降至4个月低点
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 制造业股票分化，通胀预期降温
- **受影响标的**: XLI, SPY
- **分类标签**: `manufacturing`, `pmi`, `macro_data`
- **优先级评分参考**: 0.45

### 3.3 失业率维持低位
- **日期**: 2026-06
- **事件**: 失业率 4.3%，劳动力市场具有韧性但增速放缓
- **影响级别**: 🟡 MEDIUM
- **受影响标的**: SPY, XLY (消费), XLF (金融)
- **分类标签**: `employment`, `macro_data`
- **优先级评分参考**: 0.40

---

## 四、🤖 科技与 AI 行业 (Technology & AI)

### 4.1 "七巨头" 6月集体暴跌
- **日期**: 2026-06
- **事件**: Magnificent Seven (Apple, Microsoft, Alphabet, Amazon, Nvidia, Meta, Tesla) 6月单月蒸发市值超 $2万亿。从5月中旬高点累计下跌超13%。投资者焦虑巨额AI资本开支回报不明确。
- **影响级别**: 🔴 CRITICAL
- **市场反应**:
  - Microsoft 6月 -20% (最惨)
  - Nvidia -13%
  - Apple / Amazon 各 -8%
  - 资金从科技巨头向传统行业轮动
- **受影响标的**: MSFT, AAPL, NVDA, GOOGL, AMZN, META, TSLA, QQQ, XLK
- **分类标签**: `tech_selloff`, `ai_spending`, `magnificent_seven`, `sector_rotation`, `cap_ex`
- **优先级评分参考**: 0.90
- **深度分析建议**: AI CapEx ROI 分析；对比2000年互联网泡沫

### 4.2 芯片股史诗级暴涨 — 费城半导体指数 H1 +93%
- **日期**: 2026 H1
- **事件**: 费城半导体指数 (SOX) 上半年暴涨93%，有望创1999年以来最佳年度表现。AI芯片需求爆发式增长，内存芯片短缺预计持续到2028年。
- **影响级别**: 🟠 HIGH
- **市场反应**:
  - SanDisk (SNDK) +760%
  - Micron (MU) +242% (Q2单季)
  - AMD +186% (Q2单季)
  - Intel, Western Digital, Seagate 全部翻倍+
- **受影响标的**: SOXX, SMH, SNDK, MU, AMD, INTC, WDC, STX
- **分类标签**: `semiconductor`, `ai_chips`, `sector_surge`, `memory_shortage`
- **优先级评分参考**: 0.80

### 4.3 芯片股获利了结暴跌 (7月初)
- **日期**: 2026-07-01 至 07-02
- **事件**: 芯片股在H1暴涨后遭遇猛烈获利了结
- **影响级别**: 🟠 HIGH
- **市场反应**:
  - SanDisk -10%+, KLA Corp -7%+, Lam Research -9%+, Applied Materials -9%+, Micron -9%+, AMD -7%+
  - SOXX ETF 单日 -6%+
- **受影响标的**: SOXX, SNDK, KLAC, LRCX, AMAT, MU, AMD
- **分类标签**: `semiconductor`, `profit_taking`, `sector_rotation`
- **优先级评分参考**: 0.70

### 4.4 七巨头 AI CapEx 引发市场反感
- **日期**: 2026 Q1-Q2 (持续事件)
- **事件**: 科技七巨头 2026年合计 AI 资本开支超 $7,000亿（部分依赖债务融资）。Microsoft 单季 $375亿 CapEx，全年预计 $1,900亿；Meta 指引全年 $1,450亿 CapEx。市场开始严惩"只烧钱不见效"的公司。
- **影响级别**: 🟠 HIGH
- **市场反应**:
  - Microsoft -14.5% YTD (尽管每季超预期)
  - Meta 发布 CapEx 指引后 -9%
  - Apple +1.8% YTD (务实的轻AI支出策略受青睐)
- **受影响标的**: MSFT, META, AAPL, GOOGL, AMZN
- **分类标签**: `ai_spending`, `capex`, `roi_concern`, `tech_investment`
- **优先级评分参考**: 0.75

### 4.5 Meta 宣布 AI 云业务
- **日期**: 2026-07-01
- **事件**: Meta 宣布将出售多余AI算力，构建云基础设施业务（类比 Amazon 20年前推出 AWS）。当日市值暴增 $1,790亿 (+11.3%)。
- **影响级别**: 🟠 HIGH
- **市场反应**:
  - Meta +11.3% (单日)
  - 新云竞争对手 CoreWeave -14%, Nebius Group -17%
- **受影响标的**: META, AMZN, MSFT, GOOGL, CRWV
- **分类标签**: `ai_cloud`, `business_model`, `meta`, `competition`
- **优先级评分参考**: 0.82

### 4.6 国防部与7家AI公司签约
- **日期**: 2026-04 末
- **事件**: 五角大楼与 Nvidia, Microsoft, Amazon, Google, OpenAI 等7家AI公司签署AI合作协议
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 相关AI军工概念股上涨
- **受影响标的**: NVDA, MSFT, AMZN, GOOGL, PLTR
- **分类标签**: `defense`, `ai_contract`, `government`
- **优先级评分参考**: 0.55

### 4.7 Walmart 和 Uber 缩减 AI 使用
- **日期**: 2026 Q2
- **事件**: AI 早期采用者 Walmart 和 Uber 在收到高额账单后开始缩减 AI 使用规模，引发"AI 泡沫"讨论
- **影响级别**: 🟡 MEDIUM
- **市场反应**: AI 软件股承压
- **受影响标的**: AI, C3.ai, SNOW
- **分类标签**: `ai_adoption`, `cost_concern`, `enterprise_ai`
- **优先级评分参考**: 0.50

---

## 五、🤝 并购与重组 (M&A)

### 5.1 2026 M&A 创历史纪录
- **日期**: 2026 H1
- **事件**: H1 全球并购宣布金额 $2.8万亿 (+48% YoY)，全年预计 $4-5.3万亿。$100亿以上超大型交易 47笔，合计 $1.3万亿。股票+现金混合支付占比创历史新高 (35%)。
- **影响级别**: 🟠 HIGH
- **受影响标的**: XLF (投行), GS, MS, JPM
- **分类标签**: `ma_boom`, `megadeals`, `investment_banking`
- **优先级评分参考**: 0.65

### 5.2 Paramount-Warner Bros Discovery 合并
- **日期**: 2026 H1
- **事件**: Paramount Skydance 以 $1,109亿 全现金收购 Warner Bros Discovery，重塑流媒体格局。合并套利空间约14%。
- **影响级别**: 🟠 HIGH
- **市场反应**: WBD 股价波动，媒体板块重估
- **受影响标的**: WBD, PARA, NFLX, DIS, CMCSA
- **分类标签**: `media_ma`, `streaming`, `merger_arbitrage`
- **优先级评分参考**: 0.70

### 5.3 SpaceX / xAI 合并
- **日期**: 2026 H1
- **事件**: SpaceX 与 xAI 合并为估值 $1.25万亿 的超级集团，融合航天物流与AI
- **影响级别**: 🟠 HIGH
- **受影响标的**: SPCX, TSLA (关联)
- **分类标签**: `mega_merger`, `space_ai`, `musk`
- **优先级评分参考**: 0.72

### 5.4 ON Semiconductor 收购 Synaptics — 暴跌21%
- **日期**: 2026 H1
- **事件**: ON Semiconductor 以 $70亿全股票收购 Synaptics，押注"物理AI"。市场担忧12%股权稀释且要到2028-2029年才能贡献盈利。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: ON -21% (2020年以来最大单日跌幅)
- **受影响标的**: ON, SYNA
- **分类标签**: `semiconductor_ma`, `dilution`, `stock_drop`
- **优先级评分参考**: 0.60

### 5.5 Kimberly-Clark / Kenvue 合并
- **日期**: 2026 Q1
- **事件**: Kimberly-Clark 以 $487亿 收购 Kenvue，史上最大消费品交易
- **影响级别**: 🟡 MEDIUM
- **市场反应**: KMB 宣布当日 -12%（债务和负债担忧），但股东以96%支持率批准
- **受影响标的**: KMB, KVUE, PG, CL
- **分类标签**: `consumer_ma`, `staples`
- **优先级评分参考**: 0.50

### 5.6 NextEra Energy / Dominion Energy 合并
- **日期**: 2026 H1
- **事件**: NextEra 以 $668亿 收购 Dominion，受AI数据中心能源需求驱动。公共事业行业最大交易之一。
- **影响级别**: 🟡 MEDIUM
- **受影响标的**: NEE, D, XLU
- **分类标签**: `energy_ma`, `utility`, `ai_power_demand`
- **优先级评分参考**: 0.50

### 5.7 Honeywell 三分拆
- **日期**: 2026-06 (完成)
- **事件**: Honeywell 拆分为三家独立上市公司（航空/自动化/材料），"纯业务"溢价策略
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 拆分完成后股价 -8%+
- **受影响标的**: HON
- **分类标签**: `breakup`, `spin_off`, `industrial`
- **优先级评分参考**: 0.45

### 5.8 其他值得关注的并购
- Alcoa (AA) 收购 South32 铝土矿/氧化铝/铝资产，最高 $56亿 → AA -8~9%
- Alphabet 收购 Wiz ($320亿，Google史上最大收购)
- Kroger (KR) 收购 Giant Eagle (~$16.5亿)
- Devon Energy / Coterra Energy 合并 ($580亿，Permian盆地整合)
- Rocket Lab / Iridium 合并 (~$80亿，太空整合)
- **分类标签**: `ma`
- **优先级评分参考**: 0.30-0.45

---

## 六、🚀 IPO 市场 (IPO Market)

### 6.1 SpaceX 史上最大 IPO
- **日期**: 2026-06-11 (定价), 06-12 (上市)
- **事件**: SpaceX (SPCX) 以 $135/股 定价上市，融资 ~$750亿，IPO估值 $1.77万亿。首日涨 19-23% 收于 ~$161-166。数日内估值突破 $2万亿。成为史上最大IPO，超越沙特阿美2019年纪录。
- **影响级别**: 🔴 CRITICAL
- **市场反应**:
  - SPCX 首日 +19-23%
  - 太空竞品被抽血: Planet Labs -9%, EchoStar -11~14%
  - 银行赚取 $5亿+ 承销费
  - 引发对 OpenAI/Anthropic 后续巨型IPO的关注
- **受影响标的**: SPCX, PL, SATS, NVDA, MSFT, AMZN, TSLA
- **分类标签**: `ipo`, `spacex`, `record_ipo`, `space_economy`, `musk`
- **优先级评分参考**: 0.95
- **深度分析建议**: SpaceX 估值合理性分析；对后续IPO的示范效应

### 6.2 OpenAI 和 Anthropic 巨型 IPO 推迟
- **日期**: 2026 H1
- **事件**: OpenAI ($1220亿重组为PBC) 和 Anthropic 已秘密提交 S-1，但因市场环境不佳推迟上市。分析师警告两者仍是"烧钱且商业模式未验证"的公司。
- **影响级别**: 🟡 MEDIUM
- **受影响标的**: MSFT (OpenAI关联), AMZN (Anthropic关联)
- **分类标签**: `ipo_pipeline`, `ai_company`, `delayed_ipo`
- **优先级评分参考**: 0.50

---

## 七、📈 企业财报 (Corporate Earnings)

### 7.1 Microsoft — 业绩超预期但股价下跌
- **日期**: 2026-01 (Q2FY26), 2026-04/05 (Q3FY26)
- **事件**: 连续两季 EPS 和 Revenue 超预期，但 Azure 增速指引放缓 (Q2→Q3: 40%→37-38%)，AI CapEx 过高引发担忧
- **影响级别**: 🟠 HIGH
- **市场反应**: Q2 财报后 -9%, Q3 财报后 -4%。YTD -14.5%
- **受影响标的**: MSFT, QQQ, XLK
- **分类标签**: `earnings`, `cloud_slowdown`, `ai_capex`, `microsoft`
- **优先级评分参考**: 0.75
- **训练要点**: 业绩超预期≠股价上涨，市场更关注前瞻指引和AI投入回报

### 7.2 Apple — 稳健超预期
- **日期**: 2026-01 (Q1FY26), 2026-05-01 (Q2FY26)
- **事件**: Q1: 营收 $1,437.6亿 (超预期 $1,382.5亿), EPS $2.84。Q2: 营收 $1,111.8亿, EPS $2.01, iPhone营收 +22% YoY。大中华区 Q1 +38% YoY, Q2 +28%。$1,000亿回购授权。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: Q2 财报后 +4.5%。YTD +1.8%
- **受影响标的**: AAPL, QQQ
- **分类标签**: `earnings`, `apple`, `iphone`, `buyback`, `china`
- **优先级评分参考**: 0.55
- **训练要点**: 低AI支出+高回购+服务增长=市场奖励"财务纪律"

### 7.3 NVIDIA — 市场最期待的财报
- **日期**: 2026-05-20 (Q1FY27)
- **事件**: 预期盈利增长 ~69%（继上一年 +59.5% 后）。ServiceNow AI芯片大单一度推升 NVDA +5.77%
- **影响级别**: 🔴 CRITICAL
- **市场反应**: 财报前夕市场高度紧张，"将定调整个夏季AI行情"
- **受影响标的**: NVDA, SMH, SOXX, QQQ
- **分类标签**: `earnings`, `nvidia`, `ai_trade`, `bellwether`
- **优先级评分参考**: 0.90
- **训练要点**: NVDA 财报是AI产业链的"审判日"，影响远超个股

### 7.4 General Mills — 成本削减带动大涨
- **日期**: 2026 Q2
- **事件**: Q4财报超预期 + 宣布 $30亿成本削减计划
- **影响级别**: 🟡 MEDIUM
- **市场反应**: +8%+
- **受影响标的**: GIS, XLP
- **分类标签**: `earnings`, `cost_cutting`, `consumer_staples`
- **优先级评分参考**: 0.40

### 7.5 Nike — CEO 扭亏计划提振
- **日期**: 2026 Q2
- **事件**: Q4利润超预期，CEO Elliott Hill 扭亏计划初显成效
- **影响级别**: 🟡 MEDIUM
- **市场反应**: +5%+
- **受影响标的**: NKE, XLY
- **分类标签**: `earnings`, `turnaround`, `retail`
- **优先级评分参考**: 0.45

---

## 八、🏭 贸易政策与关税 (Trade Policy & Tariffs)

### 8.1 "堡垒美国" 关税体系
- **日期**: 2026 H1 (持续)
- **事件**: 特朗普政府将关税从"谈判工具"升级为"永久性国内经济政策支柱"。平均有效关税率为1946年以来最高。Tax Foundation 估算每户年均多支出 $1,300，GDP 10年累计减少 0.5%。
- **影响级别**: 🟠 HIGH
- **市场反应**: 制造业回流受益股 vs 进口依赖受损股剧烈分化
- **受影响标的**: 
  - 受益: NUE, CLF, STLD (钢铁), CAT, XOM, INTC
  - 受损: GM, F, AAPL, NVDA, NKE, GPS, BBY
- **分类标签**: `tariff`, `trade_war`, `protectionism`, `supply_chain`
- **优先级评分参考**: 0.75

### 8.2 "格陵兰关税危机"
- **日期**: 2026-01
- **事件**: 8个欧洲国家因格陵兰谈判被威胁加征10-25%关税。S&P 500 在特朗普第二任期就职一周年当日 -1.8%。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: VIX 突破 22, 10年期收益率升至 4.28%
- **受影响标的**: SPY, VIX, FEZ (欧洲)
- **分类标签**: `tariff`, `geopolitical`, `trade_tension`
- **优先级评分参考**: 0.55

### 8.3 半导体关税威胁
- **日期**: 2026 H1
- **事件**: 威胁对芯片征收高达300%关税；要求台湾产AI芯片经美国本土"测试中转"。Intel 赢得苹果美国本土芯片订单后 +10%。
- **影响级别**: 🟠 HIGH
- **市场反应**: 芯片供应链剧烈重构
- **受影响标的**: NVDA, AMD, INTC, TSM, AVGO, MU
- **分类标签**: `semiconductor`, `tariff`, `supply_chain`, `chip_war`
- **优先级评分参考**: 0.70

### 8.4 10% 信用卡利率上限提案
- **日期**: 2026-01-09
- **事件**: 特朗普政府提议信用卡利率上限10%为期一年。Jamie Dimon 警告对整个行业造成"$1,000亿冲击"，分析师预估削减发卡行税前利润18%。
- **影响级别**: 🟠 HIGH
- **市场反应**: WFC -4.6%, BAC -3.8%, C -3.4%
- **受影响标的**: WFC, BAC, C, JPM, COF, DFS, AXP
- **分类标签**: `regulation`, `credit_card`, `banking`, `interest_cap`
- **优先级评分参考**: 0.70

### 8.5 最高法院推翻 IEEPA 关税
- **日期**: 2026-02
- **事件**: 最高法院在 *Learning Resources, Inc. v. Trump* 案中裁定 IEEPA 基础关税违宪。政府随即依据《1974年贸易法》第122条征收150天临时"过渡关税"(10%→15%)。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 关税不确定性短期缓解但中期加剧
- **受影响标的**: SPY, XLI, XLY
- **分类标签**: `supreme_court`, `tariff`, `legal`, `trade_law`
- **优先级评分参考**: 0.60

---

## 九、🏦 银行与金融业 (Banking & Financial)

### 9.1 2026年首宗银行倒闭
- **日期**: 2026-01-30
- **事件**: 芝加哥 Metropolitan Capital Bank & Trust 被关闭 (~$2.61亿资产)，由 First Independence Bank 收购。FDIC存款保险基金损失 ~$1,970万。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 区域性银行股短暂承压，但远小于2023年SVB冲击
- **受影响标的**: KRE, XLF
- **分类标签**: `bank_failure`, `regional_bank`, `fdic`
- **优先级评分参考**: 0.50

### 9.2 美联储压力测试 — 32家大银行全部通过
- **日期**: 2026 H1
- **事件**: 压力测试模拟失业率10%、经济萎缩4.6%、房价跌30%、股市暴跌58%。全部32家银行通过。总资本充足率从12.8%仅降至11.2%。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 银行股短期提振
- **受影响标的**: JPM, BAC, WFC, C, GS, MS, XLF
- **分类标签**: `stress_test`, `banking`, `regulation`, `capital_adequacy`
- **优先级评分参考**: 0.45

### 9.3 HSBC MFS 欺诈案损失
- **日期**: 2026-05
- **事件**: HSBC 因英国房贷机构 MFS (Market Financial Solutions) 欺诈倒闭案损失 $4亿。Barclays 也计提 £2.28亿减值。暴露 $3.5万亿私人信贷市场风险。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: HSBC -6%
- **受影响标的**: HSBC, BCS, DB
- **分类标签**: `fraud`, `private_credit`, `bank_loss`, `contagion_risk`
- **优先级评分参考**: 0.55

### 9.4 大银行财报季抛售
- **日期**: 2026-01
- **事件**: 大银行Q4业绩不及预期，叠加信用卡利率上限提案
- **市场反应**: WFC -4.6%, BAC -3.8%, C -3.4%
- **受影响标的**: WFC, BAC, C, JPM
- **分类标签**: `earnings`, `banking`, `regulation`
- **优先级评分参考**: 0.50

---

## 十、🛢️ 能源与商品 (Energy & Commodities)

### 10.1 油价坐过山车
- **日期**: 2026 H1
- **事件**: WTI 从战前 $67 → 高峰 $119 (+78%) → 停火后 $71。布伦特从 $70-80 → $120+ → $71.57。全球能源市场剧烈动荡。
- **影响级别**: 🔴 CRITICAL
- **市场反应**: 能源股 Q1暴涨 Q2回落；航空公司成本剧增；消费者支出承压
- **受影响标的**: XLE, USO, XOP, DAL, AAL, UAL
- **分类标签**: `oil_price`, `energy`, `commodity_volatility`
- **优先级评分参考**: 0.90

### 10.2 黄金史诗级暴跌
- **日期**: 2026 Q2
- **事件**: 黄金从 $5,300+/oz 暴跌至 $4,082 (-13%, Q2)，白银 -20%。为2013年以来最差季度表现。地缘风险消退+高利率+美元走强三重打击。
- **影响级别**: 🟠 HIGH
- **市场反应**: 贵金属矿业股暴跌
- **受影响标的**: GLD, SLV, GDX, NEM, GOLD
- **分类标签**: `gold`, `precious_metals`, `commodity_crash`
- **优先级评分参考**: 0.70

### 10.3 美国汽油价格冲高回落
- **日期**: 2026 H1
- **事件**: 全国均价从战前 $3以下 → 峰值 $4.56/加仑 (5/26) → 逐步回落。成为中期选举关键议题。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 消费股承压，零售销售波动
- **受影响标的**: XLY, XRT, WMT, TGT
- **分类标签**: `gasoline`, `consumer`, `inflation`
- **优先级评分参考**: 0.50

### 10.4 内存芯片短缺 (持续至2028年)
- **日期**: 2026 H1 (持续事件)
- **事件**: 全球内存芯片短缺预计持续到2028年，驱动芯片制造商业绩暴涨
- **影响级别**: 🟡 MEDIUM
- **受影响标的**: MU, SNDK, WDC, STX
- **分类标签**: `supply_shortage`, `semiconductor`, `memory_chips`
- **优先级评分参考**: 0.50

---

## 十一、🪙 加密货币 (Cryptocurrency)

### 11.1 比特币从高点腰斩
- **日期**: 2025-10 至 2026-07
- **事件**: 比特币从 2025-10-06 ATH $126,080 跌至 ~$59,000 (-53%)。以太坊从 $4,946 跌至 ~$1,590 (-68%)。双双跌破长期均线。
- **影响级别**: 🟠 HIGH
- **市场反应**: 加密相关股票 (COIN, MSTR, MARA) 承压
- **受影响标的**: BTC, ETH, COIN, MSTR, MARA, RIOT
- **分类标签**: `crypto_crash`, `bitcoin`, `bear_market`
- **优先级评分参考**: 0.70

### 11.2 比特币 ETF 创纪录流出
- **日期**: 2026-06
- **事件**: 美国现货比特币 ETF 6月净流出 $45亿（自2024年1月推出以来最差月份）。YTD 累计流出 ~$33亿。以太坊 ETF 6月也流出 $5.29亿。
- **影响级别**: 🟠 HIGH
- **市场反应**: Citi 将12个月 ETF 净流入假设从 $100亿降至 $0
- **受影响标的**: IBIT, FBTC, GBTC, BITO
- **分类标签**: `bitcoin_etf`, `outflows`, `institutional`
- **优先级评分参考**: 0.65

### 11.3 Citi 大幅下调比特币目标价
- **日期**: 2026-07
- **事件**: Citi 将 BTC 12个月目标从 $143,000 → $112,000 → $82,000（两次下调）。熊市情形 $53,000。理由: ETF资金流出+机构兴趣减弱+立法停滞。
- **影响级别**: 🟡 MEDIUM
- **市场反应**: 加密市场情绪进一步恶化
- **受影响标的**: BTC, ETH
- **分类标签**: `analyst_downgrade`, `bitcoin`, `price_target`
- **优先级评分参考**: 0.50

### 11.4 加密立法停滞 (CLARITY Act)
- **日期**: 2026 H1
- **事件**: 《数字资产市场清晰法案》陷入停滞。原因：特朗普加密商业利益引发的道德争议 + 稳定币收益争议 + 中期选举前参议院路径不明。
- **影响级别**: 🟡 MEDIUM
- **受影响标的**: BTC, ETH, COIN
- **分类标签**: `crypto_regulation`, `legislation`, `stalemate`
- **优先级评分参考**: 0.50

---

## 十二、💊 医疗与生物科技 (Healthcare & Biotech)

### 12.1 UniQure — FDA 逆转批准亨廷顿舞蹈症基因疗法
- **日期**: 2026-06
- **事件**: FDA 戏剧性大转弯，允许 UniQure 以现有3年 I/II 期数据申报加速批准（此前被斥为"失败产品"并要求全新假手术对照试验）。标志 FDA 进入"看护模式"。
- **影响级别**: 🟠 HIGH
- **市场反应**: QURE +78%至80% (单日), 从52周低点 $8.73 飙升至 $48.16
- **受影响标的**: QURE, XBI, IBB
- **分类标签**: `fda`, `gene_therapy`, `accelerated_approval`, `biotech`, `regulatory_reversal`
- **优先级评分参考**: 0.75
- **训练要点**: FDA 人事变动可能引发审批标准松紧变化，生物科技股对此极度敏感

### 12.2 Concord Biotech — 仿制药获批
- **日期**: 2026-06
- **事件**: USFDA 批准 Tofacitinib 仿制药 (Pfizer Xeljanz 仿制版)，$5亿美国市场
- **影响级别**: 🟢 LOW
- **市场反应**: +5-6%
- **受影响标的**: 印度制药 (Concord)
- **分类标签**: `fda`, `generic_drug`, `anda`
- **优先级评分参考**: 0.25

---

## 📋 附录：新闻影响级别分类标准

| 级别 | 代码 | 定义 | 典型评分范围 | 预期市场影响 |
|------|------|------|-------------|-------------|
| 🔴 关键 | CRITICAL | 影响整体市场方向、货币政策、地缘格局 | 0.85-1.0 | 大盘指数 1%+ 波动，跨板块传染 |
| 🟠 重要 | HIGH | 影响特定板块或大型公司，有跨板块波及可能 | 0.60-0.84 | 板块指数 1-3% 波动 |
| 🟡 中等 | MEDIUM | 影响个股或子行业，有一定市场关注度 | 0.35-0.59 | 个股/子行业 1-5% 波动 |
| 🟢 一般 | LOW | 行业常规事件，影响范围有限 | 0.10-0.34 | 个股小幅波动 <1% |

## 📋 附录：新闻分类标签体系

```
# 一级分类
monetary_policy     - 货币政策 (FOMC, 利率, 美联储)
geopolitical        - 地缘政治 (战争, 制裁, 国际关系)
macro_data          - 宏观经济数据 (就业, 通胀, GDP)
corporate_earnings  - 企业财报
ma                  - 并购重组
ipo                 - 首次公开募股
trade_policy        - 贸易政策 (关税, 贸易协议)
banking             - 银行金融业
energy_commodity    - 能源与大宗商品
cryptocurrency      - 加密货币
technology_ai       - 科技与人工智能
healthcare_biotech  - 医疗与生物科技
regulation          - 监管政策

# 二级标签 (情绪/性质)
hawkish             - 鹰派
dovish              - 鸽派
bullish             - 利多
bearish             - 利空
breaking            - 突发
supply_chain        - 供应链
leadership_change   - 领导层变动
profit_taking       - 获利了结
sector_rotation     - 板块轮动
contagion_risk      - 传染风险
```

## 📋 附录：训练使用建议

1. **优先级评分训练**: 将事件描述输入系统，对比人工标注的影响级别，训练 PriorityScorer 权重
2. **实体抽取训练**: 每条新闻中人名/机构名/产品名/指标名作为 NER 标注
3. **情感分析训练**: 标注每条事件的 market_sentiment (positive/negative/neutral/mixed)
4. **事件聚类训练**: 同一主题事件（如美伊战争相关的油价波动、停火）应聚合为同一 event_line
5. **战略检测训练**: 标注 gov_intervention / investment / endorsement / competitive_threat 类型
6. **多源共振训练**: 标注哪些事件应当触发"多源确认"逻辑（fast_lane 提升到 deep_lane）

---

> **数据来源**: Nasdaq, Yahoo Finance, AP News, FRED Blog, Morgan Stanley, Goldman Sachs, Citi Research, Wedbush, J.P. Morgan, New York Times, CoinDesk, FDA, SEC EDGAR
> **编制日期**: 2026-07-02
> **适用范围**: News Monitor 系统训练 / PriorityScorer 校准 / StrategicDetector 关键词扩充
