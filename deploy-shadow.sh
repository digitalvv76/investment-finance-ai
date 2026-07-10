#!/usr/bin/env bash
# ============================================================================
# V2 Shadow — 一键部署到 ECS 影子容器 (不影响 V1 生产)
# ============================================================================
# Usage:
#   ./deploy-shadow.sh              # 部署 V2 代码 + 重建影子容器
#   ./deploy-shadow.sh --no-build   # 只 scp 文件
#   ./deploy-shadow.sh --logs       # 部署后 tail 影子日志
#   ./deploy-shadow.sh --down       # 停止并移除影子容器
# ============================================================================
set -euo pipefail

ECS_HOST="root@47.76.50.77"
ECS_PROJECT="/opt/news-monitor"
DOCKER_DIR="${ECS_PROJECT}/news-monitor/docker"

# ── Colors ───────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[SHADOW]${NC} $*"; }
warn()  { echo -e "${YELLOW}[SHADOW]${NC} $*"; }
err()   { echo -e "${RED}[SHADOW]${NC} $*"; }

# ── Flags ────────────────────────────────────────────────────────────────
BUILD=true; LOGS=false; DOWN=false
for arg in "$@"; do
    case "$arg" in
        --no-build) BUILD=false ;;
        --logs)     LOGS=true ;;
        --down)     DOWN=true ;;
        *)          err "Unknown flag: $arg"; exit 1 ;;
    esac
done

# ── Just down? ───────────────────────────────────────────────────────────
if $DOWN; then
    info "Stopping shadow container..."
    ssh "$ECS_HOST" "cd ${DOCKER_DIR} && docker compose -f docker-compose.yml -f docker-compose.shadow.yml down"
    info "Shadow container removed. V1 is unaffected."
    exit 0
fi

# ── Step 1: Pre-flight ───────────────────────────────────────────────────
info "1/4  Pre-flight"
echo "     Branch: $(git branch --show-current)"
echo "     Last commit: $(git log -1 --oneline)"

if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$ECS_HOST" "echo ok" &>/dev/null; then
    err "Cannot SSH to ECS."
    exit 1
fi
info "     SSH: OK"

# ── Step 2: Sync code ────────────────────────────────────────────────────
info "2/4  Syncing V2 code → ECS"
FILES=(
    # Engine
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
    "news-monitor/engine/event_matcher.py"
    "news-monitor/engine/event_escalator.py"
    "news-monitor/engine/market_snapshot.py"
    "news-monitor/engine/event_driven_evaluator.py"
    "news-monitor/engine/watchdog.py"
    "news-monitor/engine/entity_extractor.py"
    "news-monitor/engine/content_filter.py"
    "news-monitor/engine/actionability_review.py"
    "news-monitor/engine/trainer.py"
    # Bot
    "news-monitor/bot/formatters.py"
    "news-monitor/bot/telegram_bot.py"
    "news-monitor/bot/handlers.py"
    "news-monitor/bot/translator.py"
    "news-monitor/bot/digest.py"
    # Collector
    "news-monitor/collector/scheduler.py"
    "news-monitor/collector/rss_fetcher.py"
    "news-monitor/collector/twitter_fetcher.py"
    "news-monitor/collector/chinese_fetcher.py"
    "news-monitor/collector/finnhub_fetcher.py"
    "news-monitor/collector/web_scraper.py"
    "news-monitor/collector/dedup.py"
    "news-monitor/collector/api_fetcher.py"
    "news-monitor/collector/playwright_fetcher.py"
    # Config
    "news-monitor/config/loader.py"
    "news-monitor/config/sources.yaml"
    "news-monitor/config/settings.yaml"
    "news-monitor/config/keywords.yaml"
    "news-monitor/config/prompts/event_driven_v1.txt"
    "news-monitor/config/prompts/impact_v1.txt"
    "news-monitor/config/prompts/vlm_extract.txt"
    # Pipeline
    "news-monitor/pipeline/__init__.py"
    "news-monitor/pipeline/item.py"
    "news-monitor/pipeline/ingest.py"
    "news-monitor/pipeline/screen.py"
    "news-monitor/pipeline/evaluate.py"
    "news-monitor/pipeline/dispatch.py"
    "news-monitor/pipeline/deep.py"
    "news-monitor/pipeline/channel.py"
    # Storage
    "news-monitor/storage/database.py"
    "news-monitor/storage/models.py"
    "news-monitor/storage/vector_store.py"
    # Main + Web
    "news-monitor/main.py"
    "news-monitor/web/routes.py"
    "news-monitor/web/server.py"
    "news-monitor/web/auth.py"
    # Docker
    "news-monitor/docker/Dockerfile"
    "news-monitor/docker/docker-compose.shadow.yml"
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

# ── Step 3: Docker build shadow ──────────────────────────────────────────
if $BUILD; then
    info "3/4  Docker build shadow container"
    ssh "$ECS_HOST" "cd ${DOCKER_DIR} && docker compose -f docker-compose.yml -f docker-compose.shadow.yml up -d --build news-monitor-shadow 2>&1" | tail -5
else
    info "3/4  Docker SKIPPED (--no-build)"
fi

# ── Step 4: Health check ─────────────────────────────────────────────────
info "4/4  Health check"
for i in $(seq 1 12); do
    sleep 5
    STATUS=$(ssh "$ECS_HOST" "docker ps --filter name=news-monitor-shadow --format '{{.Status}}' 2>/dev/null")
    if echo "$STATUS" | grep -q "healthy"; then
        echo -e "     ${GREEN}✅ Shadow healthy — ${STATUS}${NC}"
        break
    fi
    echo "     Waiting... (${STATUS:-not found})"
done

# ── Optional: tail logs ──────────────────────────────────────────────────
if $LOGS; then
    info "Shadow logs (last 30 lines):"
    ssh "$ECS_HOST" "docker logs news-monitor-shadow --tail 30 2>&1"
fi

# ── Verify V1 still healthy ──────────────────────────────────────────────
V1_STATUS=$(ssh "$ECS_HOST" "docker ps --filter name=^news-monitor$ --format '{{.Status}}' 2>/dev/null")
if echo "$V1_STATUS" | grep -q "healthy"; then
    echo -e "     ${GREEN}✅ V1 production — ${V1_STATUS}${NC}"
else
    echo -e "     ${YELLOW}⚠️  V1 status: ${V1_STATUS:-NOT FOUND}${NC}"
fi

echo ""
info "Shadow deploy complete. ${COPIED} files updated."
info "Shadow: http://47.76.50.77:8081 | DRY_RUN mode (no real pushes)"
info "V1:     http://47.76.50.77:8080 | Production (real pushes)"
info ""
info "Monitor:  docker logs -f news-monitor-shadow"
info "Compare:  grep 'DRY_RUN WOULD-PUSH' → 对比 V1 实际推送"
info "Takedown: ./deploy-shadow.sh --down"
