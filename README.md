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

## 🛠️ Migliorie in sospeso

Mantenute dal code review (`CODE_REVIEW.md`) e dall'audit produzione (`REVIEW_CONTAINER.md`) — consolidate qui.

### 🔴 Critiche — Da fare SUBITO
| # | Problema | Impatto |
|---|----------|---------|
| C2 | Timezone CEST hardcoded in scheduler (v1.3 fix) | ✅ RISOLTO — zoneinfo attivo |
| C3 | Confronto naive/aware datetime in scheduler | ✅ RISOLTO — now_rome usato ovunque |
| C4 | Token esposto in git history | ✅ RISOLTO — env var obbligatoria |
| C5 | Dead code login headers | ✅ RISOLTO — rimosso |
| — | Volume `/app` sovrascriveva codice | ✅ RISOLTO — `/app/data` |
| — | `.env.example` con token reali | ✅ RISOLTO — solo placeholder |

### 🟠 Importanti — Da fare PRESTO
| # | Problema | Dettaglio |
|---|----------|-----------|
| H1 | `bookings.py` mai importato (dead code) | 206 righe morte. Rimuovere o integrare. |
| H2 | `courses.py` mai importato (dead code) | 130 righe morte. `/calendario` irraggiungibile. |
| H3 | SQLite senza lock esplicito | `_db_lock` definito mai usato. 3 thread scrivono concorrentemente. |
| H4 | Rate limiter non thread-safe | `_user_timestamps` condiviso senza lock. |
| H5 | Password in query params HTTP | GET login → password in access log. Usare POST. |
| H6 | `application.loop` fragile | API interna ptb, potrebbe sparire in v23+. |
| H7 | `last_booked_date` potrebbe non matchare | Se utente prenota manualmente un altro slot stesso giorno, retry si ferma. |
| H8 | `authenticate` non valida token | Login OK ma token potrebbe non funzionare. |

### 🟡 Medie — Migliorie
| # | Problema | Dettaglio |
|---|----------|-----------|
| M2 | Accesso a `db._get_conn()` come privato | Da esporre metodo pubblico `get_connection()`. |
| M4 | `cb_menu_home` dead code | Definita ma mai registrata. |
| M5 | `force_refresh` fragile cross-file | Registrato in menu.py ma chiamato da corsi.py. |
| M6 | `app_token` sovrascritto con company token | Ogni refresh token sovrascrive. Naming confuso. |
| M7 | `_last_token_refresh` non persistito | In-memory only, perso su restart. |
| M8 | Password decifrabili con chiave su disco | .fernet_key leggibile da chi ha accesso al filesystem. |
| M9 | `is_locked` confronta datetime naive | `utcnow()` e `fromisoformat()` sono naive. |
| — | `docker-compose.yml` attributo `version:` obsoleto | ✅ RISOLTO — rimosso. |

### 🔵 Future — Backlog
| # | Idea | Priorità |
|---|------|----------|
| L1 | Input validation su `service_id` da callback | Bassa |
| L2 | Notifiche via `application.bot.send_message()` invece di HTTP diretto | Bassa |
| L3 | Logging strutturato JSON (invece di plain text) | Bassa |
| L4 | Cache key timezone-safe | Bassa |
| L6 | Python 3.11/3.12 invece di 3.13 per stabilità | Bassa |
| L7 | Logging su stdout per Docker | Bassa |
| L8 | PicklePersistence fuori dall'immagine | Bassa |
| L9 | `_check_cache` blocca event loop | Bassa |
| L10 | Rate limit su callback query | Bassa |

### 🏗️ Note Architetturali
| # | Nota |
|---|------|
| A1 | Due sistemi auto-booking (legacy `autobook_rules` + nuovo `auto_book_items`). Rimuovere legacy. |
| A2 | Tre thread concorrenti su DB e API senza coordinazione. |
| A3 | `requests` sincrono blocca event loop. Migrare a `httpx.AsyncClient`. |
| A4 | Token management frammentato su 3 file. Centralizzare in `TokenManager`. |
| A5 | `requests.Session` globale con race condition in lazy init. |
| A6 | Zero test. Nessun file `tests/`. |
| A7 | Nessun CI/CD. |
| A8 | `busy_timeout=5000` senza exception handling su timeout. |

## ✅ Checklist Produzione

| # | Requisito | Stato |
|---|-----------|-------|
| 1 | Dockerfile con utente non-root | ✅ |
| 2 | Healthcheck su servizio | ✅ (Dockerfile + compose) |
| 3 | Resource limits CPU/RAM | ✅ (0.5 CPU, 256M RAM) |
| 4 | Named volumes per dati persistenti | ✅ (`/app/data`) |
| 5 | `.env` separato + `.env.example` ripulito | ✅ |
| 6 | `restart: unless-stopped` | ✅ |
| 7 | README.md + CHANGELOG.md | ✅ |
| 8 | Makefile | ✅ |
| 9 | Backup automatico volumi | ❌ Da fare |
| 10 | CI/CD (GitHub Actions) | ❌ Da fare |
| 11 | Licenza (LICENSE) | ❌ Da fare |
| 12 | Logging strutturato JSON | ❌ Da fare |
| 13 | Script backup/restore | ❌ Da fare |

## 📜 Storico

Vedi [CHANGELOG.md](CHANGELOG.md) per il dettaglio delle versioni.
