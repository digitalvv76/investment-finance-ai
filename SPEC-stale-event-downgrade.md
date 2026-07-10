# SPEC：事件驱动推送 — 过期催化剂降级（stale-event downgrade）

> 类型：语义契约（§5 分工——V1 出规格，V2 在 main 流水线接线实现）
> 出处：V1 窗口（v1-stable）诊断 + 设计，2026-07-10
> 归属实现：**V2 / main**（改动 `pipeline/evaluate.py`，属 main 流水线）
> 用户已定阈值：**1 小时**（更狠版，非 2 小时）

---

## 1. 背景（为什么做）

用户手机收到推送：**"美光2500亿美元押注推动芯片复苏，但百事可乐和李维斯仍遭惩罚"**，反馈"不够格上手机"。

核实结论：
- 生产实时记录：`id=3340, level=important, silent=false, reason="event_driven: catalyst_types=[1] intensity=4"` → **确实响了手机**（IMPORTANT → `_pushover_high`）。
- 查证原文（[Micron 7/9 官方公告](https://www.globenewswire.com/de/news-release/2026/07/09/3324807/14450/en/micron-accelerates-u-s-investments-pours-first-concrete-at-new-york-fab.html)）：真事件、含 $6.1B CHIPS 拨款、MU 当天涨 7-9%。**LLM 判 intensity=4 站得住，不是误评。**
- **真正的问题（用户抓的点）**：这是**几小时前就已公开、市场早消化完**的催化剂。几小时后再满级震手机 = 无可操作价值。

## 2. 根因（已坐实）

`pipeline/evaluate.py :: EvaluateStage._apply_event_assessment()`（现约 212–262 行）把 LLM `intensity` **直接**映射成 alert level：

```python
if intensity >= 5:   level = CRITICAL
elif intensity >= 4: level = IMPORTANT
else:                level = IMPORTANT   # intensity 3
```

这条路径**只有多源"升级"（source_count≥3 → +1星），从不因"过期"降级**——完全不看新闻时效性。所以一条几小时前的旧催化剂照样满级上手机。**这是逻辑缺口。**

（对比：旧的 legacy 路径 Path B 有 `timeliness` 门禁 `TIMELINESS_PHONE_MIN=0.25`，但事件驱动 Path A 是 primary，绕过了它。）

## 3. 行为契约（要实现成什么样）

**新增一道"过期降级"闸，加在 `_apply_event_assessment` 里 intensity→level 映射之后、构建 `DispatchDecision` 之前：**

| 条件 | 结果 |
|------|------|
| 最终 level == **IMPORTANT**（intensity 3-4）且 事件线年龄 > **60 分钟** | **降级为 NOTABLE**（→ dispatch 判 silent=True → 静音 Telegram、**手机不响**） |
| level == **CRITICAL**（intensity 5） | **豁免**，永不降级（极稀有板块级，宁可震一下） |
| 事件线年龄未知（无 event_line / 查询失败 → None） | **保持原级别**（不惩罚缺失数据，与 `timeliness_factor` None→1.0 的哲学一致） |
| level == NOTABLE / NORMAL | 原样透传 |

**"事件线年龄"定义**：该新闻所属 `event_lines` 行的 `first_seen` 到"现在"的分钟数。语义 = "这件事我们系统首次见到它，到现在多久了" —— 精准对应用户说的"几小时前已被公开报告"。

**不需要对 `is_breaking` 特殊豁免**：年龄本身就是新鲜度度量。真突发 → 事件线刚建 → 年龄≈0 → 不会被降级；反之一条打着 BREAKING 标签、但我们 90 分钟前就见过的旧闻复述，就该降级。**用年龄，不用标签，才堵得住漏洞。**（这点比会话里最初说的"突发10分钟豁免"更干净——age<60min 已是其超集。）

## 4. 建议实现结构（便于 TDD；最终实现权归 V2）

**a) 纯函数（模块级，仿 `event_driven_evaluator.watchlist_safety_net` 的可测风格）：**

```python
STALE_EVENT_MINUTES = 60  # 事件公开 > 1h → 已 price in，手机降静音TG

def _downgrade_if_stale(level: AlertLevel, age_minutes: float | None) -> AlertLevel:
    """IMPORTANT 且事件线年龄 > STALE_EVENT_MINUTES → NOTABLE（静音TG，不响手机）。
    CRITICAL 豁免；age 未知(None)→保持。纯函数，无副作用。"""
    if (level == AlertLevel.IMPORTANT
            and age_minutes is not None
            and age_minutes > STALE_EVENT_MINUTES):
        return AlertLevel.NOTABLE
    return level
```

