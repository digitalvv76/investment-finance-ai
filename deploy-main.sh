#!/usr/bin/env bash
# ============================================================================
# deploy-main.sh — 把当前 origin/main 的运行时代码部署到 V1 生产（走 git，不 scp）
# ============================================================================
# 固化 COLLAB-PROTOCOL §1b / lean-spec §31 的「部署前先 tag 回滚镜像」习惯。
#
# 只同步 Python 源码 + prompts；**故意不碰** config/*.yaml、docker/、.env
# （这些是 ECS 专属：请求延迟、卷路径、代理、凭证——见 ecs-prod-drift 教训）。
# 若某次改动涉及这些配置，手动处理，别指望本脚本。
#
# Usage:
#   ./deploy-main.sh              # tag回滚 → checkout源码 → 重建 → 验证
#   ./deploy-main.sh --no-verify  # 跳过健康验证
# ============================================================================
set -euo pipefail

ECS_HOST="root@47.76.50.77"
ECS_PROJECT="/opt/news-monitor"
DOCKER_DIR="${ECS_PROJECT}/news-monitor/docker"
ROLLBACK_TAG="rollback-$(date +%Y%m%d-%H%M%S)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[DEPLOY]${NC} $*"; }
warn() { echo -e "${YELLOW}[DEPLOY]${NC} $*"; }
err()  { echo -e "${RED}[DEPLOY]${NC} $*"; }

VERIFY=true
for a in "$@"; do case "$a" in --no-verify) VERIFY=false ;; *) err "未知参数 $a"; exit 1 ;; esac; done

# 只同步这些运行时目录/文件（Python 逻辑 + prompts），保留 ECS 配置
SRC_PATHS=(
  news-monitor/engine news-monitor/collector news-monitor/pipeline
  news-monitor/storage news-monitor/bot news-monitor/web
  news-monitor/main.py news-monitor/config/prompts news-monitor/requirements.txt
)

# ── 0. 前置：本地 main 已推送？ ─────────────────────────────────────────
info "0/5  前置检查"
echo "     本地 HEAD: $(git log -1 --oneline)"
if ! git diff --quiet origin/main..HEAD 2>/dev/null; then
  warn "     本地 HEAD 与 origin/main 有差异——请先 git push origin main"
fi
if ! ssh -o ConnectTimeout=6 -o BatchMode=yes "$ECS_HOST" "echo ok" &>/dev/null; then
  err "SSH 不通 ECS"; exit 1
fi
info "     SSH: OK"

# ── 1. 打回滚镜像（固化习惯）────────────────────────────────────────────
info "1/5  打回滚镜像 ${ROLLBACK_TAG}"
ssh "$ECS_HOST" "docker tag docker-news-monitor docker-news-monitor:${ROLLBACK_TAG}"
info "     回滚镜像已打；出事可：docker tag docker-news-monitor:${ROLLBACK_TAG} docker-news-monitor && 重建"

# ── 2. git 同步源码（保留 ECS 配置）────────────────────────────────────
info "2/5  git fetch + checkout origin/main 源码（保留 config/docker/.env）"
ssh "$ECS_HOST" "cd ${ECS_PROJECT} && git fetch origin -q && git checkout origin/main -- ${SRC_PATHS[*]}"

# ── 3. 重建容器 ────────────────────────────────────────────────────────
info "3/5  重建 news-monitor（旧容器跑到新镜像就绪才切）"
ssh "$ECS_HOST" "cd ${DOCKER_DIR} && docker compose -f docker-compose.yml up -d --build news-monitor 2>&1" | tail -4

# ── 4. 健康验证 ────────────────────────────────────────────────────────
if $VERIFY; then
  info "4/5  健康验证"
  for i in $(seq 1 12); do
    sleep 5
    STATUS=$(ssh "$ECS_HOST" "docker ps --filter name=^news-monitor$ --format '{{.Status}}' 2>/dev/null")
    if echo "$STATUS" | grep -q healthy; then
      echo -e "     ${GREEN}✅ healthy — ${STATUS}${NC}"; break
    fi
    echo "     等待... (${STATUS:-未找到})"
  done
  ssh "$ECS_HOST" "docker logs news-monitor --since 90s 2>&1 | grep -E 'News Monitor running|Watchdog started' | tail -2" || true
else
  info "4/5  验证已跳过"
fi

# ── 5. 完成 ────────────────────────────────────────────────────────────
info "5/5  部署完成"
info "     回滚: ssh ${ECS_HOST} \"docker tag docker-news-monitor:${ROLLBACK_TAG} docker-news-monitor && cd ${DOCKER_DIR} && docker compose -f docker-compose.yml up -d news-monitor\""
