# 系统训练与模型优化方案 — V1 设计 → V2 实施

> 状态: V1 方案设计 | 日期: 2026-07-16

## 现状诊断

### 已有的（不错）

| 组件 | 状态 | 说明 |
|------|:---:|------|
| Learner 引擎 | ✅ | 反馈→信源权重+阈值自适应 |
| Telegram 反馈按钮 | ✅ | 👍/👎 inline keyboard |
| Holdout 盲测 | ✅ | 14 条干净样本，排除 few-shot |
| 训练数据 | ✅ | H1 2026 标注事件集 |
| R0 event_decisions 表 | ✅ | 每次评估决策落库 |
| Autolabel | ✅ | LLM 自动标注新样本 |

### 缺失的（瓶颈）

| 缺口 | 影响 |
|------|------|
| 反馈闭环未充分利用 | Learner 在跑但用户用得少，数据稀疏 |
| Prompt 没有自动优化 | 靠人工改 prompt，没有数据驱动的迭代 |
| 没有 A/B 对比 | 改 prompt 后不知道比旧版好还是差 |
| Wiki 未接入评估 | 用户真正关心的标的/主题没有用于校准 |
| 没有跨模型验证 | DeepSeek 单模型盲点无法自我纠错 |

---

## 方案：四层训练体系

```
Layer 1: 反馈闭环 (用户→系统)     ← 最优先，数据源头
Layer 2: Prompt 自动校准 (数据→Prompt) ← 从反馈数据驱动优化
Layer 3: 跨模型对抗 (模型→模型)   ← 打破单模型盲点
Layer 4: Wiki 驱动 (知识→评分)     ← 个性化校准
```

---

### Layer 1: 反馈闭环增强

**目标**: 让每次推送都成为训练数据。

**当前问题**: Telegram 有 👍/👎 按钮但用户不太用。需要更低摩擦的反馈方式。

**方案**:

```python
# 1a. Telegram 按钮增强 — 每条推送消息追加 inline 按钮
# 当前: [👍 内容好] [📊 预测准确]
# 增强: [🔔 推得好] [🔇 不推也行] [❌ 误报]  ← 更直观

# 1b. 反馈影响权重
FEEDBACK_WEIGHTS = {
    "push_good":    {"source": +0.01, "topic": +0.02},   # 推得好→信任上升
    "push_ok":      {"source": +0.00, "topic": +0.00},   # 不推也行→保持
    "push_bad":     {"source": -0.02, "topic": -0.03},   # 误报→降权
}

# 1c. 反馈积累到阈值触发 Learner 自动调整
# 当前: 按钮被点击时触发 learner.run_adaptation_cycle()
# 增强: 每累计 10 条反馈自动跑一次 Learner
#       每周生成一份「信源可信度报告」推送到 TG
```

**工作量**: ~50 行改动 + 5 测试，1 小时

---

### Layer 2: Prompt 自动校准

**目标**: 用 R0 event_decisions 表中的历史数据，自动发现 prompt 的弱点并生成改进建议。

**方案**:

```python
# 2a. 自动回归测试 — 每次改 prompt 前跑
# 从 event_decisions 表取最近 100 条，用新旧 prompt 各跑一次
# 对比: 推送率 / 误推率 / 漏推率

# news-monitor/scripts/calibrate_prompt.py
async def compare_prompts(old_prompt, new_prompt, test_cases):
    """A/B 对比两个 prompt 在 100 条真实新闻上的表现"""
    old_results = await evaluate_with_prompt(old_prompt, test_cases)
    new_results = await evaluate_with_prompt(new_prompt, test_cases)
    return {
        "push_rate_change": new_results.push_rate - old_results.push_rate,
        "intensity_correlation": compare_intensity(old_results, new_results),
        "direction_agreement": compare_direction(old_results, new_results),
    }

# 2b. Few-shot 自动优化 — 从反馈中提取最佳样本
# 用户标记 "推得好" 的事件 → 自动加入 few-shot 候选池
# 每周用最新的 4 条高反馈样本替换 prompt 中的 few-shot
```

**工作量**: ~200 行 + 15 测试，3 小时

---

