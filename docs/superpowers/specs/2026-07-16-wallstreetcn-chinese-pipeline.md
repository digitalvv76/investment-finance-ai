# 华尔街见闻中文管道适配 — V1 诊断 → V2 实现

> 状态: V1 诊断完成，待 V2 实施 | 日期: 2026-07-16

## 诊断结论

华尔街见闻是**幽灵源**：5 个频道正常采集（1 分钟心跳，每频道 20 条），但管道从头到尾未适配中文，采集到的新闻被筛选静默丢弃，零推送。

## 根因：三层缺陷

### ① 实体提取 — 中文公司名→ticker 映射缺失

`entity_extractor.py` 的 `_company_to_ticker` 只有英文名（"nvidia"→NVDA），不含中文名（"英伟达"→NVDA）。中文新闻用「英伟达」不写「NVDA」，ticker 提取为零。

关键词匹配（`_known_macro`）已有中文宏观术语（美联储、CPI、PPI 等），这是唯一能得分的因子。但仅靠 macro 标签不够稳定。

### ② 优先级评分 — 中文模式缺失 + 权重过低

- `_DEVIATION_PATTERNS`：6 个正则全是英文（"vs expected"、"beat forecasts"），不匹配「高于预期」「超出预期」「不及预期」
- `_SURPRISE_KEYWORDS`：19 个关键词全是英文（"shock"、"plunge"），不匹配「意外」「震惊」「暴跌」「暴涨」
- `SOURCE_AUTHORITY`：华尔街见闻 0.02-0.03，与 ZeroHedge 同档。但华尔街见闻是中国最好的财经快讯源之一，应不低于 0.05

### ③ 事件评估 — 缺少中文 few-shot 样本

`event_driven_v1.txt` prompt 本身是中文，但缺少中文新闻的 few-shot 样本。DeepSeek 能读中文，但没有中文范例对齐，评估质量不稳定。

---

## V2 实施方案

### 改动 1/4：`entity_extractor.py` — 中文公司名映射

在 `_company_to_ticker` 之后新增 `_cn_company_to_ticker`，在 `_extract_tickers()` 中增加中文名匹配步骤。

```python
# 新增：中文公司名 → ticker 映射
_cn_company_to_ticker: dict[str, str] = {
    # 科技七巨头
    "英伟达": "NVDA", "辉达": "NVDA",
    "苹果": "AAPL", "微软": "MSFT",
    "谷歌": "GOOGL", "亚马逊": "AMZN",
    "脸书": "META", "元宇宙": "META", "元宇宙平台": "META",
    "特斯拉": "TSLA",
    # 半导体
    "英特尔": "INTC", "超威": "AMD", "超微": "AMD",
    "博通": "AVGO", "高通": "QCOM", "美光": "MU",
    "德州仪器": "TXN", "应用材料": "AMAT", "泛林": "LRCX",
    "拉姆研究": "LRCX", "科磊": "KLAC", "安森美": "ON",
    "迈威尔": "MRVL", "迈威尔科技": "MRVL",
    "安谋": "ARM", "安谋科技": "ARM",
    "台积电": "TSM", "联电": "UMC", "中芯国际": None,  # A股/港股
    # 关注股 — 半导体/AI
    "帕兰提尔": "PLTR", "帕兰泰尔": "PLTR",
    # 关注股 — 太空/防务
    "火箭实验室": "RKLB", "奎托斯": "KTOS",
    "宇航电信": "ASTS", "太空移动": "ASTS",
    # 关注股 — 量子/核能/新兴
    "里盖蒂": "RGTI", "奥克洛": "OKLO",
    "纽斯凯尔": "SMR", "核能革新": "SMR",
    "天普思": "TEM", "奈比斯": "NBIS",
    # 加密美股
    "币基地": "COIN", "微策略": "MSTR",
    "瑞波": None,  # 非美股，但新闻常见
    "马拉松数字": "MARA", "马拉松": "MARA",
    "清洁火花": "CLSK", "哈特8": "HUT",
    "暴乱": "RIOT", "暴乱平台": "RIOT",
    # 金融科技
    "布洛克": "SQ", "方块": "SQ",
    "确认": "AFRM", "索菲": "SOFI",
    "罗宾汉": "HOOD",
    # 金融 — 大行
    "摩根大通": "JPM", "高盛": "GS", "摩根士丹利": "MS",
    "花旗": "C", "美国银行": "BAC", "富国银行": "WFC",
    # 能源
    "埃克森美孚": "XOM", "雪佛龙": "CVX",
    # 零售/消费
    "沃尔玛": "WMT", "耐克": "NKE", "迪士尼": "DIS",
    "奈飞": "NFLX", "网飞": "NFLX",
    "赛富时": "CRM", "甲骨文": "ORCL", "奥多比": "ADBE",
    "贝宝": "PYPL",
    # 波音
    "波音": "BA",
}
```

