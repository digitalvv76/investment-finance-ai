# V1 → V2 富途交付通知 · 2026-07-16

> V1 今日交付完毕，以下待 V2 评估执行。

---

## 🔴 P0 — 防封禁加固（1 行修复）

**文件**: `news-monitor/collector/futu_fetcher.py`  
**改动**: `fetch_multi()` 的 `_fetch_one` 内加 `await asyncio.sleep(0.3)`  
**原因**: 东财因无间隔被封。富途走本地网关不暴露 IP，但加间隔是必要保险。

---

## 🟡 P1-P3 — 富途数据挖掘

**Spec**: `docs/superpowers/specs/2026-07-16-futu-full-utilization.md`  
**Commit**: `0a3bebf`（v1-stable）

| 阶段 | 功能 | 工作量 |
|:---:|------|:---:|
| P1 | 盘前/盘中实时快照 (`get_market_snapshot`) | 2h |
| P2 | 板块轮动追踪 (`get_plate_list` + `get_capital_flow`) | 3h |
| P3 | 经纪商队列 (`get_broker_queue`, 先验证美股可用) | 3h |

**ECS 安全性**: 已评估，无宕机风险。新增调用量 ~135/天，无新 LLM 调用，无新常驻进程。

---

## ✅ 今日已完成（无需操作）

- MacroAgent 部署 ✅
- 华尔街见闻中文管道 + 日经 RSS ✅
- 35 个中文管道测试 ✅
- 中文引号崩溃修复 ✅

ECS 当前 `8af4132`，所有变更已上线。
