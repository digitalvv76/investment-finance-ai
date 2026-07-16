# 当前工作状态

> 最后更新: 2026-07-16 18:00。关机同步。

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `c3a93bf`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ✅
- **Futu OpenD**: systemd 自启，行情+资金流+新闻+快照+板块五合一 ✅
- **东财代理**: 已废弃 ❌
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动，四通道正常 ✅

## ✅ 本次会话交付 (8 个提交)

### 1. TG 重复推送修复 (`6ae7617`)
- IngestStage 跳过 INSERT OR IGNORE 返回 0 的条目
- 启动时 load_existing_urls 种子 6K URL 缓存
- 新增 get_all_urls() 方法

### 2. TG 推送格式修复 (`9551566`)
- 📌 headline_signal + 📊 analyst_note 不再重复/缺失
- Path A flash_note 不再覆盖 analyst_note
- Path B headline_signal 回退 flash_note

### 3. 深度分析按钮修复 (`6ac8f0a` + `adc5429`)
- 区分 news_id=0 vs deep_lane 缺失，不再误导"引擎未就绪"
- 宏观推送空洞修复（V1 诊断 → V2 实施）：救援舱补全 impact 字段

### 4. 资金流卡片重构 (`a51918f`)
- 币种: US→$, HK→HK$
- 格式: 📌终极结论 + 🎯操作建议
- 对抗性核实修复 3 项

### 5. 同主题去重增强 (`c7c888b`)
- Tier 2 跨键 headline_signal 相似度 (CJK unigram Jaccard ≥ 0.22)
- ticker_hint 空时生成 headline MD5 回退键
- 测试覆盖台积电/TSM 跨 ticker 场景

### 6. 手机推送门槛调高 (`f71c57d`)
- IMPORTANT 仅推关注股 + 宏观 impact ≥ 85
- 预期手机推送量降 50-70%
- entity_extractor 补中概映射

### 7. 资金流全流程审计 (`c0eb7dd` + `e094605` + `c3a93bf`)
- main_pct 分母修复（总成交绝对值替代净流入）
- 推送方向改回 anchor (super_big)
- 散户陷阱零边界 + 累计价格真实值
- K线全零警告 + 采集加重试

### V1 协同
- V1 d17018c 审查：取 macro-push-hollow-fix spec，已实施
- V1 phone-threshold-raise spec，已实施

## 📋 下一步
- 观察 TG 新闻推送格式是否正常
- 观察资金流卡片新格式效果
- 观察手机推送量是否下降
- 盘前 08:00 ET 后检查资金流采集覆盖更多标的
- 🔔 P1 ATR 波动率阈值（仍未实施）
- 🔔 P1 因子有效性回测（仍未实施）

## ⚠️ 本次踩坑
- HuggingFace 504 导致 sentence-transformers 模型下载超时，重启后自动恢复
- dispatch 测试 `_item` 默认 impact_score=0 导致手机门槛挡住所有测试
- CJK 单字 Jaccard 对短标题不敏感 → 改用 unigram 分词
