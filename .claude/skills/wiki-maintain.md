---
name: wiki-maintain
description: >-
  Wiki 索引维护与一致性检查。扫描页面、验证格式、重建 INDEX.md、标记过期页。
  触发：wiki index, wiki check, wiki维护, wiki索引, wiki housekeeping, rebuild index.
metadata:
  type: project
  triggers:
    - wiki index
    - wiki check
    - wiki维护
    - wiki索引
    - wiki housekeeping
    - rebuild index
    - wiki maintain
---

# wiki-maintain — Wiki 维护

保持 wiki 可导航、一致、新鲜。重建索引、标记过期页、验证格式。

## 工作流

### Step 1: 扫描页面
列出 `wiki/*.md`，排除 `SCHEMA.md` 和 `INDEX.md`。提取每页的 YAML frontmatter。

### Step 2: 验证格式
逐页检查是否符合 `wiki/SCHEMA.md`：
- [ ] frontmatter 字段完整（ticker/topic, type, status, confidence, updated, sources）
- [ ] type 值在允许范围内
- [ ] status 值在允许范围内
- [ ] updated 是有效日期格式
- [ ] sources 至少一条且文件存在
- [ ] Tier 2 五段齐全（Thesis, Key Metrics, Stance, Catalysts, Risks）

发现问题列出文件名 + 具体问题，不自动修（除非用户明确要求）。

### Step 3: 检测过期
`updated` > 90 天的页面 → 列出，建议：
- 如果投资逻辑仍然成立 → 更新 `updated` 日期
- 如果已过时 → 将 `status` 改为 `archived` 并移至过期区

### Step 4: 重建索引
重写 `wiki/INDEX.md`：
1. 保留 frontmatter（更新 `updated` 日期）
2. 「全部页面」表格：从每页 frontmatter 提取字段
3. 「按类型」分组：stock / macro / crypto / strategy / sector
4. 「过期页面」区：>90 天未更新的页面
5. 「维护说明」保留不变

### Step 5: 交叉引用
读取 `data/reports/ARCHIVE.md`（如存在），列出**有研究报告但无 wiki 页面**的标的，提示可编译。

### Step 6: 报告摘要
```
✅ {N} 页健康 | ⚠️ {N} 页过期 | ❌ {N} 页格式问题

过期页:
  - {PAGE} — {N} 天未更新，最后立场 {STANCE}

格式问题:
  - {PAGE} — 缺少 frontmatter 字段 {FIELD}

待编译 (有报告无 wiki):
  - {TICKER} — {REPORT_PATH}
```

## 规则

1. **不删页面**：过期页改 `status: archived`，永不删除
2. **INDEX.md 是重建的**：每次运行完全重写，不增量更新
3. **格式问题先报告**：不自动修复（可能改错）
4. **中文报告**
