# Financial News Monitor — Docker Image
# Build: docker build -t news-monitor -f docker/Dockerfile .
# Run: docker-compose -f docker/docker-compose.yml up -d

FROM python:3.12-slim

LABEL org.opencontainers.image.title="Financial News Monitor"
LABEL org.opencontainers.image.description="24/7 financial news collection, analysis, and Telegram alerts"
LABEL org.opencontainers.image.version="1.0"

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install spaCy model
RUN python -m spacy download en_core_web_sm

# Install Playwright Chromium
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p data logs

# Expose nothing — all communication is outbound (Telegram API, news sources)
# Health check: verify main.py can import
HEALTHCHECK --interval=300s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sys; sys.path.insert(0,'.'); from main import NewsMonitor; print('OK')" || exit 1

CMD ["python", "main.py"]
