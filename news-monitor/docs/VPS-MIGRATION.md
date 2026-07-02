# VPS Migration Guide — Financial News Monitor

Step-by-step guide to deploy the News Monitor on a Linux VPS (Ubuntu 22.04+ recommended).

## Prerequisites

- VPS with 2+ GB RAM, 20+ GB disk
- Ubuntu 22.04 or Debian 12 (other Linux distros work with minor adjustments)
- Domain or static IP (optional — Telegram Bot uses outbound polling)
- Git installed

## Option A: Docker (Recommended)

### 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group to take effect
```

### 2. Clone & Configure

```bash
git clone https://github.com/digitalvv76/investment-finance-ai.git
cd investment-finance-ai/news-monitor
```

### 3. Set Environment Variables

```bash
# Required
export TELEGRAM_BOT_TOKEN="your_bot_token_here"

# Optional (enables LLM deep analysis)
export ANTHROPIC_API_KEY="your_anthropic_key"

# Optional (enables FRED economic calendar)
export FRED_API_KEY="your_fred_key"

# Optional (enables Alpha Vantage data)
export ALPHA_VANTAGE_API_KEY="your_av_key"
```

Add these to `/etc/environment` or a `.env` file for persistence:

```bash
# Create .env file
cat > .env << EOF
TELEGRAM_BOT_TOKEN=your_bot_token_here
ANTHROPIC_API_KEY=your_anthropic_key
FRED_API_KEY=your_fred_key
ALPHA_VANTAGE_API_KEY=your_av_key
EOF
```

### 4. Start

```bash
# Build and start
docker compose -f docker/docker-compose.yml up -d --build

# Check status
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f
```

### 5. Verify

Send `/status` to your Telegram bot. Should respond with "News Monitor Running".

---

## Option B: Bare Metal

### 1. Install Dependencies

```bash
# System packages
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip git curl

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Python packages
pip install -r requirements.txt

# spaCy model
python -m spacy download en_core_web_sm

# Playwright
playwright install --with-deps chromium
```

### 2. Set Environment Variables

Same as Docker section above. Add to `~/.bashrc` or use a `.env` file.

### 3. Run as systemd Service

Create `/etc/systemd/system/news-monitor.service`:

```ini
[Unit]
Description=Financial News Monitor
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/investment-finance-ai/news-monitor
EnvironmentFile=/home/ubuntu/investment-finance-ai/news-monitor/.env
ExecStart=/home/ubuntu/investment-finance-ai/news-monitor/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable news-monitor
sudo systemctl start news-monitor
sudo systemctl status news-monitor
```

### 4. Log Management

```bash
# View logs
journalctl -u news-monitor -f

# Log files
tail -f logs/news_monitor.log
```

Configure logrotate to prevent disk fill:

```bash
# /etc/logrotate.d/news-monitor
/home/ubuntu/investment-finance-ai/news-monitor/logs/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    maxsize 50M
}
```

---

## Firewall

No inbound ports needed — the monitor uses outbound connections only:

| Outbound | Destination | Purpose |
|----------|------------|---------|
| TCP 443 | api.telegram.org | Telegram Bot API |
| TCP 443 | api.anthropic.com | LLM analysis (optional) |
| TCP 443 | Various news sites | RSS/Playwright collection |
| TCP 443 | api.stlouisfed.org | FRED data (optional) |

```bash
# UFW (if enabled)
sudo ufw allow out 443/tcp
```

---

## Health Monitoring

### Check if the process is running

```bash
# systemd
sudo systemctl is-active news-monitor

# Docker
docker compose -f docker/docker-compose.yml ps

# Process
ps aux | grep main.py
```

### Telegram Bot Health

Send `/status` to your bot. Expected response includes article counts and uptime.

### Database Size Watch

```bash
# SQLite DB size
ls -lh data/news.db

# Vacuum periodically (cron weekly)
0 3 * * 0 sqlite3 /path/to/data/news.db "VACUUM;"
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Bot doesn't respond | `TELEGRAM_BOT_TOKEN` is set and valid |
| No news collected | Internet connectivity, check `logs/news_monitor.log` |
| Playwright errors | Run `playwright install --with-deps chromium` |
| DB locked | Only one instance running; stop duplicates |
| High CPU | Check Playwright sources; reduce heartbeat frequency in `config/settings.yaml` |
| Disk full | Check log rotation; verify `logs/` size |

---

## Upgrading

```bash
# Docker
cd investment-finance-ai/news-monitor
git pull
docker compose -f docker/docker-compose.yml up -d --build

# Bare metal
cd investment-finance-ai/news-monitor
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart news-monitor
```
