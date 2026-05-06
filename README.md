# Vicenza Fitness Bot 🏋️

Bot Telegram per la prenotazione automatica dei corsi presso **Vicenza Fitness Company** (sistema WellTeam).

## ✨ Funzionalità

| Funzione | Stato | Descrizione |
|----------|-------|-------------|
| 📅 Prenotazione corsi | ✅ | Naviga calendario settimanale, prenota con 1 click |
| 🤖 Auto-booking | ✅ | Prenotazione automatica ogni settimana (notte alle 00:10) |
| 🔄 Retry intelligente | ✅ | Se il server non risponde, riprova ogni ora (max 20 tent.) |
| 🔔 Notifiche Telegram | ✅ | Avvisi su esito prenotazione, errori, retry |
| 🎫 QR code | ✅ | Codice per ingresso palestra |
| 📖 Catalogo offline | ✅ | Corsi visibili anche oltre la finestra di prenotazione |
| 🕐 Promemoria | ✅ | 3h e 60min prima del corso |
| 🔐 Login guidato | ✅ | Conversazione guidata username/password |
| 🟢🟡🟠 Semaforo giorni | ✅ | Disponibile / In arrivo / Solo catalogo |
| 📊 Statistiche bot | ✅ | Utenti, prenotazioni, corsi attivi |

## 🚀 Quick Start

```bash
# 1. Prepara le variabili d'ambiente
cp .env.example .env
# Modifica .env con i token (vedi docs/TOKENS.md per il token WellTeam)

# 2. Builda e avvia
make up

# 3. Controlla i log
make logs
```

## ⚙️ Configurazione

| Variabile | Obbligatoria | Default | Descrizione |
|-----------|-------------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Token del bot Telegram (da @BotFather) |
| `WELLTEAM_APP_TOKEN` | ✅ | — | Token company-level WellTeam — vedi `docs/TOKENS.md` |
| `LOG_LEVEL` | ❌ | `INFO` | DEBUG, INFO, WARNING, ERROR |
| `ADMIN_IDS` | ❌ | — | ID Telegram admin (separati da virgola) |
| `AUTOBOOK_CHECK_INTERVAL` | ❌ | `30` | Intervallo check scheduler (minuti) |

## 📋 Comandi

### Makefile

```bash
make build     # Builda l'immagine Docker
make up       # Avvia il bot in background
make down     # Ferma e rimuove il container
make logs     # Log in tempo reale
make shell    # Apre una shell nel container
make restart  # Ricostruisce e riavvia
make clean    # Pulisce container, volumi, immagini
make help     # Mostra comandi disponibili
```

### Telegram

| Comando | Descrizione |
|---------|-------------|
| `/start` | 🏠 Menu principale |
| `/login` | 🔐 Accedi con WellTeam (o `/login <user> <pass>`) |
| `/logout` | 🚪 Esci e cancella dati |
| `/qr` | 🎫 QR Code ingresso |
| `/prenota` | 📅 Prenota un corso |
| `/corsi` | 📋 Lista corsi |
| `/autobook` | 🤖 Prenotazioni automatiche |
| `/prenotazioni` | 📅 Le mie prenotazioni |
| `/help` | ❓ Aiuto |

## 🏗️ Architettura

```
bot-palestra/
├── main.py               # Entry point Telegram bot + banner avvio
├── config.py              # Configurazione (env vars)
├── db.py                  # SQLite database (WAL mode)
├── wellteam.py            # WellTeam API client (requests)
├── scheduler.py           # Auto-booking notturno + retry intelligente
├── schedule_cache.py      # Cache calendario settimanale
├── course_catalog.py      # Catalogo offline corsi (JSON)
├── handlers/
│   ├── __init__.py
│   ├── menu.py            # Menu principale (pre/post login)
│   ├── auth.py            # Login/logout guidato
│   ├── corsi.py           # Corsi, prenotazioni, auto-booking UI
│   ├── autobook.py        # Gestione iscrizioni auto-booking
│   ├── reminders.py       # Promemoria 3h/60min prima del corso
│   ├── qr.py              # QR code ingresso palestra
│   ├── decorators.py      # Rate limit, require_auth decorators
│   └── ratelimit.py       # Rate limiter per utente
├── docs/
│   └── TOKENS.md          # Raccolta APPTOKEN WellTeam
├── Dockerfile             # Immagine production (non-root, HEALTHCHECK)
├── docker-compose.yml     # Container con healthcheck + resource limits
├── requirements.txt       # Dipendenze Python
├── .env.example           # Template variabili d'ambiente
├── Makefile               # Comandi frequenti
├── CHANGELOG.md           # Storico versioni
└── README.md              # Questo file
```

## 🧱 Tecnologie

- **Python** 3.13-slim (Docker)
- **python-telegram-bot** v22.7 (con AIORateLimiter)
- **SQLite** (WAL mode, busy_timeout=5000, Fernet encryption password)
- **Docker** (utente non-root, HEALTHCHECK, resource limits)
- **requests** (API WellTeam)
- **cryptography** (Fernet per password cifrate)

## 🛠️ Storico Migliorie

Tutte le migliorie identificate sono state risolte. Vedi sotto per l'unico
problema non fixabile perché dipende da backend di terzi.

### ⏸️ Problemi non fixabili (backend di terzi)

| # | Problema | Dettaglio | Motivo |
|---|----------|-----------|--------|
| H5 | Password in query params HTTP | GET login → password in `access.log` del server WellTeam. | Il backend .NET di WellTeam richiede la chiamata GET con `password` in query params. Non possiamo modificare il loro server. Best practice violata ma inevitabile. |

### 🔵 Future — Backlog

| # | Idea | Priorità |
|---|------|----------|
| A7 | CI/CD (GitHub Actions) | Media |

## ✅ TODO Checklist

Tutto risolto ✅ — il progetto è pronto per pubblicazione.

| # | Requisito | Stato |
|---|-----------|-------|
| 1 | Dockerfile con utente non-root | ✅ |
| 2 | Healthcheck su servizio | ✅ |
| 3 | Resource limits CPU/RAM | ✅ |
| 4 | Named volumes per dati persistenti | ✅ |
| 5 | `.env` separato + `.env.example` pulito | ✅ |
| 6 | `restart: unless-stopped` | ✅ |
| 7 | README.md + CHANGELOG.md | ✅ |
| 8 | Makefile | ✅ |
| 9 | Secreti rimossi dalla git history | ✅ |
| 10 | Licenza GPL v3 | ✅ |
| 11 | CI/CD (GitHub Actions) | ❌ Futuro |

## 📜 Storico

Vedi [CHANGELOG.md](CHANGELOG.md) per il dettaglio delle versioni.
