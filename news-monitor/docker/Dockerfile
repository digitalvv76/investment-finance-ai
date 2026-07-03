# Financial News Monitor — Docker Image
# Build:  docker build -t news-monitor -f docker/Dockerfile .
# Run:    docker-compose -f docker/docker-compose.yml up -d
#
# Deploy to any cloud server that runs Docker:
#   1. Copy the news-monitor/ directory to the server
#   2. Create .env file with your API keys
#   3. docker compose -f docker/docker-compose.yml up -d

FROM python:3.12-slim

LABEL org.opencontainers.image.title="Financial News Monitor"
LABEL org.opencontainers.image.description="24/7 financial news collection, analysis, and Telegram alerts"
LABEL org.opencontainers.image.version="1.0"

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for Playwright + Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libu2f-udev \
    libxcomposite1 \
    libxdamage1 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (saves ~2GB vs CUDA version)
# sentence-transformers depends on torch but we don't need GPU for inference
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install spaCy model
RUN python -m spacy download en_core_web_sm

# Install Playwright Chromium (with system deps already installed above)
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

# Create data directories (mounted as volumes at runtime, but created here as fallback)
RUN mkdir -p data logs

# Default WEB_PORT — enables the web dashboard inside the container
ENV WEB_PORT=8080

# Health check: verify the main module is importable and DB is accessible
HEALTHCHECK --interval=300s --timeout=15s --start-period=60s --retries=3 \
    CMD python -c "import sys; sys.path.insert(0,'.'); from storage.database import Database; db = Database('data/news.db'); db.init_db(); print('OK')" || exit 1

CMD ["python", "main.py"]