**`_extract_tickers()` 新增步骤 3**（在现有步骤 1 regex + 步骤 2 英文名映射之后）：

```python
# 3. Chinese company-name → ticker mapping
for cn_name, ticker in self._cn_company_to_ticker.items():
    if cn_name in text and ticker and ticker in FALLBACK_TICKERS:
        found.add(ticker)
```

### 改动 2/4：`priority.py` — 评分因子中文适配

#### 2a. 信源权威调高

```python
# priority.py SOURCE_AUTHORITY diff
-    "华尔街见闻·全球快讯": 0.02,
-    "华尔街见闻·美股": 0.03,
-    "华尔街见闻·外汇": 0.02,
-    "华尔街见闻·加密货币": 0.02,
-    "华尔街见闻·大宗商品": 0.02,
+    "华尔街见闻·全球快讯": 0.06,
+    "华尔街见闻·美股": 0.06,
+    "华尔街见闻·外汇": 0.05,
+    "华尔街见闻·加密货币": 0.05,
+    "华尔街见闻·大宗商品": 0.05,
-    "新浪财经·7x24综合快讯": 0.02,
-    "新浪财经·7x24全球财经": 0.02,
+    "新浪财经·7x24综合快讯": 0.04,
+    "新浪财经·7x24全球财经": 0.04,
```

#### 2b. 中文预期差正则

在 `_DEVIATION_PATTERNS` 列表末尾新增：

```python
# Chinese deviation patterns
re.compile(
    r"(?P<actual>[\d,.]+[KMB%万亿]?)\s*(?:高于|超出|超过|好于|强于)\s*(?:市场|一致)?(?:预期|预估|预测|估计)\w*(?:的\s*)?(?P<expected>[\d,.]+[KMB%]?)?",
),
re.compile(
    r"(?P<actual>[\d,.]+[KMB%万亿]?)\s*(?:低于|不及|弱于|差于|逊于)\s*(?:市场|一致)?(?:预期|预估|预测|估计)\w*(?:的\s*)?(?P<expected>[\d,.]+[KMB%]?)?",
),
# "预期2.5%实际2.7%" / "市场预估190K结果285K"
re.compile(
    r"(?:市场|一致)?(?:预期|预估|预测|估计)\s*(?P<expected>[\d,.]+[KMB%]?)\s*(?:实际|结果|公布|录得|报)\s*(?P<actual>[\d,.]+[KMB%万亿]?)",
),
# "大超预期" / "远低预期" — qualitative deviation (no numbers, direction only)
re.compile(
    r"(?P<direction>大超|远超|大幅?超|大幅?高[于出]|大幅?低[于出]|远低[于出]|不及|逊于)\s*(?:市场|一致)?(?:预期|预估)",
),
```

#### 2c. 中文意外关键词

在 `_SURPRISE_KEYWORDS` 列表末尾新增：

```python
# Chinese surprise keywords
("意外", 0.8), ("出乎意料", 0.8), ("出人意料", 0.8),
("震惊", 0.9), ("震惊全球", 1.0),
("暴跌", 0.8), ("暴涨", 0.7), ("闪崩", 0.9), ("熔断", 0.9),
("创纪录", 0.7), ("创历史新高", 0.7), ("创历史新低", 0.7),
("历史新高", 0.7), ("历史新低", 0.7), ("历史最高", 0.7),
("崩盘", 0.9), ("恐慌", 0.9), ("恐慌性", 0.9),
("黑天鹅", 0.9), ("灰犀牛", 0.7),
("突然", 0.6), ("骤然", 0.6), ("急剧", 0.6),
("大跌", 0.6), ("大涨", 0.5), ("飙升", 0.7), ("骤降", 0.7),
("大幅跳涨", 0.7), ("大幅跳水", 0.8),
# Market-specific
("史诗级", 0.8), ("历史性", 0.7),
```

### 改动 3/4：`event_driven_v1.txt` — 中文 few-shot 样本

