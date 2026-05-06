# Code Review — Container Production Readiness

**Progetto:** bot-palestra (Vicenza Fitness Bot)
**Skill di riferimento:** `container-production` (devops)
**Data:** 2026-05-06
**Reviewer:** Hermes (con skill container-production)

---

## Riepilogo

| Categoria | Stato | Priorità |
|-----------|-------|----------|
| Dockerfile | ⚠️ 2 issue | Media |
| docker-compose.yml | 🔴 5 issue | Alta |
| .dockerignore | ⚠️ 3 issue | Media |
| .gitignore | ✅ Ok | — |
| Repository Structure | 🔴 8 mancanze | Alta |
| Documentazione | 🔴 4 mancanze | Alta |
| CI/CD | ❌ Assente | Media |
| .env.example | 🔴 Token reali esposti | **CRITICA** |
| Volume Docker | 🔴 Sovrascrive codice | **CRITICA** |

---

## 1. Dockerfile

### ✅ OK
- Immagine `python:3.13-slim`
- `WORKDIR /app` esplicito
- `--no-cache-dir` in pip
- `COPY requirements.txt` prima del codice (cache layer)
- Utente non-root (`botuser`)
- `chown -R` prima di `USER botuser`
- Sistema multi-stage ready

### ⚠️ Manca HEALTHCHECK
```dockerfile
# Il container non espone porte HTTP, ma si può usare:
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python3 -c "import os; os.kill(os.getpid(), 0)" || exit 1
```
Oppure, più elegante, verificare che il processo Python sia vivo con `pgrep`.

### ⚠️ Manca pulizia layer apt
Si potrebbe ridurre dimensione immagine con:
```dockerfile
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    sqlite3 qrencode tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean
```

---

## 2. docker-compose.yml

### ✅ OK
- `restart: unless-stopped`
- Variabili da `.env` con `${VAR}` pattern
- Named volume
- Container name esplicito

### 🔴 Volume montato su /app — SOVRASCRIVE IL CODICE
```yaml
volumes:
  - palestra_data:/app   # ❌ SOVRASCRIVE tutto il codice!
```
Il volume named `palestra_data` montato su `/app` fa sì che:
1. Build nuova immagine → codice nuovo non viene usato
2. Il volume vecchio (con codice vecchio) persiste e sovrascrive
3. Per aggiornare serve: `docker compose down -v && docker compose up -d`

**Fix:** Il volume va montato SOLO sulla directory dati:
```yaml
volumes:
  - palestra_data:/app/data   # Solo dati persistenti
```
Il codice nell'immagine non va sovrascritto.

### 🔴 Manca HEALTHCHECK
```yaml
healthcheck:
  test: ["CMD-SHELL", "pgrep -f 'python3 main.py' || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 15s
```

### 🔴 Manca resource limits
```yaml
deploy:
  resources:
    limits:
      cpus: "0.5"
      memory: "256M"
    reservations:
      cpus: "0.25"
      memory: "128M"
```

### 🔴 Nessuna rete isolata
Di default i container sono sulla rete `default` del compose. Per un bot che fa solo chiamate API in uscita non è grave, ma è buona pratica:
```yaml
networks:
  app-net:
    driver: bridge
```

### ⚠️ Tag `latest` implicito
```yaml
build: .    # Usa :latest di default
```
Meglio specificare un tag:
```yaml
image: vicenza-fitness-bot:${VERSION:-latest}
```

---

## 3. .dockerignore

### ✅ OK
- `__pycache__`, `*.pyc`
- `.git`, `.gitignore`
- `docker-compose.yml`
- `bot.log`

### ⚠️ Manca `.env`
Il file `.env` contiene TOKEN REALI. Deve essere nel `.dockerignore`:
```dockerignore
.env
```

### ⚠️ Manca `*.md`
I file markdown non servono nell'immagine:
```dockerignore
*.md
```

### ⚠️ Manca `.git/` — già presente ✅

### Vari finali
```dockerignore
__pycache__
*.pyc
.git
.gitignore
.env
.env.example
*.md
docker-compose.yml
docker-compose*.yml
bot.log
.DS_Store
CODE_REVIEW.md
```

---

## 4. .gitignore — ✅ OK

- `__pycache__/`, `*.pyc`
- `.env`, `.fernet_key`
- `palestra.db`, `bot_state.pickle`, `bot.log`
- `*.db-shm`, `*.db-wal`

Niente da aggiungere.

---

## 5. Repository Structure

### 🔴 Manca README.md
File più importante del repo — chiunque arrivi deve capire:
- Cosa fa il progetto
- Come avviarlo in 30 secondi
- Come configurarlo

### 🔴 Manca CHANGELOG.md
Chi mantiene deve sapere cosa è cambiato in ogni versione.