**b) DB 助手（仿现有 `_get_event_source_count`）：**

```python
def _event_line_age_minutes(self, news_id: int) -> float | None:
    if not self._db or not news_id:
        return None
    try:
        with self._db._get_conn() as conn:
            row = conn.execute(
                """SELECT (julianday('now','localtime')
                           - julianday(datetime(el.first_seen))) * 1440.0 AS age_min
                   FROM event_lines el JOIN news n ON n.event_line_id = el.id
                   WHERE n.id = ? AND el.is_active = 1""",
                (news_id,),
            ).fetchone()
            if row and row["age_min"] is not None:
                return max(float(row["age_min"]), 0.0)
            return None
    except Exception:
        return None
```

**c) 接线（在 level 定完之后插入）：**

```python
age_min = self._event_line_age_minutes(item.id) if item.id else None
new_level = _downgrade_if_stale(level, age_min)
if new_level != level:
    logger.info("EVALUATE: stale event #%d (age=%.0fmin>%d) IMPORTANT→NOTABLE 静音TG: %s",
                item.id, age_min or 0, STALE_EVENT_MINUTES, (item.title or "")[:60])
    reason += f" | stale_downgrade(age={age_min:.0f}min)"
    level = new_level
```

**可选精修（非必须）**：降级时把 `needs_deep` 设为 False，省掉对旧闻的深度分析 LLM 调用。为保持 diff 最小可暂不做。

## 5. ⚠️ 时区陷阱（必读，否则年龄算错、降级乱触发）

`event_lines.first_seen` 由 **`cluster.py:206` 的 `datetime.now()`** 写入 = **本地时间（naive）**，且 Python 3.12 isoformat 适配器存成 **`T` 分隔符**（如 `2026-07-10T14:30:00`）。

这正是上次**看门狗 STALLED 误报**的同款坑（本地时间 + T 分隔符 + UTC `now` 比较 → 窗口失效）。修法同 `get_recent_news`：
- **"now" 必须本地**：`julianday('now','localtime')`。
- **`first_seen` 必须 `datetime()` 包裹**：兼容 T / 空格两种分隔符。
- 上面 4.b 的 SQL 已按此写好，直接用即可。

## 6. 测试用例（TDD，先红后绿；测试禁用真实推送凭证）

纯函数 `_downgrade_if_stale`：

| # | 输入 | 期望 | 说明 |
|---|------|------|------|
| 1 | IMPORTANT, age=90 | **NOTABLE** | 主 bug 场景（美光这条） |
| 2 | IMPORTANT, age=30 | IMPORTANT | 新鲜，照响手机 |
| 3 | IMPORTANT, age=None | IMPORTANT | 未知年龄不惩罚 |
| 4 | CRITICAL, age=999 | CRITICAL | intensity-5 豁免 |
| 5 | NOTABLE, age=999 | NOTABLE | 非 IMPORTANT 透传 |
| 6 | IMPORTANT, age=60 | IMPORTANT | 边界（>60 才降，=60 不降） |

（建议再加一条集成测试：塞一条 `first_seen` 为 90 分钟前的 event_line + 关联 news，跑 `_apply_event_assessment`，断言 decision.alert_level==NOTABLE。用真实 SQLite 临时库验证时区 SQL 正确。）

新增 `tests/test_stale_event_downgrade.py`；在 `config/module_registry.json` 里把它挂到 `pipeline/evaluate.py` 的 `tests`（注意：该 JSON 用 UTF-8，Windows 上 `open()` 需显式 `encoding='utf-8'`，否则 GBK 报错）。

## 7. 部署 & 回滚（§1 / §1b）

1. 本地 TDD 绿 + registry-mapped 测试全绿。
2. **对抗式核实子 agent**：确认不误伤"当天真突发"（quality-gate 要求）。
3. `deploy-shadow.sh` 影子容器试跑，对比降级是否只命中旧闻。
4. 部署前打回滚 tag：`docker tag docker-news-monitor docker-news-monitor:rollback-pre-staledowngrade`。
5. `git push origin main` → ECS `git fetch && checkout origin/main -- <文件> && rebuild`。

## 8. 与"推送偏少"待办的关系（别打架）

SESSION #3 的老问题是"推送**偏少**"。本改动**不冲突**：它只砍"过期旧闻"这一类**低价值噪音**，**完全不碰新鲜催化剂**。净效果是**提纯**信号，不是收紧闸门。

---
**交接完成。** V1 侧诊断+设计+排雷已做完；实现/测试/部署归 V2。有疑问回本 SPEC 或 v1-stable SESSION。
