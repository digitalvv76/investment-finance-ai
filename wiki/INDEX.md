---
type: index
updated: 2026-07-14
---

# Wiki 索引

> LLM Wiki 导航中枢。每个 wiki 页面都必须在此列出。`wiki-maintain` skill 自动维护。

## 全部页面

| 页面 | 类型 | 状态 | 置信度 | 更新 | 核心论题 |
|------|------|------|--------|------|----------|
| [[NVDA]] | stock | active | high | 2026-07-01 | AI GPU 垄断，PEG 0.59 低估，恐惧=买点 |
| [[PLTR]] | stock | active | medium | 2026-07-16 | 业务改善+宏观转鸽，但内幕卖出+极端估值，HOLD |
| [[fed-policy]] | macro | active | high | 2026-07-01 | 降息暂停 6.5 月，CPI 再加速，Warsh 时代 |

## 按类型

### Stock
- [[NVDA]] — BUY，AI 算力垄断
- [[PLTR]] — HOLD，国防 AI + 内幕疑虑

### Macro
- [[fed-policy]] — 利率路径 + 通胀 + FOMC

### Crypto
（暂无）

### Strategy
（暂无）

### Sector
（暂无）

## 过期页面（>90 天未更新）

（暂无）

---

## 维护说明

运行 `wiki-maintain` skill 自动重建此索引：
- 扫描 `wiki/*.md`（排除 SCHEMA.md 和本文件）
- 验证每页 frontmatter 完整
- 检测 >90 天未更新 → 移入「过期页面」区
- 交叉引用 `data/reports/ARCHIVE.md`