### 🔴 Manca LICENSE
Progetto open-source? Senza licenza, nessuno può legalmente usarlo.

### 🔴 Manca Makefile
Comandi frequenti (`make up`, `make logs`, `make build`) velocizzano il workflow.

### 🔴 Manca scripts/ directory
Script di utilità (backup, restore, healthcheck) non hanno una casa.

### 🔴 Manca docs/ directory
Documentazione extra (architettura, deploy) sparsa o assente.

### 🔴 Manca .github/workflows/ (CI/CD)
Nessun test automatico, build, deploy.

### ⚠️ Manca CONTRIBUTING.md
Linee guida per chi vuole contribuire.

**Struttura target:**
```
bot-palestra/
├── .env.example              ✅ (ma da ripulire)
├── .gitignore                ✅
├── .dockerignore             ⚠️ (da sistemare)
├── Dockerfile                ⚠️ (manca healthcheck)
├── docker-compose.yml        🔴 (volume bug)
├── Makefile                  ❌ MANCA
├── README.md                 ❌ MANCA
├── CHANGELOG.md              ❌ MANCA
├── LICENSE                   ❌ MANCA
├── scripts/
│   ├── backup.sh             ❌ MANCA
│   └── healthcheck.sh        ❌ MANCA
├── docs/
│   ├── architecture.md       ❌ MANCA
│   └── deployment.md         ❌ MANCA
└── .github/workflows/
    └── ci.yml                ❌ MANCA
```

---

## 6. .env.example — 🔴 CRITICO

### 🔴 Contiene TOKEN REALI
```env
TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN_RIMOSSO
WELLTEAM_APP_TOKEN=2AEAC60F19EF... (320 hex char)
```

Il file `.env.example` è PUBBLICO su GitHub. Contiene TOKEN REALI.

**Fix:**
```env
# Variabili d'ambiente richieste
TELEGRAM_BOT_TOKEN=         # Obbligatorio: token del bot Telegram
WELLTEAM_APP_TOKEN=         # Obbligatorio: company-level token WellTeam
LOG_LEVEL=INFO              # Opzionale: DEBUG, INFO, WARNING, ERROR
```

---

## 7. Volume Docker — 🔴 CRITICO

Il volume `palestra_data:/app` nell'attuale docker-compose.yml sovrascrive TUTTO il codice dell'immagine.

Ogni volta che l'immagine viene ricostruita con nuovo codice, il bot continua a usare il VECCHIO codice dal volume persistente.

**Fix:**
```yaml
volumes:
  - palestra_data:/app/data   # Solo dati, non codice!
```

---

## 8. Checklist Produzione (escluso monitoring/metriche)

| # | Requisito | Stato | Priorità |
|---|-----------|-------|----------|
| 1 | Dockerfile con utente non-root | ✅ | OK |
| 2 | Healthcheck su servizio | ❌ | Media |
| 3 | Resource limits CPU/RAM | ❌ | Media |
| 4 | Logging strutturato (JSON) | ❌ (plain text) | Bassa |
| 5 | Named volumes per dati persistenti | ⚠️ (ma montato male) | 🔴 Alta |
| 6 | `.env` separato + `.env.example` in git | ⚠️ (.env.example con token) | 🔴 Alta |
| 7 | Reverse proxy (non necessario per bot Telegram) | ✅ N/A | — |
| 8 | Backup automatico volumi | ❌ | Bassa |
| 9 | `restart: unless-stopped` | ✅ | OK |
| 10 | Immagini con tag specifico (non `:latest`) | ❌ | Bassa |
| 11 | README.md + CHANGELOG.md aggiornati | ❌ | Alta |
| 12 | CI/CD (test + build + deploy) | ❌ | Media |

---

## Azioni Raccomandate (ordine di priorità)

### 🔴 Fare SUBITO
1. **Pulire `.env.example`** — rimuovere token reali
2. **Fix volume docker-compose** — `palestra_data:/app` → `palestra_data:/app/data`
3. **Aggiungere `.env` al `.dockerignore`** — non deve finire nell'immagine

### 🟠 Fare PRESTO
4. **Creare `README.md`** — quick start, configurazione, struttura
5. **Creare `Makefile`** — build, up, logs, down, shell
6. **Aggiungere HEALTHCHECK** al Dockerfile e al docker-compose
7. **Aggiungere resource limits** al docker-compose

### 🟡 Quando possibile
8. **Aggiungere `.gitignore` per `*.md`** (non serve nell'immagine)
9. **Creare `CHANGELOG.md`** con storico modifiche
10. **Aggiungere CI/CD** (GitHub Actions: lint + test + build)
11. **Aggiungere `scripts/`** con backup.sh
12. **Aggiungere `LICENSE`**
