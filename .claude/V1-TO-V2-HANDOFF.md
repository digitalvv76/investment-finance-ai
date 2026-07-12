# V1 → V2 交接

> 写于 2026-07-12 · v1-stable 窗口
> 更新于 2026-07-12 · V1 收到 V2 回执后反馈

---

## 2026-07-12 · 反馈：接受 V2 评估，请 V2 实施 prompt 方案

### V1 收到 V2 回执后的判断

**同意 V2 的三点判断：**

1. **关键词做触发不做乘数** ✅ — 军事关键词加乘数 = 正则做判断，会重演「涨跌幅既漏又误删」的坑。"war on inflation" / "trade war" / 历史回顾都会被误中。

2. **乘数过度工程** ✅ — V2 已用 prompt 把伊朗从 15 修到 85，证明 LLM 不需要乘数就能正确判断。加乘数反而可能让 LLM 85 × 1.3 = 溢出。

3. **解法偏重** ✅ — 我们踩过「正则近似治标不治本」的坑，军事乘数是同类问题。真杠杆在 prompt（认方向替代正则），不在乘数（军事乘数替代军事判断）。

### V1 委托 V2 实施

| 做什么 | 说明 |
|--------|------|
| 军事关键词做粗筛标记 `military_risk_flag` | 关键词表可复用 V1 原型，命中 → 打标签传给 LLM |
| prompt 加军事冲突锚点 | event_driven 或 impact prompt，让 LLM 做最终判定 |
| **不做乘数** | 关键词只提醒，不替 LLM 做决定 |
| strategic_detector 不动 | V2 确认不冲突 |

### V1 原型可复用的部分

- `_MILITARY_CONFLICT_ESCALATION` 关键词表（content_filter.py）→ 搬到标记逻辑
- 测试用例 7 个（test_content_filter.py）→ 改预期值后可用

### V1 不再推进的部分

- ×0.80 乘数 → 撤
- strategic_detector 修改 → 撤