在 prompt 末尾（JSON 输出示例区域）新增 3 个中文 few-shot：

```
### 中文新闻示例（与英文同等对待）

**示例1 — 宏观数据超预期（催化剂3等效）**
标题：美国6月PPI同比增长2.7%，高于预期的2.5%
摘要：美国劳工部公布6月生产者价格指数，同比上涨2.7%，超出市场预期的2.5%。核心PPI同比上涨3.0%，亦高于预期的2.8%。
→ {"is_event": true, "intensity": 4, "timeliness": "immediate", "direction": "neutral", "confirmed": true, "sector_tags": ["Macro", "Fed Policy", "Equities Broad"], "headline_signal": "PPI超预期强化利率higher-for-longer叙事，科技成长股估值承压，价值/能源板块受益", "ticker_hint": ["SOXX", "XLF", "XLE"]}

**示例2 — 芯片法案政府入股（催化剂1）**
标题：英特尔获CHIPS法案最高80亿美元补贴，将用于亚利桑那州工厂建设
摘要：美国商务部宣布与英特尔达成初步协议，提供最高80亿美元CHIPS法案补贴及110亿美元贷款，支持其在亚利桑那、俄亥俄等州的先进芯片制造设施建设。
→ {"is_event": true, "intensity": 5, "timeliness": "immediate", "direction": "up", "confirmed": true, "sector_tags": ["Semiconductor", "Government Contract", "AI Foundry"], "headline_signal": "80亿美元CHIPS补贴锁定英特尔先进制程扩产确定性，设备材料链（AMAT/LRCX/KLAC）和AI算力基建双重受益", "ticker_hint": ["INTC", "AMAT", "LRCX", "KLAC", "AMD", "NVDA"]}

**示例3 — 暴涨/模因（催化剂5，确认已发生）**
标题：游戏驿站盘中暴涨超90%触发熔断，Reddit散户再度集结
摘要：GameStop股价周二盘中一度暴涨超90%并多次触发熔断，此前被视为2021年模因股热潮核心人物的Roaring Kitty时隔近三年首次在社交媒体发文，引发散户集体买入。
→ {"is_event": true, "intensity": 5, "timeliness": "immediate", "direction": "up", "confirmed": true, "sector_tags": ["Meme Stocks", "Retail Trading"], "headline_signal": "Roaring Kitty时隔三年回归引爆GME轧空，已触发熔断→强催化5，散户资金实际涌入，但AMC等跟风股可能冲高回落", "ticker_hint": ["GME", "AMC"]}

**示例4 — 传闻（不确认，不上手机）**
标题：据传OpenAI正洽谈以600亿美元估值进行新一轮融资
摘要：据知情人士透露，OpenAI正在与投资者洽谈新一轮融资，估值可能达到600亿美元，但谈判仍处于早期阶段，条款尚未敲定。
→ {"is_event": true, "intensity": 3, "timeliness": "recent", "direction": "up", "confirmed": false, "sector_tags": ["AI", "SaaS"], "headline_signal": "OpenAI传闻融资属未证实消息→confirmed=false，不上手机，TG静音通知", "ticker_hint": ["MSFT"]}

**示例5 — 纯A股无美股映射（过滤）**
标题：央行降准0.5个百分点释放长期资金约1万亿元
摘要：中国人民银行决定下调金融机构存款准备金率0.5个百分点，此次降准预计释放长期资金约1万亿元，旨在支持实体经济发展。
→ {"is_event": false, "filter_reason": "中国央行降准主要影响A股/港股，无直接美股映射标的"}
```

### 改动 4/4：`keywords.yaml` — 补充中文关键词

#### 4a. `key_people` 补充

```yaml
key_people_tier1:
  # 现有 + 新增
  - "黄仁勋"        # 已有
  - "苏姿丰"        # AMD CEO Lisa Su
  - "鲍威尔"        # Jerome Powell
  - "沃什"          # Kevin Warsh
  - "萨姆·奥特曼"   # Sam Altman
  - "山姆·奥特曼"

key_people_tier2:
  # 现有 + 新增
  - "马斯克"        # Elon Musk
  - "埃隆·马斯克"
  - "巴菲特"        # Warren Buffett
  - "戴蒙"          # Jamie Dimon
  - "杰米·戴蒙"
  - "耶伦"          # Janet Yellen
  - "詹斯勒"        # Gary Gensler
  - "方舟"          # Cathie Wood / ARK
  - "木头姐"

key_people_tier3:
  # 现有 + 新增
  - "特朗普"        # Trump
  - "拜登"          # Biden
  - "贝森特"        # Scott Bessent (Treasury Secretary)
  - "卢特尼克"      # Howard Lutnick (Commerce Secretary)
```

