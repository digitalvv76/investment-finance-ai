# Financial News Monitor

24/7 financial news monitoring with Telegram alerts and AI-powered deep analysis.

## Architecture

```
📡 Collection         🧠 Analysis              📲 Delivery         📚 Learning
RSS (7 sources)  →   Entity Extraction    →   Telegram Alerts  →   Feedback Loop
Playwright (3)   →   Sentiment (VADER)    →   Fast Lane (<5s)  →   Source Weights
API Triggers     →   Priority Scoring     →   Deep Lane (LLM)  →   Threshold Tuning
                      Event Clustering    →   Daily Digest     →   Personal Dict
                      Dedup (URL+Content+Semantic)
```

## Quick Start

```bash
# Install
pip install -r requirements.txt
python -m spacy download en_core_web_sm
playwright install chromium

# Configure
set TELEGRAM_BOT_TOKEN=your_bot_token          # Windows
export TELEGRAM_BOT_TOKEN=your_bot_token       # Linux/Mac
# Optional: set ANTHROPIC_API_KEY for LLM analysis

# Run
python main.py
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/status` | System stats (24h news, fast/deep counts) |
| `/filter add/remove <ticker>` | Manage ticker watchlist |
| `/filter list` | Show current filters |
| `/mute <ticker> <hours>` | Temporarily mute a ticker |
| `/prefs` | View all preferences |
| `/daily` | Generate daily digest |
| `/help` | Command reference |

## Production Deployment

### Windows Service (NSSM)

```bash
# Install NSSM
winget install nssm

# Install as service (run as Administrator)
python scripts/install_service.py install

# Manage
nssm start NewsMonitor
nssm stop NewsMonitor
python scripts/install_service.py status
```

### Docker

```bash
# Build and start
docker compose -f docker/docker-compose.yml up -d --build

# View logs
docker compose -f docker/docker-compose.yml logs -f

# Stop
docker compose -f docker/docker-compose.yml down
```

### Linux VPS (systemd)

See [docs/VPS-MIGRATION.md](docs/VPS-MIGRATION.md) for complete guide.

## Configuration

All settings in `config/settings.yaml`:

| Setting | Default | Description |
|---------|---------|-------------|
| `frequencies.heartbeat` | 60s | Breaking news check interval |
| `frequencies.fast` | 300s | Tier 2 source interval |
| `frequencies.normal` | 900s | RSS source interval |
| `weekend_multiplier` | 3x | Frequency multiplier on weekends |
| `fast_lane.multi_source_count` | 3 | Sources needed for resonance |
| `deep_lane.llm_model` | claude-fable-5 | Model for deep analysis |
| `thresholds.urgent_priority` | 0.7 | Auto LLM trigger |
| `thresholds.important_priority` | 0.4 | On-demand LLM trigger |

Sources in `config/sources.yaml`. Keywords in `config/keywords.yaml`.

## Testing

```bash
# All tests
python -m pytest tests/ -v

# Specific module
python -m pytest tests/test_fast_lane.py -v

# With coverage
pip install pytest-cov
python -m pytest tests/ --cov=. --cov-report=html
```

107 tests, 90 pass + 7 skipped (ChromaDB optional).

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram Bot API token |
| `ANTHROPIC_API_KEY` | No | LLM deep analysis |
| `FRED_API_KEY` | No | Economic calendar |
| `ALPHA_VANTAGE_API_KEY` | No | Stock fundamentals |
