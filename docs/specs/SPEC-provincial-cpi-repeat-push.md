# SPEC: 宏观新闻地域分级 → 堵省级CPI刷屏

> V1 → V2 交接 | 2026-07-17 | 来源：用户反馈 TG 刷屏"广东居民消费价格"

## 问题

7月17日 TG 推送了非核心经济体宏观新闻，两起事件：

| 时间 | 新闻 | 命中关键词 | 应属级别 |
|------|------|-----------|---------|
| 白天 | 广东居民消费价格同比上涨 | `居民消费价格` (CPI) | ❌ 排除（省级） |
| 刚才 | 马来西亚 GDP 增速 | `GDP` / `经济增速` | ❌ 排除（非核心经济体） |

五道防线全部失守：

| # | 阶段 | 失守原因 |
|---|------|----------|
| 1 | 去重 | `居民消费价格` 命中 Tier A CPI 白名单 → 无条件跳过全部四层去重 |
| 2 | 内容过滤 | 含 "CPI" 字样 → 中文降权 ×0.5 被 `_has_us_market_signal` 豁免 |
| 3 | LLM 打分 | Prompt 只说 CPI = 宏观催化剂，未区分美国CPI vs 中国省级CPI |
| 4 | TG 去重 | Telegram 没有主题去重，只有 Pushover 手机端有 |
| 5 | 聚类 | 30分钟窗口太短，不同时段的新浪/华尔街见闻无法合并 |

**根因**：`居民消费价格` 是白名单关键词，系统把它当美国 CPI 对待。

## 宏观地域三级体系

> 用户决策：宏观新闻按地域分三级，影响去重优先级 + 评分权重 + 推送门槛。
>
> **核心原则：默认拒绝。不在 T1/T2/T3 列表中的国家和地区 → 不构成宏观催化剂，不推。**

| 级别 | 地区 | 去重 | 评分权重 | 手机推送 | 说明 |
|------|------|:---:|:---:|:---:|------|
| **T1** | 🇺🇸 美国 | 白名单放行 | ×1.0 | 正常门槛 | 全球定价锚，驱动所有资产 |
| **T2** | 🇪🇺 欧洲 · 🇯🇵 日本 | 白名单放行 | ×0.85 | 正常门槛 | 重要经济体，影响区域和外汇 |
| **T3** | 🇨🇳 中国全国 · 🇰🇷 韩国 | 正常去重 | ×0.7 | 仅 T3 ≥ IMPORTANT | 新兴市场核心，影响港股/A股/韩股 |
| **排除** | 中国省级/市级、其他地区 | 正常去重 | 不适用 | 不推 | 不构成宏观催化剂 |

**关键区分**：
- "中国6月CPI同比上涨2.1%" → T3，是国家统计局全国数据
- "广东6月居民消费价格同比上涨2.1%" → 排除，是省级数据
- "韩国央行维持基准利率3.5%不变" → T3，是韩国全国级政策

---

## 实施方案（4 项）

### P0: macro_indicators.yaml — 去掉省级关键词 + 加地域标签

**文件**: `news-monitor/config/macro_indicators.yaml`

**改动 1** — CPI 关键词收紧：
```yaml
# Before
- id: CPI
  tier: A
  keywords:
    - CPI
    - 消费者价格指数
    - 居民消费价格        # ← 裸匹配，广东/北京/上海全中
    - consumer price index
    - inflation data
    - 通胀数据
    - 通货膨胀

# After
- id: CPI
  tier: A
  keywords:
    - CPI
    - 消费者价格指数
    - 全国居民消费价格      # 只匹配全国级
    - consumer price index
    - inflation data
    - 通胀数据
    - 通货膨胀
    - US CPI
    - 美国 CPI
```

