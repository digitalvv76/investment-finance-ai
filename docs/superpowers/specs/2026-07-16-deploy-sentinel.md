# 部署哨兵 (Deploy Sentinel) — V1 方案 → V2 评估

> 状态: 方案待评估 | 日期: 2026-07-16

## 问题

当前部署验证只靠 `/health` 端点——容器活着就算成功。但 `/health` 通过不意味着系统在干活：采集可能停摆、TG bot 可能冲突、LLM API 可能不通。每次部署都是"推上去等用户反馈推送没到才知道坏了"。

我们已有的基础：
- `deploy-main.sh`：tag 回滚 → git sync → 重建 → health 验证（5 步）
- `dev_checklist.py`：会话结束检查（git/测试/HISTORY/凭证/远程）
- `uptimerobot`：外部探测 `/health`
- `watchguard.py`：内部采集监控

**缺的是部署后那一分钟的功能验证。**

## 方案

在 `deploy-main.sh` 的 health 验证和完成之间，插入一步 **smoke test**——跑一个轻量脚本，验证系统不是在"活着但没用"的状态。

### 部署流程（改后）

```
0. 前置检查 (SSH + 本地已推送)
1. 打回滚镜像 tag
2. git sync 源码
3. 重建容器 → 等待 healthy
4. 🆕 部署哨兵 smoke test (30s)  ← 新增
   ├─ 4a. /health 返回 ok
   ├─ 4b. 采集心跳 (< 5min ago)
   ├─ 4c. TG bot 无冲突 (无另一实例 polling)
   ├─ 4d. LLM API 可达 (一条轻量测试调用)
   └─ 4e. Pushover 凭证可推送 (发送一条 "deploy ok" 静默消息)
5. 如果 4 的任意步骤失败 → docker tag 回滚 + 重建 → 告警
6. 部署完成
```

### 哨兵脚本设计

**文件**：`news-monitor/scripts/deploy_sentinel.py`

**输入**：ECS SSH host（默认 `root@47.76.50.77`），容器名（默认 `news-monitor`）

**输出**：全绿 → exit 0，任何红 → exit 1 + 错误详情

**5 项检查**：

| # | 检查项 | 方法 | 超时 | 说明 |
|---|--------|------|------|------|
| 1 | **Health 端点** | `curl /health` → 200 + `{"status":"ok"}` | 5s | 已有，哨兵再做一次确认 |
| 2 | **采集心跳** | SSH 查 DB：`SELECT MAX(captured_at) FROM news WHERE captured_at > datetime('now','localtime','-5 minutes')` | 10s | 上次部署重启后采集可能加载模型 1-2 分钟，给 5 分钟窗口 |
| 3 | **TG Bot 冲突** | SSH docker logs 搜 `Conflict` / `terminated by other` | 10s | 双 bot polling 会 crash 其中一个 |
| 4 | **LLM 可达** | 容器内调一条最小评估（"ping"→预期返回 pong 或正常 JSON） | 15s | 验证 DeepSeek API 通 + 代理正常 |
| 5 | **Pushover 可推送** | 发一条静默测试消息（priority=-2 不震手机） | 10s | 验证凭证有效 + 网络通 |

**回滚触发**：任意一项失败 → 打印失败详情 → exit 1。`deploy-main.sh` 收到 exit 1 → `docker tag rollback-*` → 重建旧镜像 → 哨兵再跑一遍验证旧版 OK → 告警用户。

### 为什么不做全量推送测试

不模拟一条真实新闻推送——那需要构造完整的 PipelineItem，风险是假数据污染 DB 或真发到手机上。5 项检查覆盖了推送链路的每个环节（采集→评估→TG→手机），拆开验证比端到端更安全。

### 接入 deploy-main.sh

在现有第 4 步 health 验证之后、第 5 步完成之前插入：

```bash
# ── 4.5 部署哨兵 smoke test ──
info "4.5/5  部署哨兵"
SMOKE_OUTPUT=$(ssh "$ECS_HOST" "cd ${ECS_PROJECT} && python3 scripts/deploy_sentinel.py" 2>&1)
if [ $? -ne 0 ]; then
  err "哨兵未通过，回滚..."
  echo "$SMOKE_OUTPUT"
  ssh "$ECS_HOST" "docker tag docker-news-monitor:${ROLLBACK_TAG} docker-news-monitor && cd ${DOCKER_DIR} && docker compose -f docker-compose.yml up -d news-monitor"
  err "已回滚到 ${ROLLBACK_TAG}，请检查哨兵日志后重试"
  exit 1
fi
info "哨兵通过 ✅"
```

## 改动量

| 文件 | 改动 | 类型 |
|------|------|------|
| `news-monitor/scripts/deploy_sentinel.py` | ~120 行，新建 | 核心哨兵 |
| `deploy-main.sh` | ~15 行，加步骤 4.5 | 集成 |
| `news-monitor/config/__manifest__.json` | +1 模块注册 | 注册 |

**总计 ~135 行，3 文件**

## 风险

- **极低**：哨兵是只读+轻量写（一条静默 Pushover），不影响生产数据
- 哨兵自身挂了只阻止部署，不会损坏已运行的服务
- 唯一的"副作用"是部署成功后一条 `priority=-2` 的 Pushover 消息（手机不震不亮屏）

## 后续可扩展

- 部署后 5 分钟自动再跑一次哨兵（验证采集已恢复稳定）
- 接入看门狗：哨兵失败 → 自动发 Pushover 告警
- 记录每次部署的哨兵结果到 `deploy_history` 表
