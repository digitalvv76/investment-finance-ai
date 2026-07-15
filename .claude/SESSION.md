# 当前工作状态

> 最后更新: 2026-07-15 11:30。手机推送双规则收紧已部署。

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `392820c`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ✅

## ✅ 本会话交付 (2026-07-15 上午)

### 📱 同主题去重 (commit `ee9b671`)
- 用户反馈: CPI 同一事件 3h 推 3 条到手机
- 修复: dispatch.py 6h 窗口内同 macro/ticker 主题只推第一条
- 仅限 Pushover (手机)，TG 全量接收
- 8 组 macro 正则归一化 + 强度升级豁免 + 方向分离
- +23 tests, 538 passed

### 📱 机构资金 → TG only (commit `392820c`)
- 用户反馈: ARK 增持 OKLO/XE 不应响手机
- 修复: event_channel_level event_type=3 → notable (TG 静默)
- ★5 豁免，混合类型 [1,3] 不受限
- +6 tests, 58 passed

## 📋 下一步
- 📊 **观察生产**: 下次宏观事件/机构资金新闻时看推送是否符合预期
  - 同主题是否只推第一条
  - 机构资金类是否只在 TG 不响手机

## ⚠️ 本次踩坑
- 无新踩坑，两处改动均为纯增量，无回归
