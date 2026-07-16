# 当前工作状态

> 最后更新: 2026-07-16 15:23。TG 重复推送修复。

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `6ae7617`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一 ✅（ECS .env 代理已修复）
- **Futu OpenD**: systemd 自启，行情+资金流+新闻+快照+板块五合一 ✅
- **东财代理**: 已废弃 ❌
- **TG 推送**: 资金流 + 新闻 + 快照 + 板块轮动，四通道正常 ✅
- **TG 重复推送**: 已修复 ✅ — IngestStage 跳过 INSERT OR IGNORE 条目 + 启动 URL 缓存

## ✅ 本次会话交付

### 1. Futu OpenD 全栈迁移
- ECS 安装部署，systemd 自启，安全配置（纯行情 + 2FA）
- 资金流采集（替代东财）、K线价格（替代 yfinance）、新闻采集、实时快照、板块轮动

### 2. 资金流模型 V2.5 生产级
- 六法则 A-F（小单/连续/占比/合力/陷阱/黄金坑）
- 推送强制首位标定、信号强度标准化、分类完全信任富途

### 3. 中文管道 + TG 优化
- 华尔街见闻适配（实体提取/优先级/Prompt/关键词）
- 富途新闻接入（35 关键词轮转）
- TG 卡片重构、限流、去国旗、去反馈按钮

### 4. 对抗性核实
- 6 个运行时 bug 修复（时区/参数/NaN/重叠/格式/方向）

## 📋 下一步
- 🔔 P1 ATR 波动率阈值
- 🔔 P1 因子有效性回测
- 📋 新模块注册 module_registry.json
- 🧪 新采集器补测试覆盖
- 🔧 板块轮动 US. 前缀验证

## ⚠️ 本次踩坑
- 东财 API 全线被封 → 切换富途
- ECS .env 残留 Clash 代理 → DeepSeek/HTTPS 全断
- ECS docker0 是 172.18.0.1 非 172.17.0.1
- 时区 bug: datetime.now()=CST, 需转 ET
- send_system_alert 参数名 body→message
- Telegram Conflict: 不能同时两个 bot 实例 polling
- NewsBot 无 send_message 方法，需 app.bot.send_message
- 中文引号被 ASCII 替换导致 SyntaxError
- 线程耗尽：重复 ApplicationBuilder 初始化
