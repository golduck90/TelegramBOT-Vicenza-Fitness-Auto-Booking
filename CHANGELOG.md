# Changelog

## [1.4.0] - 2026-05-06

### Fixed
- **M2**: `_get_conn()` privato → esposto `get_connection()` pubblico
- **M4**: Rimosso `cb_menu_home` dead code
- **M5**: `force_refresh` spostato in corsi.py (dov'è usato)
- **M6**: `app_token` non più sovrascritto ad ogni refresh token
- **M7**: Log warning su `_last_token_refresh` perso dopo restart
- **M8**: Security warning se `FERNET_KEY` è file-based (non env var)
- **M9**: `is_locked`/`lock_user` timezone-aware (UTC con timezone)
- **A1**: Rimosso tabella legacy `autobook_rules` + 6 funzioni morte
- **A2**: Aggiunto API rate limiter WellTeam (1 richiesta/secondo)
- **A3**: `_check_cache` e `cmd_prenotazioni` ora usano `asyncio.to_thread()`
- **A5**: `requests.Session` inizializzato eager (no race condition lazy init)
- **A8**: `busy_timeout=10000` + try/except su `OperationalError`
- **A6**: Creata infrastruttura test (`tests/` con 6 test case)

### Changed
- `README.md` — rimosse migliorie risolte, sezione "Problemi non fixabili" per H5
- `config.py` — aggiunto logging per sicurezza Fernet key
- `wellteam.py` — throttle API + session eager init
- `db.py` — `_LockedConnection` + `get_connection()` pubblico

## [1.3.0] - 2026-05-06

### Added
- Catalogo offline corsi su JSON (`course_catalog.json`) — giorni 🟠 visibili anche oltre finestra
- Giorni con semaforo 🟢🟡🟠 nella schermata prenotazione
- `course_catalog.py`: modulo per gestione catalogo persistente
- `container-production` skill per Docker/Compose/Repo best practices
- `docker-compose.yml` con healthcheck e resource limits
- `Makefile` con comandi frequenti (build, up, logs, shell)
- `README.md` con quick start e documentazione
- `REVIEW_CONTAINER.md` con audit produzione

### Fixed
- Timezone CEST hardcoded → `zoneinfo.ZoneInfo("Europe/Rome")` (DST automatico)
- `NameError` in `_confirm_autobook` — context mancante
- Token aziendale rimosso da hardcoded default → env var obbligatoria
- Volume Docker sovrascriveva codice (`/app` → `/app/data`)
- `.env.example` ora senza token reali (solo placeholder)
- `.dockerignore` esteso (`.env`, `*.md`, `CODE_REVIEW.md`)

### Security
- `WELLTEAM_APP_TOKEN` rimosso da `config.py` (era hardcoded)
- `.env` aggiunto a `.dockerignore`

## [1.2.0] - 2026-05-05

### Added
- Retry automatico su errori di rete/500 (max 20 tentativi, ogni ora)
- Notifiche Telegram su esito prenotazione (successo/errore/20 esauriti)
- Nuova navigazione: button Prenota full-width, rimosso "Solo Visualizzazione"
- Auto-booking chiede se prenotare subito quando posto disponibile
- `db.py`: colonne `retry_count`, `retry_error`, `retry_next_at`, `retry_notified`

### Fixed
- Bug date WellTeam API: `"1900-01-01T19:00:00"` malformato → formato ISO8601 corretto
- `Internal Server Error` su tutte le prenotazioni (era il bug date)

### Removed
- Button "Lista Corsi" separato (unito in "Prenota")
- Toggle "Solo Visualizzazione / Prenota"
- Button "Prenota solo questa volta"

## [1.1.0] - 2026-05-04

### Added
- Primo rilascio con autenticazione WellTeam
- Lista corsi con calendario settimanale
- Auto-booking ricorrente (Martedì/Giovedì All. Funzionale)
- QR code ingresso
- Promemoria 3h e 60min prima del corso
- Rate limiting per utente