**改动 2** — 宏观指标整体加 `geo_tiers` 字段（新增）：
```yaml
# 在文件顶部新增全局地域规则（所有指标通用）
geo_tiers:
  t1:  # 美国
    patterns: ['美国', 'US\b', 'Fed', '美联储', 'U.S.', 'Wall Street']
    weight: 1.0
  t2:  # 欧洲 + 日本
    patterns: ['欧元区', '欧盟', '欧洲央行', 'ECB', '英国', 'BOE', '英格兰银行',
               '日本', '日银', 'BOJ', '日本央行', '德国', '法国', '意大利']
    weight: 0.85
  t3:  # 中国全国(非省级) + 韩国
    patterns: ['中国(?!省|市)', '央行(?!分行)', '国家统计局', '国务院',
               '韩国', '韩国央行', 'BOK', '韩国统计厅']
    weight: 0.7
  exclude:  # 不构成宏观催化剂
    # 原则：不在 T1/T2/T3 列表中的 = 排除。以下为常见命中示例，非穷举。
    # 中国省级/市级
    patterns: ['省(?!级)', '市(?!级)', '区(?!块链)', '广东', '北京', '上海',
               '深圳', '广州', '浙江', '江苏', '山东', '四川', '湖北',
               '河南', '河北', '湖南', '福建', '安徽', '辽宁',
               # 东南亚
               '马来西亚', 'Malaysia', '印尼', 'Indonesia', '泰国', 'Thailand',
               '越南', 'Vietnam', '菲律宾', 'Philippines', '新加坡', 'Singapore',
               # 南亚
               '印度', 'India', '巴基斯坦', 'Pakistan',
               # 拉美
               '巴西', 'Brazil', '墨西哥', 'Mexico', '阿根廷', 'Argentina',
               # 中东/非洲
               '土耳其', 'Turkey', '沙特', 'Saudi', '阿联酋', 'UAE', '南非', 'South Africa',
               # 其他常见非核心经济体
               '澳大利亚', 'Australia', '新西兰', 'New Zealand', '加拿大', 'Canada',
               '俄罗斯', 'Russia', '台湾', 'Taiwan', '香港', 'Hong Kong']
```

> ⚠️ 上述 exclude 列表是非穷举示例。代码实现应遵循「不在 T1/T2/T3 中 = 排除」的默认拒绝原则，而非依赖穷举列表。

**影响**: 
- 省级 CPI 不匹配任何白名单关键词 → 走正常去重
- 即使后续阶段仍用到此配置，T3 权重 ×0.7 会拉低最终分数

---

### P1: dispatch.py — TG 频道加主题去重

**文件**: `news-monitor/pipeline/dispatch.py`

**现状**（第 173 行）:
```python
if channel.name == "pushover" and level != AlertLevel.CRITICAL:
    skip, reason = self._phone_should_skip(item)
```

**改为**: 扩展主题去重到 TG 通道：
```python
# Pushover 去重（保持不变）
if channel.name == "pushover" and level != AlertLevel.CRITICAL:
    skip, reason = self._phone_should_skip(item)

# TG 宏观主题去重（新增）
if channel.name == "telegram":
    tg_key = self._tg_macro_topic_key(item)
    if tg_key and tg_key in self._tg_sent_macro_topics:
        log.info(f"TG skip: macro topic {tg_key} already sent in window")
        continue
    if tg_key:
        self._tg_sent_macro_topics.add(tg_key)
```

**新增方法** `_tg_macro_topic_key()`:
```python
def _tg_macro_topic_key(self, item) -> str | None:
    """为宏观新闻生成 TG 去重 key，2 小时窗口内同主题只推一次。"""
    from datetime import timedelta
    now = datetime.now()
    # 清理过期 key（>2h）
    expired = [k for k, ts in self._tg_sent_macro_topics.items() if now - ts > timedelta(hours=2)]
    for k in expired:
        del self._tg_sent_macro_topics[k]
    
    # 复用 _MACRO_TOPIC_PATTERNS
    for pattern, label in self._MACRO_TOPIC_PATTERNS:
        if re.search(pattern, item.headline or ""):
            return f"macro:{label}"
    return None
```

**TG 窗口**: 2 小时（vs 手机 6 小时），TG 是静音通道，容忍度更高。

---

### P2: event_driven_v1.txt — LLM Prompt 加地域分级指令

**文件**: `news-monitor/config/prompts/event_driven_v1.txt`

**现状**（第 13-14 行）:
```
重要宏观数据发布（CPI/PPI/PCE/非农/失业率/GDP/美联储利率决议/ISM PMI/零售销售）：
这些数据**直接驱动利率预期和增长前景**...必须识别为相关事件
```

