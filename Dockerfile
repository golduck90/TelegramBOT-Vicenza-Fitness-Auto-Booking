FROM python:3.13-slim

WORKDIR /app

# Install system deps: sqlite3 + qrencode CLI tool
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    sqlite3 \
    qrencode \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir "python-telegram-bot[job-queue,rate-limiter]>=20.0" && \
    pip install --no-cache-dir requests>=2.31.0 cryptography>=41.0.0

# Copy application code
COPY . .

# Run as non-root
RUN useradd -m -u 1001 botuser && chown -R botuser:botuser /app
USER botuser

# Default: polling mode
ENTRYPOINT ["python3", "main.py"]
