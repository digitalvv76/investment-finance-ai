# 当前工作状态

> 最后更新: 2026-07-09 ~15:20 CST (V1 窗口 / v1-stable)

## ✅ 本次完成 — 部署受阻→抢救孤儿代码→安全加固

- **事件升级推送部署：暂停**。上服务器发现 `/opt/news-monitor` 是 dirty 工作副本，有 ~1451 行未提交孤儿代码（30 文件 + 15 新文件），直接部署会覆盖、使生产倒退 → 果断停手
- **孤儿代码抢救**：双份备份（服务器 `/opt/news-monitor-backup/2026-07-09_135506/` + 本地 `.claude/backups/ecs-rescue/`），验证可还原；**main 窗口已归档进 `rescue/ecs-prod-drift-20260708`**（交接说明生效）
- **来源取证**：孤儿代码=7/7–8 服务器上跑 Claude Code 改的；陌生登录 `100.104.189.x`=阿里云网页终端代理段（非入侵，用户确认）
- **安全加固**：关闭 SSH 密码登录（`PasswordAuthentication no`，防锁死流程+新连接验证通过）；清除 bash_history 明文密码 2 处
- 生产服务全程零中断，容器 healthy

## 📋 下一步（均待人工确认/独立排期）

1. **事件升级推送部署（阻断中）** — 必须先把 `rescue/ecs-prod-drift-20260708` 与本窗口 v1-stable 事件升级功能**合并 + 测试通过**，才能部署。这是下一件独立开发活
2. **轮换 root 强密码 + 存凭证备份**（非紧急：密码登录已关+明文已清，仅 VNC 仍用）
3. **🔴 8080 公网裸奔（已核实）** — 外部无凭证可读 `/api/*` 真实数据（写接口大概率同样敞）；`.env` 设了 WEB_USERNAME 但运行容器未强制。**不能单独关**（手机走 Vercel→直连 8080）→ 随下次「孤儿代码合并+部署」一并修：Vercel 改走 :80 认证 + 8080 收内网，或容器真启用认证 + Vercel 带认证头
4. 本会话收尾：`dev_checklist.py` → commit HISTORY/SESSION → `git push origin v1-stable`

## ⚠️ 铁律

- 本窗口只做 v1-stable；孤儿代码归档在 main 窗口/rescue 分支
- ⛔ 不对 ECS 工作副本做 checkout/reset（容器靠它跑）；不部署；两窗口不同时动同一服务器

## 🩹 本次踩坑（已入 memory `ecs-prod-drift` / `ecs-server`）

- 绕过「本地开发→提交→部署拉 git」流程直接改生产 → 代码岔开
- `deploy_ecs.sh` 拉 `origin/main`，与 v1-stable 功能分支不符
- 弱 root 密码 + SSH 密码登录曾开启（已关）

## 📊 系统健康

| 组件 | 状态 |
|------|------|
| 生产容器 | ✅ healthy，零中断 |
| 事件升级推送 | ⏸️ 已实现(v1-stable)，未部署，阻断于孤儿代码合并 |
| 孤儿代码 | ✅ 双份备份 + 已归档 rescue 分支 |
| SSH 安全 | ✅ 仅密钥登录 |

## 🧪 已知预存测试失败（非本次引入；今日零源码改动，仅文档）

- 4 real fails: `test_impact_push` ×3 (high/moderate/low classification) + `test_scheduler::test_load_watchlist_default` — 疑因本地 `alert_dispatcher.py` 缺孤儿代码时效性逻辑、测试按新行为写 → 随孤儿代码合并一并修
- 6 errors: `test_vector_store` — Windows ChromaDB 文件锁，已知环境问题，非逻辑失败
- 334 passed, 全绿前勿部署

> 会话结束 — 2026-07-09T15:52 · 关机

## ⚠️ 铁律
