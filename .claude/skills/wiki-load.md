---
name: wiki-load
description: >-
  分析前加载 wiki 已有知识，避免从零开始。纯只读，输出压缩上下文块注入分析 prompt。
  触发：load wiki, wiki context, wiki加载, 加载wiki, prior knowledge, wiki load.
metadata:
  type: project
  triggers:
    - load wiki
    - wiki context
    - wiki加载
    - 加载wiki
    - prior knowledge
    - wiki load
---

# wiki-load — Wiki 知识加载

在开始新的 stock-research 或 deep-research 之前，加载已有 wiki 页面作为先验知识。纯只读，不修改任何文件。

## 工作流

### Step 1: 查索引
读取 `wiki/INDEX.md`，找到目标 ticker 或 topic 的页面路径。

如果页面不存在：输出「wiki: 无已有知识」→ 继续正常分析。

### Step 2: 读 Tier 2
读取 `wiki/<TICKER|topic>.md` 的 frontmatter + Tier 2（Thesis / Key Metrics / Stance / Catalysts / Risks）。

如果页面 `status: archived` 或 `confidence: low`，在输出中加醒目警告。

### Step 3: 检查新鲜度
- 页面 `updated` > 90 天 → 输出标记 `⚠️ 页面已过期（N 天前），先验知识可能过时`
- `confidence: low` → 输出标记 `⚠️ 低置信度，先验知识仅供参考`

### Step 4: 输出压缩块
输出一个紧凑的 markdown 块（~300-500 tokens），可直接注入新分析 prompt：

```markdown
## 📚 Wiki 先验知识：{TICKER}

**上次立场**: BUY (2026-07-01, confidence: high)
**核心论题**: 一句话 thesis
**关键数据**: 价格 $X | PE X | 市值 $X
**活跃催化剂**: xxx
**关键风险**: xxx, xxx

> 上次分析报告: `data/reports/{TICKER}-{date}.md`
```

## 集成建议

在 stock-research 或 deep-research 分析前，自动调用本 skill 加载 wiki 上下文。输出块应插入分析 prompt 的「已有知识」段，让 LLM 知道上次怎么判断的，但不替代本次独立分析。

## 规则

1. **纯只读**：不修改 wiki 文件，不修改 INDEX.md
2. **标明新鲜度**：过期或低置信度页面必须标记
3. **不替代分析**：先验知识是参考，不是答案——新分析必须独立判断
4. **Token 控制**：输出压缩块不超过 500 tokens
