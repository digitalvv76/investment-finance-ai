# SPEC: Agent 人格化 — Graham 风格价值投资审查

> V1 → V2 交接 | 2026-07-17 | 来源：AI 金融全景调研 P0 决策
>
> 关联：[[quality-gate-lightweight]] · [[govt-program-rating-deepdig]] · [[push-predicted-vs-happened]]

## 问题

当前系统所有 LLM 评估共用同一视角——「找理由推」。五个 prompt（宏观分析师、事件哨兵、影响评估、可操作性审查、深度分析）无一例外都是买方/对冲基金分析师口吻。

**后果**：
- 同模型 agent 共享盲点——全景调研确认这是行业共识问题
- 广东 CPI、马来西亚 GDP 能一路通关，因为没有任何环节问「这真的重要吗？」
- 现有的 ActionabilityReviewer 只在 borderline（信号 0.3-0.7）触发，且同样是 trader 视角，不是真正不同的声音

**核心思路**：不等同于加人海战术的「多 agent 辩论」。加一个视角根本不同的审查者——不找理由推，找理由不推。

## 方案：Benjamin Graham 风格价值投资审查

### 在流水线中的位置

```
Ingest → Macro → Screen → Evaluate → [Graham Review] → Dispatch
                                        ↑ 新增
```

Evaluate 做出 push 决策后、Dispatch 发送前，所有非 NORMAL 的新闻过 Graham 审查。Graham **只能降级，不能升级**——他是刹车，不是油门。

### 人格设定

```
你是 Benjamin Graham 风格的价值投资审查员。
你的唯一职责是质疑：这条新闻真的值得打断投资者的注意力吗？
你天然怀疑一切——大多数新闻是噪音。你不是来找理由推的，你是来找理由不推的。

核心信念：
- 市场短期是投票机，长期是称重机。你只关心称重机。
- 如果一条新闻不改变任何公司的内在价值，它不值得推送。
- "这听起来很重要"不是推送理由。"这改变了盈利预期"才是。
```

### 审查清单（5 个问题）

每个问题独立判断——任意 FAIL → 降级。

| # | 问题 | FAIL 条件 | 针对的盲点 |
|---|------|----------|-----------|
| 1 | 这是已发生的事，还是预测/观点？ | 标题含「预计」「或将」「可能」「暗示」「传闻」「据称」且正文无硬数据支撑 | 把预测当真事件推（memory [[push-predicted-vs-happened]]） |
| 2 | 如果这是宏观数据，来源国直接影响美国股市或我的关注名单吗？ | 来源国不在 T1(美)/T2(欧日)/T3(中韩) 或不在关注股所在国 | 广东 CPI、马来西亚 GDP（今天两起事故） |
| 3 | 这件事改变任何公司的盈利能力或资产价值了吗？ | 纯情绪/标题党/政策标题无资金落地机制/「或再现」类模因股暗示 | 把情绪当基本面（memory [[push-predicted-vs-happened]]） |
| 4 | 市场是否已经有充分时间消化这条信息？ | 事件公开 > 2 小时且无新增信息（非更新数据/非独立确认） | 旧闻新炒、滞后报道 |
| 5 | 如果去掉这条推送，明天回头看你会觉得错过了一个交易机会吗？ | 你觉得 24h 后没人会记得这条新闻 | 终极检验——大部分推送通不过这关 |

### 降级规则

| FAIL 数 | 动作 |
|:---:|------|
| 0 | 维持原判，正常推送 |
| 1-2 | 降到静音 TG（NOTABLE），不推手机 |
| ≥3 | 不推（NORMAL） |

**重要**：Graham 只能降级，不能升级。即使他 5 个全 PASS，也不提升原推送等级。这保证 Graham 是安全网，不是放大器。

### 输出格式

```json
{
  "verdict": "PUSH",
  "failures": [],
  "note": "美国 CPI 超预期，直接影响利率预期和所有美股估值，通过全部 5 项审查。"
}
```

```json
{
  "verdict": "SILENT",
  "failures": [2],
  "note": "马来西亚 GDP 不影响美股也不在关注名单，不构成推送理由。"
}
```

```json
{
  "verdict": "DROP",
  "failures": [1, 3, 5],
  "note": "'或将迎来'是预测不是事件，无公司盈利受影响，明天没人会记得。"
}
```

### 触发范围

**全部非 NORMAL 推送决策**，即主评估判定要推的每条新闻都过 Graham。

日调用量预估 ~30-50 次，DeepSeek 成本可忽略。

### 与现有 ActionabilityReviewer 的关系

| | ActionabilityReviewer | Graham Review |
|---|---|---|
| 触发 | 仅 borderline (signal 0.3-0.7) | 全部要推的 |
| 视角 | trader — 「手机该响吗？」 | value investor — 「值得打断注意力吗？」 |
| 方向 | 可升可降 | 只能降级 |
| 角色 | 精细调参 | 安全网 |

两者互补，不冲突。Graham 先跑（覆盖全部），ActionabilityReviewer 在 borderline 仍然跑（精细判断）。

## 实施要点

### 新增文件
- `news-monitor/config/prompts/graham_review.txt` — Graham 审查 prompt
- `news-monitor/engine/graham_reviewer.py` — Graham 审查器类

### 修改文件
- `news-monitor/pipeline/evaluate.py` — 在 Evaluate 阶段末尾插入 Graham 审查调用
- `news-monitor/config/module_registry.json` — 注册新模块
- `news-monitor/config/__manifest__.json` — 同步注册

### Prompt 设计要点

1. 人格设定放在最前面——第一句话定义角色
2. 5 个问题逐条列出，每条带 FAIL 条件
3. 强调「默认怀疑」——如果犹豫，选 FAIL
4. 用中文输出（与项目一致）
5. 加入 few-shot 校准样本：广东 CPI（FAIL #2）、马来西亚 GDP（FAIL #2）、美国 CPI（全 PASS）、「或将再现」模因股（FAIL #1+#3）

### 成本

| 项目 | 估算 |
|------|------|
| 日调用量 | ~30-50 次 |
| 每次 token | ~500 input + ~200 output |
| 模型 | DeepSeek（现有） |
| 日成本 | < $0.01 |

## 验证

- [ ] 广东居民消费价格 → Graham FAIL #2 → 降级/不推
- [ ] 马来西亚 GDP → Graham FAIL #2 → 降级/不推
- [ ] 美国 CPI 超预期 → Graham 全 PASS → 正常推送
- [ ] 「XX或将迎来暴涨」→ Graham FAIL #1+#3 → 不推
- [ ] 2 小时前的旧闻无更新 → Graham FAIL #4 → 降级
- [ ] Graham 审查不增加 Evaluate 阶段延迟 > 5 秒
- [ ] Graham 不能把 NORMAL 升级为推送
