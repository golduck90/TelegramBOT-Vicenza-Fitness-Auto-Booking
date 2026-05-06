# Vicenza Fitness Bot 🏋️

Bot Telegram per la prenotazione automatica dei corsi presso **Vicenza Fitness Company** (sistema WellTeam).

## Funzionalità

- 📅 **Prenotazione corsi** — naviga il calendario e prenota
- 🤖 **Auto-booking** — prenotazione automatica ogni settimana
- 🔄 **Retry intelligente** — se il server non risponde, riprova ogni ora (max 20 tentativi)
- 🔔 **Notifiche Telegram** — avvisi su esito prenotazione e promemoria 3h prima
- 🎫 **QR code** — codice per l'ingresso in palestra
- 📖 **Catalogo offline** — corsi visibili anche oltre la finestra di prenotazione

## Quick Start

```bash
# 1. Copia e configura le variabili d'ambiente
cp .env.example .env
# modifica .env con i tuoi token

# 2. Avvia il bot
make up

# 3. Controlla i log
make logs
```

## Configurazione

| Variabile | Obbligatoria | Descrizione |
|-----------|-------------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token del bot Telegram (da @BotFather) |
| `WELLTEAM_APP_TOKEN` | ✅ | Company-level token WellTeam |
| `LOG_LEVEL` | ❌ | Livello di log (default: INFO) |

## Comandi

```bash
make build    # Builda l'immagine Docker
make up       # Avvia il bot
make down     # Ferma il bot
make logs     # Log in tempo reale
make shell    # Shell nel container
make restart  # Ricostruisci e riavvia
```

## Architettura

```
bot-palestra/
├── main.py              # Entry point Telegram bot
├── config.py            # Configurazione (env vars)
├── db.py                # SQLite database layer
├── wellteam.py          # WellTeam API client
├── scheduler.py         # Auto-booking + retry
├── schedule_cache.py    # Cache calendario
├── course_catalog.py    # Catalogo offline corsi (JSON)
├── handlers/
│   ├── menu.py          # Menu principale
│   ├── auth.py          # Login/logout
│   ├── corsi.py         # Corsi, prenotazioni, auto-booking
│   ├── autobook.py     # Gestione auto-booking
│   ├── reminders.py     # Promemoria 3h/60min
│   ├── qr.py            # QR code ingresso
│   └── decorators.py    # Rate limit, auth decorators
└── Dockerfile           # Produzione (non-root, healthcheck)
```

## Tecnologie

- **Python 3.13** + python-telegram-bot v22.7
- **SQLite** (WAL mode, thread-safe)
- **Docker** (immagine slim, utente non-root)

## Licenza

Vedi file [LICENSE](LICENSE).
