# Wiki 页面格式规范

> 本文件是 wiki 页面的格式标准。所有 wiki 页面必须遵循此规范，确保 LLM 和人类都能可靠地读写。

## Frontmatter（必填）

每个 wiki 页面必须以 YAML frontmatter 开头：

```yaml
---
ticker: NVDA                              # 股票代码；非股票页用 topic: fed-policy
type: stock                               # stock | macro | crypto | strategy | sector
status: active                            # active (活跃) | archived (归档) | stub (占位)
confidence: high                          # high | medium | low — 对当前判断的把握
updated: 2026-07-01                       # 最后更新日期 (YYYY-MM-DD)
sources:                                  # 来源报告，保证可追溯
  - data/reports/NVDA-2026-07-01.md
tags: [ai, semiconductor, large-cap]      # 可选，便于分类检索
---
```

### 字段约束

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `ticker` 或 `topic` | ✅ | 股票用 ticker，宏观/主题用 topic，二选一 |
| `type` | ✅ | stock / macro / crypto / strategy / sector |
| `status` | ✅ | active=当前有效 / archived=已过时但保留 / stub=待填充 |
| `confidence` | ✅ | high=多源验证 / medium=单源或分歧 / low=初步判断 |
| `updated` | ✅ | ISO 日期，内容实际更新时间（非自动填充） |
| `sources` | ✅ | 至少一条，指向已存在的研究报告 |
| `tags` | ❌ | 自由标签，数组 |

## 页面结构

### Tier 2 — 压缩上下文（必填，~1500 tokens 以内）

wiki-load 注入分析用的核心块。只需这五段：

```markdown
## Thesis
3-5 句话，一句话说清投资逻辑。不展开。

## Key Metrics
| 指标 | 数值 |
|------|------|
| 价格 | ... |
| PE | ... |
| 市值 | ... |

## Stance
**BUY** / **HOLD** / **SELL** — 一行立场，一行理由。

## Catalysts
- 催化剂 1
- 催化剂 2

## Risks
1. 风险 1
2. 风险 2
3. 风险 3
```

### Tier 3 — 完整正文（可选，深度参考时使用）

根据 `type` 不同，扩展示例段：

- **stock**：公司概览、技术面、基本面、估值框架、风险登记表、催化剂时间线、反向观点
- **macro**：政策路径历史、核心指标趋势、市场含义、板块影响、风险情景
- **crypto**：项目概述、代币经济学、链上数据、监管风险、技术面
- **sector**：板块定位、权重股、轮动信号、宏观敏感性
- **strategy**：策略逻辑、回测摘要、参数、适用条件、失效场景

## 链接约定

| 目标 | 格式 | 示例 |
|------|------|------|
| 同 wiki 内页面 | `[[PAGE]]` | `[[NVDA]]` 链接到 `wiki/NVDA.md` |
| 外部文件 | `[text](../path/to/file.md)` | `[源报告](../data/reports/NVDA-2026-07-01.md)` |

## 质量门禁

1. **不捏造**：所有数据和判断必须可追溯到 `sources` 中的报告
2. **中文主体**：投资内容用中文，英文专有名词保留（PEG、RSI、FOMC 等）
3. **日期诚实**：`updated` 反映内容实际更新时间，非创建时间
4. **立场明确**：Stance 必须是 BUY/HOLD/SELL 三选一，不给模糊描述
5. **区分事实与判断**：数据是事实，评级是判断——说清楚哪个是哪个
6. **最小长度**：Tier 2 至少 200 字；纯 stub 不应进 wiki

## 示例

参见 `wiki/NVDA.md`（stock）、`wiki/PLTR.md`（stock）、`wiki/fed-policy.md`（macro）。
