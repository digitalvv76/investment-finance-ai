# 手机推送门槛调高 + 同主题去重增强 — V1 需求 → V2 实施

> 状态: V1 需求确认，待 V2 实施 | 日期: 2026-07-16

## 背景

用户反馈手机推送偏多。当前 ALERT 级别门槛太宽（财报>10%、并购>$10B、宏观>2σ、FDA、监管），导致每周多次震动。另一问题：中英文管道同时采集同一事件（台积电/TSM、英伟达机器人），同主题去重因 ticker 映射不完整而漏拦。

## 需求 1：调高手机推送门槛

### 现行逻辑

| 级别 | 触发条件 | 手机 |
|------|----------|:---:|
| FLASH | 战争、军事打击、紧急央行、主权违约 | 🔔 紧急 |
| ALERT | 财报>10%、并购>$10B、FDA、宏观>2σ、地缘升级 | 🔔 高优 |
| WATCH/INFO | 常规事件 | ❌ |

### 改动：ALERT 加手机限制

`alert_dispatcher.py` 的 `dispatch()` 方法，在 ALERT 分支（行 323-339）加 `phone_blocked` 判断：

```python
elif level == AlertLevel.IMPORTANT:
    # NEW: phone push only for watchlist stocks OR macro shock ≥85
    is_phone_worthy = (
        rel_mult > 0.5  # user's watchlist/portfolio
        or (is_macro and impact_assessment is not None 
            and int(getattr(impact_assessment, "impact_score", 0) or 0) >= 85)
    )
    
    if phone_blocked or not is_phone_worthy:
        # TG alert only, skip phone
        ...
    else:
        # push to phone (existing logic)
        ...
```

### 效果

| 场景 | 改前 | 改后 |
|------|:---:|:---:|
| 关注股财报 beat >10% | 🔔 手机 | 🔔 手机 |
| 非关注股财报 beat >10% | 🔔 手机 | ❌ TG 提醒 |
| 非关注股并购 >$10B | 🔔 手机 | ❌ TG 提醒 |
| 宏观 CPI 85 分 | 🔔 手机 | 🔔 手机 |
| 宏观 CPI 75 分 | 🔔 手机 | ❌ TG 提醒 |
| FDA / 常规监管 | 🔔 手机 | ❌ TG 提醒 |
| **战略事件 (政府入股/NVDA)** | 🔔 紧急 | 🔔 紧急 **不变** |

### 不改动

- FLASH → 手机紧急，维持不变
- 战略事件 (gov_intervention / nvda_*) → CRITICAL，独立路径，不受影响
- TG → 全量接收不变

---

## 需求 2：同主题去重增强

### 现行逻辑 (`ee9b671`)

6h 窗口内同主题只推第一条到手机，TG 不去重。去重键基于 `ticker_hint` 或 `macro_topic`。

### 漏洞

中文实体提取的 `_cn_company_to_ticker` 映射不完整，"台积电"可能不映射到 TSM，导致同一事件中英文新闻生成不同去重键 → 双双上手机。

### 改动：`dispatch.py` 的 `_dedup_key()` 增强

```python
# 在 ticker 匹配失败后，加一个 headline 相似度 fallback：
#   1. ticker 键优先（现有逻辑）
#   2. macro topic 兜底（现有逻辑）
#   3. NEW: headline_signal 相似度 fallback —
#      对已记录的键逐个做 embedding cosine similarity，
#      若 ≥ 0.85 则复用已有键，视为同主题
```

### 同步联动

补全 `entity_extractor.py` 的 `_cn_company_to_ticker` 映射表，至少加：

```python
"台积电": "TSM",
"台积": "TSM",  
"腾讯": "TCEHY",
# ... 覆盖常用中英文不一致的公司名
```

---

## 改动量估算

| 文件 | 改动 |
|------|------|
| `alert_dispatcher.py` | ~15 行，ALERT 分支加 `is_phone_worthy` 判断 |
| `dispatch.py` | ~20 行，`_dedup_key()` 加 headline similarity fallback |
| `entity_extractor.py` | ~15 行，补 `_cn_company_to_ticker` 映射 |

**3 文件，~50 行**

## 验证

- 部署后观察 3 天：手机推送数量预期降 50-70%
- 关注股事件仍震手机
- 同一事件中英文源只推一次到手机
