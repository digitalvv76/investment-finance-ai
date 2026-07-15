# MacroAgent — 宏观新闻独立评估子 Agent

> 设计日期: 2026-07-15 | 状态: 待 V2 实施 | V1 设计 → V2 实现

## 问题

当前系统把宏观新闻和个股催化剂放在同一条管道（去重 → Screen(0.15) → EventDrivenEval）评估。宏观新闻的 priority_score 天然低（不含 ticker），容易被 Screen 筛掉或在去重阶段被相似标题误杀。2026-07-15 PPI 数据好于预期但未推送，根因是被去重判定为 Finnhub PPI 预告的重复。

## 方案

在管道中新增 MacroAgent 阶段，位于 Ingest(去重) 之后、Screen 之前。宏观新闻被独立检测和评估，不经过 Screen 和 EventDrivenEval。

## 架构

```
采集 → Ingest(去重) → MacroAgent ─┬─ 宏观+推 → Dispatch（跳过 Screen/Evaluate）
                                  ├─ 宏观+不推 → NORMAL（不推送）
                                  └─ 非宏观 → Screen → Evaluate → Dispatch（现有路径）
```

**铁律**：MacroAgent 无法判定时默认「放过」——LLM 失败、JSON 解析失败、超时 → 透传给 Screen，不影响非宏观新闻的正常管道。

## 宏观检测（不依赖 LLM）

两层规则：

1. **标题白名单命中**：配置在 `config/macro_indicators.yaml`，每个指标包含中英文变体关键词 + Tier
2. **白名单未命中** → 判为非宏观，透传给 Screen

不依赖 LLM 做检测，因为每条 99% 不是宏观，LLM 全量调用成本过高。

## 指标分级

| Tier | 指标 | 评估方式 |
|------|------|---------|
| A | CPI、FOMC 利率决议、非农、美联储主席证词/讲话 | 数据类：偏离 σ / Fed 类：LLM 定性 |
| B | PPI、零售销售、GDP、FOMC 会议纪要 | 数据类：偏离 σ / Fed 类：LLM 定性 |
| C | PMI、消费者信心、其他联储官员讲话 | 同上 |

## 推送矩阵

| Tier | 轻微偏离 | 显著偏离 | 极端偏离 |
|------|---------|---------|---------|
| **A** | NOTABLE (TG 静音) | **IMPORTANT (手机)** | **IMPORTANT (手机 high)** |
| **B** | NORMAL (跳过) | NOTABLE (TG 静音) | **IMPORTANT (手机)** |
| **C** | NORMAL (跳过) | NORMAL (跳过) | NOTABLE (TG 静音) |

偏离定义（数据类）：
- 轻微：estimated < 0.5σ（实际 vs 共识偏离小）
- 显著：0.5σ ≤ deviation < 1.5σ
- 极端：deviation ≥ 1.5σ

偏离定义（Fed 类，LLM 定性）：
- 轻微：略偏鹰/鸽，基本符合市场预期
- 显著：明显偏鹰/鸽，超出多数人预期
- 极端：大幅超预期（如突然加息 50bp 或意外降息）

## LLM Prompt 结构

模板位置：`config/prompts/macro_eval.txt`

### 输入

新闻标题 + 内容摘要（前 1200 字）

### 评估步骤

1. **提取**：指标名称、Tier、实际值、共识预期值（有数字的）；Fed 类提取「实际决议/措辞」和「市场预期」
2. **判偏离**：对比实际 vs 预期，判定 轻微/显著/极端
3. **查矩阵**：Tier × 偏离 → alert_level
4. **生成 headline_signal**：含实际数字和预期对比（如「6月CPI同比+3.5%，超市场预期3.2%，核心CPI同步回落」）
5. **写出 risk_snapshot**：一句话风险提示（如「若核心CPI粘性超预期，可能推迟降息时点」）

### 降级规则（Prompt 内处理）

- 标题含"预览/前瞻/eye/expect/anticipate/ahead/will watch"等预告词 → `is_macro=false`，等实际数据发布
- 距离发布时间 > 24h 的不再是新发布

### 输出格式

```json
{
  "is_macro": true,
  "indicator": "CPI",
  "tier": "A",
  "actual": "3.5%",
  "expected": "3.2%",
  "deviation": "significant",
  "alert_level": "important",
  "headline_signal": "6月CPI同比+3.5%，超市场预期3.2%，核心CPI同步回落至3.8%。通胀放缓趋势确认，但服务项仍具粘性。",
  "risk_snapshot": "核心CPI环比仍高——单月数据不足以推动FOMC转向，警惕后续讲话修正市场预期。"
}
```

## 代码集成

| 文件 | 动作 | 说明 |
|------|------|------|
| `engine/macro_agent.py` | 新增 | MacroAgent 类：检测+评估+LLM 调用 |
| `pipeline/macro.py` | 新增 | MacroStage：Pipeline Stage，插在 Ingest 之后 |
| `config/macro_indicators.yaml` | 新增 | 白名单关键词（指标名+Tier+中英文变体） |
| `config/prompts/macro_eval.txt` | 新增 | LLM prompt 模板 |
| `main.py` | 改 | Pipeline 插入 MacroStage |
| `config/module_registry.json` | 改 | 注册新模块 + 测试映射 |
| `engine/__manifest__.json` | 改 | 同步注册（[[two-manifest-tables-sync]]） |

LLM provider 复用 EventDrivenEvaluator 的 provider 获取方式（DeepSeek，temperature=0）。

## Pipeline 集成细节

MacroStage 位于 Ingest 之后，不能直接调用 Dispatch（Dispatch 在管道末端）。用标记位传递：

1. **MacroStage** → 判定宏观+推：设置 `item.decision`（alert_level、headline_signal 等）并标记 `item._macro_routed = True`
2. **ScreenStage** → 检测 `_macro_routed`，为 True 则直接透传
3. **EvaluateStage** → 检测 `_macro_routed`，为 True 则直接透传
4. **DispatchStage** → 照常处理（不管来源是 Macro 还是 EventDriven）

宏观判定不推（NORMAL）同样设 `_macro_routed=True` + `alert_level=NORMAL`，DispatchStage 跳过推送。

## 错误处理

| 场景 | 行为 |
|------|------|
| LLM 调用失败 | 透传给 Screen（不拦截） |
| JSON 解析失败 | 透传给 Screen |
| MacroAgent 超时 | 透传给 Screen |
| 白名单未命中 | 透传给 Screen（正常路径） |

默认行为永远是「放过」，只拦截明确判定的宏观新闻。

## 测试策略

| 测试类型 | 覆盖 | 条数估计 |
|---------|------|---------|
| 白名单检测 | 15 个指标 × 中英文变体 + 反例（非宏观标题） | ~25 |
| 偏离判定 | 轻微/显著/极端 × 数据类 + Fed 鹰/鸽 × 定性类 | ~8 |
| 矩阵路由 | Tier×偏离 9 个组合 → alert_level | ~9 |
| 降级兜底 | 预览/前瞻类标题 → is_macro=false | ~3 |
| 透传 | 非宏观新闻原样通过 | ~3 |
| **合计** | | **~48** |

验收：Playwright 端到端跑一次，确认宏观新闻在决策面板可见。

## 交接 V2 要点

1. 白名单 `macro_indicators.yaml` 后续可扩展，不用改 prompt
2. 偏离阈值（0.5σ / 1.5σ）初期是估计值，跑 1-2 周后看生产推送质量可调整
3. 如果 LLM 调用增加成本显著（预估每条心跳多 1-2 次调用），考虑加缓存——同一指标 30 分钟内不重复评估
