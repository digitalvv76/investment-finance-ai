---
name: wiki-compile
description: >-
  将已完成的研究报告蒸馏为 wiki 知识页。触发：compile wiki, update wiki, wiki update,
  更新wiki, wiki编译, write wiki, 编译wiki.
metadata:
  type: project
  triggers:
    - compile wiki
    - update wiki
    - wiki update
    - 更新wiki
    - wiki编译
    - write wiki
    - 编译wiki
    - wiki compile
---

# wiki-compile — Wiki 页面编译

将已完成的深度研究报告蒸馏为结构化 wiki 页面。纯蒸馏，不取新数据。

## 工作流

### Step 1: 读规范
读取 `wiki/SCHEMA.md`，确认当前页面格式要求。

### Step 2: 读源报告
读取用户指定的研究报告（通常在 `data/reports/` 下），或用户直接给的分析内容。源报告必须已经完成——本 skill 不做新分析。

### Step 3: 读已有页面（如果是更新）
如果 `wiki/<TICKER|topic>.md` 已存在，先读已有内容，保留仍有价值的 Tier 3 深度段，只更新过时的 Tier 2 压缩上下文。

### Step 4: 提取 Tier 2（压缩上下文）
从源报告提取五段核心内容，目标 ~1500 tokens：
- **Thesis**: 3-5 句投资逻辑
- **Key Metrics**: 关键指标表（价格、PE、市值等——从源报告取数）
- **Stance**: BUY/HOLD/SELL + 一行理由
- **Catalysts**: 未来催化剂清单
- **Risks**: 关键风险 top 3

### Step 5: 写 Tier 3（完整正文，可选）
如果源报告内容充足，按页面 type 扩写深度段：
- stock: 公司概览、技术面、基本面、估值框架、风险登记表、催化剂时间线、反向观点
- macro: 政策路径、指标趋势、市场含义、板块影响

### Step 6: 写页面
写入 `wiki/<TICKER|topic>.md`：
1. YAML frontmatter（严格按 SCHEMA.md）
2. Tier 2 五段
3. Tier 3 深度段（如有）
4. 末尾 `---` + 源报告链接

### Step 7: 更新索引
如果新增页面，在 `wiki/INDEX.md` 表格加一行。如果是更新已有页面，更新 `updated` 日期。

## 质量规则

1. **不捏造**：所有数据和判断必须可追溯到源报告。不确定就写「信息不足」。
2. **中文主体**：投资内容用中文，英文术语保留。
3. **日期诚实**：`updated` = 源报告日期或实际编译日期。
4. **立场明确**：Stance 三选一，不模糊。
5. **源可追溯**：sources 字段必须列出实际文件路径。

## 输出示例

```
---
ticker: NVDA
type: stock
status: active
confidence: high
updated: 2026-07-01
sources:
  - data/reports/NVDA-2026-07-01.md
tags: [ai, semiconductor]
---

# NVDA (NVIDIA) — AI 算力垄断者

## Thesis
...
```