### Layer 3: 跨模型对抗验证

**目标**: DeepSeek 单模型有盲点。加一层独立验证，用不同模型检查关键决策。

**方案**:

```python
# 3a. 关键决策二次验证
# 当评估结果 intensity ≥ 4 时，用 GLM/备用模型重新评估
# 两个模型结论一致 → 通过；分歧 → 降级推送

# news-monitor/engine/adversarial_verify.py
class AdversarialVerifier:
    """跨模型对抗验证 — 打破单模型盲点。
    
    只对高影响决策 (intensity ≥ 4) 启动验证，控制成本。
    """
    
    async def verify(self, item, primary_result):
        if primary_result.intensity < 4:
            return primary_result  # 低影响跳过
        
        # 用备用模型独立评估
        secondary = await self._evaluate_with_secondary(item)
        
        if secondary.intensity != primary_result.intensity:
            # 分歧 → 降级 (保守策略)
            primary_result.intensity = min(primary_result.intensity, 
                                           secondary.intensity)
            logger.info("Adversarial: %s intensity %d→%d (disagreement)",
                         item.id, primary_result.intensity, secondary.intensity)
        
        return primary_result
```

**前提**: 需要第二个 LLM（GLM 已配置 key，可立即使用）
**成本**: 仅 intensity≥4 触发，每天约 5-10 次额外调用

**工作量**: ~150 行 + 10 测试，2 小时

---

### Layer 4: Wiki 驱动相关性校准

**目标**: Wiki 是用户投资体系的核心表达。用它来校准"这条新闻对我有没有用"。

**方案**:

```python
# 4a. Wiki 向量化 — 将 wiki 页面转为检索索引
# wiki/NVDA.md → embedding → 存储到 ChromaDB
# 新新闻到来时 → 检索最相关的 wiki 页面 → 计算 relevance boost

# news-monitor/engine/wiki_relevance.py
class WikiRelevance:
    """Wiki 驱动的个性化相关性评分。
    
    新闻与 wiki 中的持仓/关注标的匹配 → 加分。
    与 wiki 中的所有主题都不相关 → 减分。
    """
    
    async def compute_boost(self, news_item):
        # 从 wiki 检索相关页面
        relevant_pages = await self._search_wiki(news_item.title)
        
        if not relevant_pages:
            # 与用户所有关注点都不相关 → 门槛更高
            return {"boost": -0.05, "reason": "no wiki match"}
        
        # 匹配到 wiki 页面 → 按页面置信度加权
        boost = sum(p.confidence_score for p in relevant_pages) * 0.03
        return {"boost": min(boost, 0.10), "reason": f"matched: {[p.ticker for p in relevant_pages]}"}
```

**前提**: 需要 embedding 模型（ECS 已有 SentenceTransformer）
**成本**: 每条新闻一次向量检索，毫秒级

**工作量**: ~200 行 + 10 测试，3 小时

---

## 汇总

| Layer | 功能 | 核心价值 | 工作量 |
|:---:|------|------|:---:|
| L1 | 反馈闭环增强 | 数据源头 — 没有反馈就没有训练 | 1h |
| L2 | Prompt 自动校准 | 数据→Prompt 闭环，不再盲调 | 3h |
| L3 | 跨模型对抗验证 | 打破 DeepSeek 单模型盲点 | 2h |
| L4 | Wiki 驱动相关性 | 个性化 — 用户真正关心的才推 | 3h |
| **合计** | | | **1.5 天** |

### 优先级

```
L1 (反馈) → L3 (对抗) → L4 (Wiki) → L2 (校准)
  ↑            ↑            ↑            ↑
 必须先做     最快见效    个性化      依赖L1数据
```

L1 是所有训练的数据源头，必须最先做。L3 用已有的 GLM key 立刻就能上线。L4 让系统从"通用推送"变成"你的推送"。L2 在积累足够反馈数据后自动运转。

### 预期效果

- **误推率**（用户标记"不推也行"）：当前约 30-40% → 目标 < 15%
- **漏推率**（重要事件错过）：当前未知 → L4 上线后量化
- **反馈参与率**：当前 < 5% → L1 增强后目标 > 20%
