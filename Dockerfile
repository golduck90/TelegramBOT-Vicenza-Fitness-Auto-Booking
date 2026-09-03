FROM python:3.12-slim

WORKDIR /app

# Install system deps + timezone
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    sqlite3 \
    qrencode \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set timezone to Europe/Rome at OS level
ENV TZ=Europe/Rome
RUN ln -snf /usr/share/zoneinfo/Europe/Rome /etc/localtime && \
    echo "Europe/Rome" > /etc/timezone

# Copy requirements and install Python packages (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code (only what's needed — see .dockerignore)
COPY . .

# Create non-root user and data directory
RUN useradd -m -u 1001 botuser && \
    mkdir -p /app/data && \
    chown -R botuser:botuser /app

USER botuser

# Healthcheck: verifica che il processo Python sia vivo
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD pgrep -f 'python3 main.py' || exit 1

# Default: polling mode
ENTRYPOINT ["python3", "main.py"]
