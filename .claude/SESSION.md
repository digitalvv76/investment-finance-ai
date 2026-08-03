# 当前工作状态

> 最后更新: 2026-08-03T22:30。HISTORY 补账完成，管线健康。

## 🆕 待 V2 读取

> 来自 V1 的 spec 交接。

| 日期 | Spec 文件 | 说明 |
|------|----------|------|
| — | 当前无待交接 | —

---

## 🟢 当前部署状态
- **ECS 生产**: V2 (origin/main, `cd1ae82`)，健康 ✅
- **LLM 供应商**: DeepSeek 唯一，v4-pro (核心评估) + v4-flash (噪音过滤)
- **Futu OpenD**: ✅ 已复活 — 7/16 僵死进程已清理，重启动正常运行
- **Futu 新闻**: 恢复（~138 关键词）
- **Futu 资金流**: 恢复（71 只票），已验证采集→信号→LLM 全链路
- **DeepSeek v4 max_tokens**: 9 模块已修复（FLASH: 1024-8000, PRO: 4096）
- **Telegram Bot**: 无限用户扩展已上线，新用户只需加 .env 变量
- **管线**: 全链路健康

## 📱 推送门槛
- **Geo-tier**: 非美宏观 ×0.25 基本不推
- **Graham 审查**: 5 问题清单降级/拦截噪音
- **手机**: 战略规则 > 宏观≥92 > CRITICAL
- **TG**: IMPORTANT 阈值 0.50，每周期封顶 4 条

## 🔧 最近完成
- 富途 OpenD 诊断 + 强杀旧进程 + 重启 → 双源恢复
- 资金流完整管线验证（采集 → 信号 → LLM → 推送）
- DeepSeek v4 reasoning 吃 token 根因确认 + A/B 验证
- 9 模块 max_tokens 修复 + settings.yaml 覆盖问题修复
- 对抗式核实（致命发现 + 3 遗漏 → 全部修复）
- Telegram Bot 无限用户扩展
- SessionEnd hook 自动补账
- HISTORY.md 补账完成 → 已推送

## ⚠️ 踩坑记录
- Futu OpenD 僵死：进程存活+端口 LISTEN 但 SYN 无响应（不是 Docker 网络问题）
- DeepSeek v4: reasoning_content 从 max_tokens 预算扣，content 为空的根因
- settings.yaml 的 `dict.get(key, default)` — default 只在 key 不存在时生效，key 存在就覆盖
- 对抗式核实铁律：连续 2 次跳过被纠正，补跑皆发现致命问题