**替换为**:
```
宏观催化剂地域分级（严格执行）：

T1 美国 — 权重 1.0，全球定价锚：
  - 美国 CPI/PPI/PCE/非农/失业率/GDP/零售销售/ISM PMI/密歇根消费者信心
  - FOMC 利率决议、美联储官员讲话、JOLTS 职位空缺

T2 欧洲+日本 — 权重 0.85，影响区域+外汇：
  - 欧元区 CPI/GDP/PMI、ECB 利率决议、英国 CPI/BOE 决议
  - 日本 CPI/GDP/BOJ 决议/短观报告

T3 中国全国+韩国 — 权重 0.7，影响港股/A股/韩股：
  - 中国全国级 CPI/PPI/GDP/PMI/社融/LPR（国家统计局/央行发布，非省级）
  - 韩国 GDP/CPI/BOK 利率决议

排除（不构成宏观催化剂，is_event=false）：
  - 中国省级/市级数据（如"广东CPI""北京PPI""上海GDP"）
  - 其他国家/地区数据
  - 标题含省/市名称 + 经济指标 → 必是排除项

判断方法：先看标题有没有地域限定词（省/市/美国/欧元区等），再决定归入哪级。
不确定时就往低处归。宁可漏推省级数据，不可把省级当全国推。
```

**影响**: LLM 有明确的地域分级指南，省级数据会被正确打 `is_event=false`。

---

### P3: evaluate.py — 地域权重乘入评分（如果实现了 geo_tiers 配置）

**文件**: `news-monitor/pipeline/evaluate.py` (或评分逻辑所在文件)

**新增逻辑**（在 LLM 评分之后，推送决策之前）:
```python
def _apply_geo_weight(self, item, base_score: float) -> float:
    """根据宏观新闻的地域级别调整分数。"""
    geo_tier = self._classify_geo_tier(item.headline or "")
    weights = {"t1": 1.0, "t2": 0.85, "t3": 0.7}
    weight = weights.get(geo_tier, 1.0)  # 未识别的不降权（保守）
    
    if geo_tier == "t3":
        # T3 不推手机，只走 TG
        item.max_channel = "telegram"
    
    return base_score * weight

def _classify_geo_tier(self, headline: str) -> str | None:
    """从标题中识别宏观新闻的地域级别。"""
    import re
    # 先检查排除项（省级/市级）
    province_patterns = r'广东|北京|上海|深圳|广州|浙江|江苏|山东|四川|湖北|河南|河北|湖南|福建|安徽|辽宁|重庆|天津|省|市'
    # 注意：只匹配独立的地名，不匹配"广东省政府发布全国数据"这种
    
    if re.search(r'(?:' + province_patterns + r')(?!.*全国)', headline):
        return None  # 省级，不适用宏观评分
    
    if re.search(r'美国|US\b|Fed|美联储', headline):
        return "t1"
    if re.search(r'欧元区|欧盟|ECB|欧洲央行|英国|BOE|日本|日银|BOJ', headline):
        return "t2"
    if re.search(r'中国(?!省|市)|央行|国家统计局|国务院|韩国|BOK', headline):
        return "t3"
    
    return None  # 无法判断，不降权
```

**注意**: P3 是锦上添花——P0+P1+P2 已经能解决问题。如果 P0 geo_tiers 配置和 P2 LLM prompt 生效，P3 可以不急着做。

---

## 优先级总结

| 优先级 | 改动 | 文件 | 行数 | 效果 |
|--------|------|------|:---:|------|
| 🔴 P0 | CPI 关键词收紧 + 新增 geo_tiers 配置 | `macro_indicators.yaml` | ~30 行 | 源头阻断省级数据进白名单 |
| 🟡 P1 | TG 加 2h 宏观主题去重 | `dispatch.py` | ~25 行 | 即使漏了也不刷屏 |
| 🟡 P2 | Prompt 加三级地域指令 | `event_driven_v1.txt` | ~25 行 | LLM 语义兜底，正确分类 |
| 🟢 P3 | 评分乘地域权重 | `evaluate.py` | ~30 行 | 代码层硬兜底（可选） |

P0+P1+P2 即可闭环，P3 是额外保险。

## 验证

- [ ] 省级 CPI（"广东居民消费价格同比上涨2.1%"）→ 不进白名单，不推
- [ ] 非核心国家宏观（"Malaysia GDP grows 5.8%"）→ 不进白名单，不推
- [ ] 印度/巴西/土耳其/印尼等宏观新闻 → 不进白名单，不推
- [ ] T3 中国全国 CPI（"中国6月CPI同比上涨2.5%"）→ 正常推送 TG
- [ ] T1 美国 CPI（"US CPI rises 3.2%"）→ 正常推送 TG + 可能推手机
- [ ] T2 日本 CPI（"日本6月全国CPI同比上涨3.1%"）→ 正常推送 TG
- [ ] TG 同主题 2h 内不重复
