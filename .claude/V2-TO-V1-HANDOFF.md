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
