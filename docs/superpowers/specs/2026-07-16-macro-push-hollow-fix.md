# MacroAgent 推送内容空洞修复 — V1 诊断 → V2 实现

> 状态: V1 诊断完成，待 V2 实施 | 日期: 2026-07-16

## 诊断结论

宏观事件（CPI、FOMC、GDP、NFP 等）推送手机上只有标题+分数，没有分析师正文。根因在 `evaluate.py` 救援舱路径丢弃了 `impact` 评估结果的 `analyst_note` 和 `flash_note`。

## 根因：一条代码路径

宏观事件走的是三条评估路径中的「救援舱」：

```
EventDrivenEvaluator 评估 → "no catalyst triggered"（5 种催化剂全是股票向）
  → 回退到 ImpactEvaluator → 正常产出 flash_note + analyst_note ✅
  → impact_score ≥ 80 触发 rescue
  → DispatchDecision 只从 event_assessment 取字段 ❌
  → impact 的 flash_note / analyst_note 被丢弃
  → 推送空洞
```

**问题位置**：`news-monitor/pipeline/evaluate.py:141-151`

```python
# Site 1 — 救援舱 DispatchDecision 构造，缺少 analyst_note / flash_note
item.decision = DispatchDecision(
    alert_level=level,
    alert_reason=reason,
    filter_reason=event_assessment.filter_reason,
    headline_signal=event_assessment.headline_signal,   # ← 全从 ea 取
    risk_snapshot=event_assessment.risk_snapshot,
    event_types=event_assessment.event_types,
    intensity=event_assessment.intensity,
    sector_tags=event_assessment.sector_tags,
    ticker_hint=event_assessment.ticker_hint,
    # ❌ 缺 analyst_note, flash_note, impact_score, urgency 等
)
```

对比同文件 Site 2（`evaluate.py:216-244`），正常路径正确提取了这些字段：

```python
# Site 2 — 正常路径，正确提取
flash_note = str(getattr(impact, "flash_note", "") or "")
analyst_note = str(getattr(impact, "analyst_note", "") or "")
...
item.decision = DispatchDecision(
    ...
    analyst_note=analyst_note,    # ✅
    flash_note=flash_note,        # ✅
    ...
)
```

## V2 实施方案

### 改动：`evaluate.py:141-151` — 救援舱补全字段

在 Site 1 的 `DispatchDecision()` 构造之前，从 `impact` 提取字段，对齐 Site 2：

**修改前**（行 141-151）：
```python
            item.decision = DispatchDecision(
                alert_level=level,
                alert_reason=reason,
                filter_reason=event_assessment.filter_reason,
                headline_signal=event_assessment.headline_signal,
                risk_snapshot=event_assessment.risk_snapshot,
                event_types=event_assessment.event_types,
                intensity=event_assessment.intensity,
                sector_tags=event_assessment.sector_tags,
                ticker_hint=event_assessment.ticker_hint,
            )
```

**修改后**：
```python
            # 从 impact 提取宏观评估结果（对齐 Site 2）
            flash_note = str(getattr(impact, "flash_note", "") or "")
            analyst_note = str(getattr(impact, "analyst_note", "") or "")
            impact_score = int(getattr(impact, "impact_score", 0) or 0)
            urgency = str(getattr(impact, "urgency", "") or "").upper()
            sentiment = str(getattr(impact, "sentiment", "") or "").upper()
            greed_index = int(getattr(impact, "greed_index", 50) or 50)
            key_points = str(getattr(impact, "key_points", "") or "")
            risk_flags = str(getattr(impact, "risk_flags", "") or "")
            event_category = str(getattr(impact, "event_category", "") or "")

            item.decision = DispatchDecision(
                alert_level=level,
                alert_reason=reason,
                impact_score=impact_score,
                urgency=urgency,
                sentiment=sentiment,
                greed_index=greed_index,
                filter_reason=event_assessment.filter_reason,
                headline_signal=event_assessment.headline_signal,
                risk_snapshot=event_assessment.risk_snapshot,
                event_types=event_assessment.event_types,
                intensity=event_assessment.intensity,
                sector_tags=event_assessment.sector_tags,
                ticker_hint=event_assessment.ticker_hint,
                analyst_note=analyst_note,
                flash_note=flash_note,
                key_points=key_points,
                risk_flags=risk_flags,
                event_category=event_category,
                needs_deep=(impact_score >= 60 or urgency in ("FLASH", "ALERT")),
            )
```

### 改动量

- **1 文件，~15 行新增**（字段提取 + 构造函数补参）
- `evaluate.py` 救援舱路径（行 141-151）

### 验证

- 部署后观察下一条 CPI/宏观新闻推送，确认手机和 TG 都有分析师正文（3-5 句中文 `flash_note`）
- 确认 `impact_score`、`urgency`、`key_points`、`risk_flags` 也在推送中正常展示

### 风险

- **极低**：只补字段不改变逻辑，Site 1 原本就是因 `event_assessment` 字段有限而漏传
- `getattr` 默认空字符串兜底，`impact` 为 None 也能安全降级
