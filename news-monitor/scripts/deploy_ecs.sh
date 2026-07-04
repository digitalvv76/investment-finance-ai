#!/bin/bash
# ============================================================
# News Monitor — Alibaba Cloud ECS 一键部署脚本
# ECS: 47.76.50.77
# 用法: SSH 到 ECS 后运行:  bash deploy.sh
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✔]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✘]${NC} $*"; exit 1; }

echo "============================================"
echo " News Monitor — 阿里云 ECS 部署"
echo "============================================"
echo ""

# ---- 1. 检测系统 ----
if [ -f /etc/os-release ]; then
    . /etc/os-release
    log "OS: $NAME $VERSION"
else
    err "无法检测操作系统"
fi

# ---- 2. 安装 Docker ----
if command -v docker &>/dev/null; then
    log "Docker 已安装: $(docker --version)"
else
    warn "正在安装 Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    log "Docker 安装完成"
fi

# 安装 docker-compose 插件
if docker compose version &>/dev/null; then
    log "Docker Compose 已安装"
else
    warn "正在安装 Docker Compose..."
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin 2>/dev/null || \
    yum install -y docker-compose-plugin 2>/dev/null || \
    ( curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" -o /usr/local/bin/docker-compose && chmod +x /usr/local/bin/docker-compose )
    log "Docker Compose 安装完成"
fi

# ---- 3. 克隆/更新项目 ----
APP_DIR="/opt/news-monitor"
if [ -d "$APP_DIR/.git" ]; then
    log "更新现有代码..."
    cd "$APP_DIR"
    git pull origin main
else
    log "克隆项目..."
    git clone https://github.com/digitalvv76/investment-finance-ai.git "$APP_DIR"
    cd "$APP_DIR"
fi

# ---- 4. 检查 .env ----
if [ ! -f ".env" ]; then
    err "缺少 .env 文件! 请先从本地 Windows 上传:
    在 Windows 终端 (cmd) 中运行:
      scp D:\\class1\\.env root@47.76.50.77:/opt/news-monitor/.env"
fi

# 快速验证关键变量存在
set +e
source <(grep -E '^(TELEGRAM_BOT_TOKEN|DEEPSEEK_API_KEY|WEB_USERNAME|WEB_PASSWORD)=' .env 2>/dev/null | sed 's/^/export /')
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    warn "TELEGRAM_BOT_TOKEN 未设置，Telegram Bot 将不可用"
fi
if [ -z "${WEB_USERNAME:-}" ]; then
    warn "WEB_USERNAME 未设置，Web Dashboard 将无密码保护!"
else
    log "WEB_USERNAME=${WEB_USERNAME}"
fi
set -e
log ".env 检查通过"

# ---- 5. 配置阿里云安全组 ----
echo ""
warn "============================================="
warn "  ⚠️  请确保阿里云安全组已开放以下端口:"
warn "     22   (SSH)"
warn "     8080 (Web Dashboard)"
warn "  ⚠️  配置路径: 阿里云控制台 → ECS → 安全组 → 入方向规则"
warn "============================================="
echo ""

# ---- 6. 构建并启动 ----
log "构建 Docker 镜像 (首次约 5-10 分钟)..."
cd "$APP_DIR"
docker compose -f news-monitor/docker/docker-compose.yml build --pull

log "启动容器..."
docker compose -f news-monitor/docker/docker-compose.yml up -d

# ---- 7. 等待启动 ----
log "等待服务启动..."
sleep 15

# ---- 8. 验证 ----
if docker compose -f news-monitor/docker/docker-compose.yml ps | grep -q "Up"; then
    log "容器运行中！"
else
    err "容器启动失败，检查日志: docker compose -f news-monitor/docker/docker-compose.yml logs"
fi

# 健康检查
if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    log "健康检查通过 ✅"
    curl -s http://localhost:8080/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8080/health
else
    warn "健康检查失败，等待更长时间..."
    sleep 30
    curl -sf http://localhost:8080/health && log "重试成功 ✅" || warn "请检查: docker compose -f news-monitor/docker/docker-compose.yml logs"
fi

# ---- 9. 完成 ----
IP=$(curl -s ifconfig.me 2>/dev/null || echo "47.76.50.77")
echo ""
echo "============================================"
echo -e " ${GREEN}部署完成!${NC}"
echo "============================================"
echo ""
echo "  Dashboard:  http://${IP}:8080"
echo "  用户名:     admin"
echo "  密码:       (你在 .env 中设置的 WEB_PASSWORD)"
echo ""
echo "  健康检查:   http://${IP}:8080/health"
echo "  查看日志:   docker compose -f /opt/news-monitor/news-monitor/docker/docker-compose.yml logs -f"
echo ""
echo -e " ${YELLOW}⚠️  首次访问会弹出浏览器登录框，输入以上用户名密码即可${NC}"
echo "============================================"
