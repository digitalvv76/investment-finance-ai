# V2 → V1 交接/回执

> 信道：提交进 main，V1 开工读 origin/main 即见（COLLAB-PROTOCOL §7）。
> V2 窗口 = main @ D:\class1。

---

## 2026-07-11 · 回执：deep_lane 登记表误挂 acceptance_test.py — 已修

**你的交办**：`module_registry.json` 里 `engine/deep_lane.py` 的 `related_scripts` 误挂 `acceptance_test.py`（该脚本不 import deep_lane），常报「过时」，删成 `[]`。

**已办**（commit `bfbd26a` → main，已推）：
- ✅ **先核实再删**：`acceptance_test.py` 实 import fast_lane / entity_extractor / sentiment / priority / learner，**确实不含 deep_lane**。你的判断成立。
- ✅ 旧表 `config/module_registry.json`（供 `session_startup.py` 读）→ deep_lane `related_scripts: []`，误报止住。
- ⚠️ **多修一处（你没点到的）**：新表 `engine/__manifest__.json`（供 `pre_commit_check` 读）里**同一处也误挂了** acceptance_test.py。只删旧表，误报会从提交路径复发 → 已一并清成 `[]`。
- `fast_lane` 的 acceptance_test 关联**保留**（它真 import fast_lane）。deep_lane 真实覆盖 = `test_deep_lane.py`。

**闭环**：无残留，两张表一致，525 测试不受影响（纯配置改）。此条可关。

---

## 2026-07-12 · 回执：军事冲突关键词乘数方案评估

**你的交办**（待写入 V1-TO-V2-HANDOFF.md 新版）：
- 问题：伊朗最高领袖复仇宣言（prod-3931）被四道拦截封死，线上判 impact=15/WATCH
- 用户选方案 B（只开军事冲突，不开内政）
- V1 原型：关键词检测军事冲突 → 给新闻加乘数

**V2 评估如下**：

### 1. 方向认同 ✅

伊朗漏判是真实问题，需要特殊处理。方案 B 范围（军事冲突 ≠ 内政）正确，窄范围降低误触。

### 2. 关键词做触发、不做乘数 ⚠️

关键词直接加乘数的风险你经历过——涨跌幅正则既漏又误删，最后被「认方向」结构替代。军事关键词同类问题：

| 会漏 | 会误触 |
|------|--------|
| "armed confrontation", "cross-border strike" | "trade war", "price war", "streaming wars" |
| 非英文表述的军事行动 | "war on inflation" |
| "retaliatory attack" | 历史回顾/书评/电影 |

**建议**: 关键词做粗筛触发（命中 → 标记 `military_risk_flag` → 交给 LLM 判断），不做乘数。

### 3. 乘数机制有过度工程风险

乘数本质是「不信任 LLM，用规则修正」。但 V2 已用 prompt 改进把伊朗从 15 修到 85——**没有乘数**。乘数叠加的副作用：
- LLM 判 85 × 1.3 = 溢出
- "美军撤出某基地"被关键词误中 × 1.3 = 误推

如果真要乘数，前提必须是「LLM 先判这是军事冲突吗？→ 是 → 乘数生效」。

### 4. 与 V2 已部署改动的重叠

7/12 V2 刚部署 impact_v1 3 项改进（快速预判 + greed_index 锚点 + confidence 降权），直接修了伊朗漏判。如果 V1 的 prompt 改动是：
- 改 `event_driven_v1.txt` → ✅ 互补（实时路径，不重叠）
- 改 `impact_v1.txt` → ⚠️ 需 diff 合并（同一份 prompt 已改）
- 新建独立 military prompt → ✅ 干净

### 5. strategic_detector 不冲突

military detector vs strategic_detector 职责不重叠：前者检测军事威胁（风险信号），后者检测政府资本介入（利好信号）。可以共存。

### V2 建议的落地方式

不是照搬原型，而是吸收思路：

1. 军事关键词做粗筛标记 `military_risk_flag`，传给 LLM 作为额外上下文
2. prompt 侧（event_driven 或 impact）加军事冲突锚点，让 LLM 做最终判定
3. 不做乘数——LLM 已证明能正确判断（伊朗 85/FLASH）
4. strategic_detector 不动

**核心判断：V1 发现了真问题、选了正确的范围（方案 B）、但解法偏重。V2 倾向于用 prompt 而非乘数落地——更轻、更柔性、维护成本更低。**
