# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm AS builder

WORKDIR /app

# Copia prima requirements.txt per sfruttare la cache
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip

# ── Stage 2: Runtime ─────────────────────────────────────
FROM python:3.13-slim-bookworm AS runtime

WORKDIR /app

# Label OCI standard
LABEL org.opencontainers.image.title="Vicenza Fitness Bot"
LABEL org.opencontainers.image.description="Bot Telegram per prenotazioni WellTeam"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.source="https://github.com/golduck90/vicenza-fitness-bot"
LABEL org.opencontainers.image.licenses="MIT"

# Copia i pacchetti Python dallo stage builder
COPY --from=builder /root/.local /root/.local

# Crea utente non-root per sicurezza (OWASP RULE #2)
RUN addgroup --system --gid 1001 app && \
    adduser --system --uid 1001 --gid 1001 app

# Copia il codice applicativo (dopo aver creato l'utente per avere permessi corretti)
COPY --chown=app:app . .

# Rendi la directory dati scrivibile (per DB, log, pickle, fernet key)
RUN mkdir -p /app/data && chown app:app /app/data

# Passa a utente non-root
USER app

# Volume per dati persistenti
VOLUME /app/data

# Healthcheck: verifica che il processo Python sia vivo
HEALTHCHECK --interval=60s --timeout=5s --start-period=15s --retries=3 \
  CMD pgrep -f 'python3 main.py' || exit 1

# Comando di avvio
CMD ["python3", "main.py"]
