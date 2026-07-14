# SPEC: Docker 健康检查超时假阳性修复

> V1 → V2 交接 | 2026-07-14 | 来源：用户要求检查 ECS 运行状态

## 问题

部署后 Docker 健康检查间歇性超时，导致容器状态 `unhealthy`：

| 检查时间 | 结果 |
|----------|------|
| 16:15 | ✅ 通过 |
| 16:16–16:19（连续4次） | ❌ 超时 10s |
| 同时段内部 `/health` | ✅ 正常 200 OK |

**根因**：心跳期事件循环繁忙（210条去重+管道处理），`/health` HTTP handler 排队等不到执行，超过 Docker `--timeout=10s`。不是僵死，是假阳性。

**当前配置**（`news-monitor/docker/Dockerfile:73`）：
```dockerfile
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1
```

## 推荐方案 C（Dockerfile 放宽 + watchdog 兜底）

### 为什么选 C
- 最小改动，一行的 diff
- watchdog 已独立运行（`asyncio.create_task` 不寄生 scheduler），不受心跳繁忙影响
- watchdog 才是真正的僵死检测器，Docker healthcheck 只是容器存活信号

### 改动（1 文件）
**`news-monitor/docker/Dockerfile` 第 73 行**：
```dockerfile
# Before
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# After
HEALTHCHECK --interval=90s --timeout=15s --start-period=120s --retries=5 \
    CMD curl -f http://localhost:8080/health || exit 1
```

| 参数 | 改前 | 改后 | 理由 |
|------|:---:|:---:|------|
| interval | 60s | 90s | 减少与心跳重合概率 |
| timeout | 10s | 15s | 容忍事件循环短暂繁忙 |
| retries | 3 | 5 | 5 次失败 = 7.5 分钟窗口，避免瞬时抖动误报 |
| start-period | 120s | 120s | 不变 |

### 为什么不等同于"掩盖问题"
- 如果事件循环真的僵死（之前两次生产事故），watchdog 会在 30 分钟内独立报警（`ingest_1h < floor`）
- Docker healthcheck 只管容器是否 alive，不应做僵死检测（它做不到——它 HTTP 超时和僵死超时无法区分）
- 之前 `e9708ba` 已修了采集器级 timeout，但事件循环繁忙 ≠ 僵死

## 备选方案（如果 C 不够）

| 方案 | 改动 | 效果 |
|------|------|------|
| A: 只改参数 | Dockerfile 一行 | 假阳性减少，真僵死仍靠 watchdog |
| B: 独立线程 health server | main.py + Dockerfile | 彻底解决，但引入多线程复杂度 |

## 验证
- 改后重建容器 → `docker ps` 观察 15 分钟 → 应稳定 `healthy`
- watchdog 日志确认仍在独立运行