#### 4b. `macro_alerts` 补充

```yaml
macro_alerts:
  # 现有 + 新增中文
  - "非农就业"      # 已有"非农"，补全称
  - "消费者价格指数"
  - "生产者价格指数"
  - "核心通胀"
  - "初请失业金"
  - "续请失业金"
  - "零售销售"
  - "ISM制造业"
  - "ISM服务业"
  - "密歇根大学消费者信心"
  - "美联储利率决议"
  - "点阵图"
  - "缩表"
  - "扩表"
  - "收益率曲线"
  - "倒挂"
```

### 改动 5/4：`sources.yaml` — 新增日经 Nikkei Asia RSS

日经是亚洲科技/AI/半导体新闻的核心一手源。黄仁勋亚洲行、台积电供应链、Rapidus 进展、日本 AI 政策等关键事件常由日经首发，但当前采集源列表中完全没有日经。

```yaml
# tier_1_rss 列表新增：
- name: "Nikkei Asia"
  url: "https://asia.nikkei.com/rss/feed/nar"
  category: "macro"
  delay_seconds: 3
```

**说明**：
- RSS URL 经过验证 (`https://asia.nikkei.com/rss/feed/nar`)
- 用途为个人投资研究，属个人非商业使用，符合 RSS 使用条款
- 归类 macro（日经覆盖科技政策+产业+宏观，跨领域）
- delay 3s 与 WSJ Markets 同级，避免请求过频

---

## 验收标准

### 测试（必须）
1. `test_chinese_fetcher.py` — 已有，确认通过
2. **新增** `test_chinese_entity_extraction.py`:
   - 输入「英伟达股价创历史新高」→ tickers 含 NVDA ✅
   - 输入「苹果市值突破4万亿美元」→ tickers 含 AAPL ✅
   - 输入「特斯拉暴跌15%」→ tickers 含 TSLA，意外关键词命中 ✅
3. **新增** `test_chinese_priority.py`:
   - 中文 PPI 新闻「美国6月PPI同比上涨2.7%，高于预期的2.5%」→ priority_score ≥ 0.15 ✅
   - 中文 routine 新闻「沪深两市成交额再破万亿」→ priority_score < 0.15 ✅
   - 华尔街见闻信源权重 → SOURCE_AUTHORITY ≥ 0.05 ✅
4. `test_priority.py` — 已有，确认通过

### Playwright E2E（必须）
- 推送面板确认出现华尔街见闻来源的中文新闻（`/health/decisions`）

### 生产观察（上线后 3 天）
- 华尔街见闻推送频率：预期每天 1-5 条有效推送
- 检查误推：涨停/跌停/A股限售解禁等是否仍被过滤
- 检查漏推：重要宏观数据发布是否到位

---

## 风险与回滚

| 风险 | 概率 | 缓解 |
|------|:---:|------|
| 中文噪声涌入（A股涨跌停、国内政策） | 中 | `_is_noise_title` + `noise_patterns_cn` 已覆盖，观察 3 天 |
| 中文映射表覆盖面不足 | 中 | 本次覆盖 70+ 常用中文名，后续按需补 |
| 华尔街见闻 API 变更导致采集失败 | 低 | 日志已有 warning，上线后检查 |
| 中文推送过多干扰用户 | 低 | 事件评估门槛不变，只是让中文新闻有机会到达评估环节 |
| DeepSeek 中文评估质量不稳定 | 低 | 中文 few-shot 样本对齐，且 prompt 本身已是中文 |

回滚：`git revert` + `deploy-main.sh`，与现有流程一致。

---

## 预估工作量

| 文件 | 改动量 | 难度 |
|------|:---:|:---:|
| `entity_extractor.py` | +80 行映射表 + 5 行匹配逻辑 | 低 |
| `priority.py` | +35 行中文模式 + 8 行权重调整 | 低 |
| `event_driven_v1.txt` | +25 行 few-shot 样本 | 低 |
| `keywords.yaml` | +30 行补充关键词 | 低 |
| `sources.yaml` | +5 行（日经 RSS） | 低 |
| 测试（新建） | ~30 条测试用例 | 中 |
| **总计** | ~185 行改动 + 测试 | 半天 |
