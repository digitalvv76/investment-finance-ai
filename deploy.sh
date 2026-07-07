#!/usr/bin/env bash
# ============================================================================
# News Monitor — 一键部署脚本
# ============================================================================
# Usage:
#   ./deploy.sh              # 部署所有改动到 ECS + 重建容器
#   ./deploy.sh --no-build   # 只 scp 文件，不重建（小改动）
#   ./deploy.sh --check      # 部署后额外验证
# ============================================================================
set -euo pipefail

ECS_HOST="root@47.76.50.77"
ECS_PROJECT="/opt/news-monitor"
DOCKER_DIR="${ECS_PROJECT}/news-monitor/docker"

# ── Colors ───────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Flags ────────────────────────────────────────────────────────────────
BUILD=true; CHECK=false
for arg in "$@"; do
    case "$arg" in
        --no-build) BUILD=false ;;
        --check)    CHECK=true ;;
        *)          err "Unknown flag: $arg"; exit 1 ;;
    esac
done

# ── Step 1: Pre-flight ───────────────────────────────────────────────────
info "1/5  Pre-flight: git status + connectivity"
echo "     Branch: $(git branch --show-current)"
echo "     Last commit: $(git log -1 --oneline)"

if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$ECS_HOST" "echo ok" &>/dev/null; then
    err "Cannot SSH to ECS. Is the proxy on?"
    exit 1
fi
info "     SSH: OK"

# ── Step 2: Sync .env (if changed) ───────────────────────────────────────
info "2/5  Syncing .env → ECS"
if [ -f .env ]; then
    ECS_ENV_HASH=$(ssh "$ECS_HOST" "md5sum ${ECS_PROJECT}/.env 2>/dev/null | cut -d' ' -f1" || echo "none")
    LOCAL_ENV_HASH=$(md5sum .env | cut -d' ' -f1)
    if [ "$ECS_ENV_HASH" != "$LOCAL_ENV_HASH" ]; then
        scp .env "${ECS_HOST}:${ECS_PROJECT}/.env"
        info "     .env updated (hash changed)"
    else
        info "     .env unchanged, skip"
    fi
else
    warn "     No .env found locally, skip"
fi

# ── Step 3: Sync code files ──────────────────────────────────────────────
info "3/5  Syncing code → ECS"
FILES=(
    "news-monitor/engine/alert_dispatcher.py"
    "news-monitor/engine/deep_lane.py"
    "news-monitor/engine/fast_lane.py"
    "news-monitor/engine/priority.py"
    "news-monitor/engine/relevance.py"
    "news-monitor/engine/strategic_detector.py"
    "news-monitor/engine/impact_evaluator.py"
    "news-monitor/engine/impact_collector.py"
    "news-monitor/engine/impact_learner.py"
    "news-monitor/engine/learner.py"
    "news-monitor/engine/sentiment.py"
    "news-monitor/engine/cluster.py"
    "news-monitor/engine/curator.py"
    "news-monitor/bot/formatters.py"
    "news-monitor/bot/telegram_bot.py"
    "news-monitor/bot/handlers.py"
    "news-monitor/bot/translator.py"
    "news-monitor/bot/digest.py"
    "news-monitor/collector/scheduler.py"
    "news-monitor/collector/twitter_fetcher.py"
    "news-monitor/collector/chinese_fetcher.py"
    "news-monitor/collector/rss_fetcher.py"
    "news-monitor/collector/finnhub_fetcher.py"
    "news-monitor/collector/web_scraper.py"
    "news-monitor/config/sources.yaml"
    "news-monitor/config/settings.yaml"
    "news-monitor/config/keywords.yaml"
    "news-monitor/config/module_registry.json"
    "news-monitor/pipeline/item.py"
    "news-monitor/pipeline/ingest.py"
    "news-monitor/pipeline/screen.py"
    "news-monitor/pipeline/evaluate.py"
    "news-monitor/pipeline/dispatch.py"
    "news-monitor/pipeline/deep.py"
    "news-monitor/pipeline/channel.py"
    "news-monitor/pipeline/__init__.py"
    "news-monitor/main.py"
    "news-monitor/web/routes.py"
    "news-monitor/web/server.py"
    "news-monitor/web/auth.py"
    "news-monitor/storage/database.py"
    "news-monitor/storage/models.py"
    "news-monitor/storage/vector_store.py"
    "news-monitor/requirements.txt"
)

COPIED=0; SKIPPED=0
for f in "${FILES[@]}"; do
    if [ ! -f "$f" ]; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi
    local_md5=$(md5sum "$f" | cut -d' ' -f1)
    remote_md5=$(ssh "$ECS_HOST" "md5sum ${ECS_PROJECT}/${f} 2>/dev/null | cut -d' ' -f1" || echo "none")
    if [ "$local_md5" != "$remote_md5" ]; then
        scp "$f" "${ECS_HOST}:${ECS_PROJECT}/${f}"
        COPIED=$((COPIED + 1))
    fi
done
info "     ${COPIED} files copied, ${SKIPPED} missing, rest unchanged"

# ── Step 4: Docker rebuild ───────────────────────────────────────────────
if $BUILD; then
    info "4/5  Docker rebuild"
    ssh "$ECS_HOST" "cd ${DOCKER_DIR} && docker compose down && docker compose up -d --build 2>&1" | tail -3
else
    info "4/5  Docker rebuild SKIPPED (--no-build)"
fi

# ── Step 5: Health check ─────────────────────────────────────────────────
info "5/5  Health check"
for i in $(seq 1 12); do
    sleep 5
    STATUS=$(ssh "$ECS_HOST" "docker ps --filter name=news-monitor --format '{{.Status}}' 2>/dev/null")
    if echo "$STATUS" | grep -q "healthy"; then
        echo -e "     ${GREEN}✅ Container healthy — ${STATUS}${NC}"
        break
    fi
    echo "     Waiting... (${STATUS:-not found})"
done

if $CHECK; then
    info "Post-deploy verification"
    ssh "$ECS_HOST" "docker logs news-monitor --tail 20 2>&1" | grep -E 'Monitor running|ERROR|CRITICAL' || true
    echo -e "     Deep analysis: $(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 https://class1-cyan.vercel.app/api/news/212/analyze/result || echo 'N/A')"
fi

echo ""
info "Deploy complete. ${COPIED} files updated."
