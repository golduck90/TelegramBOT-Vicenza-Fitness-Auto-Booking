FROM python:3.12-slim

WORKDIR /app

# Install system deps + timezone
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    sqlite3 \
    qrencode \
    tzdata \
    procps \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set timezone to Europe/Rome at OS level
ENV TZ=Europe/Rome
RUN ln -snf /usr/share/zoneinfo/Europe/Rome /etc/localtime && \
    echo "Europe/Rome" > /etc/timezone

# Copy requirements and install Python packages (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir "python-telegram-bot[job-queue,rate-limiter]>=20.0" && \
    pip install --no-cache-dir requests>=2.31.0 cryptography>=41.0.0

# Copy application code
COPY . .

# Run as non-root with persistent data directory
RUN useradd -m -u 1001 botuser && \
    chown -R botuser:botuser /app && \
    mkdir -p /app/data && \
    chown -R botuser:botuser /app/data
USER botuser

# Healthcheck: verifica che il processo Python sia vivo
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD pgrep -f 'python3 main.py' || exit 1

# Default: polling mode
ENTRYPOINT ["python3", "main.py"]
