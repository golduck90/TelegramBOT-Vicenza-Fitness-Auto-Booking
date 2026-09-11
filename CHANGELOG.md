# Changelog

## [2.0.2] - 2026-09-11

### Fixed
- **Falso cambio istruttore "Giacomo → Giacomo"**: Lo scheduler ora normalizza (`strip().lower()`) i nomi degli istruttori prima di confrontarli. Se il nome è uguale dopo normalizzazione, non viene più inviata la notifica di cambio istruttore.
- **Cache corsi — perdita corsi oggi**: Il refresh del catalogo durante la giornata non cancella più i corsi di oggi già iniziati. Per il giorno corrente viene eseguito un merge (i corsi non più nell'API vengono mantenuti), per i giorni futuri il comportamento resta clear+replace.

### Changed
- **`course_catalog.py`**: Nuova funzione `get_courses_by_slot()` per cercare corsi per (description, day, time) indipendentemente dall'istruttore. Usata dal check proattivo cambio istruttore.
- **Refresh catalogo automatico su "Prenota"**: Ogni volta che un utente apre il menu "📅 Prenota", il bot esegue un refresh silenzioso dell'API. Se fallisce, usa la cache esistente senza mostrare errori.
- **Refresh notturno alle 00:10**: Lo scheduler ora esegue `refresh_all_users()` per tutti gli utenti attivi prima di processare gli auto-book items. Il catalogo viene aggiornato per tutti gli utenti in modo centralizzato.
- **Errori API — messaggi user-friendly**: Rimosso ogni bottone "🔄 Ricarica/Aggiorna calendario" dalla UI. In caso di errore API, il bot mostra un messaggio che suggerisce di verificare il funzionamento dell'app WellTeam.
- **`first_seen` preservato**: Quando un corso viene aggiornato nel catalogo, il campo `first_seen` originale viene mantenuto invece di essere sovrascritto.
- **Tracking `last_seen_api`**: Ogni entry del catalogo ora traccia il timestamp dell'ultimo aggiornamento dall'API, necessario per il cleanup automatico.

### New
- **Notifica proattiva cambio istruttore**: Ogni notte alle 00:10, dopo il refresh del catalogo, il bot confronta gli istruttori degli auto-book items attivi con quelli nel catalogo. Se un istruttore è cambiato, l'utente riceve una notifica immediata e l'auto-book item viene aggiornato nel DB. La prenotazione continuerà normalmente con il nuovo istruttore.
- **Cleanup corsi stale (>4 settimane)**: Nuova funzione `cleanup_stale_entries()` in `course_catalog.py`. I corsi non visti nell'API per oltre 4 settimane vengono rimossi dalla cache. Eseguito automaticamente ogni notte alle 00:10.
- **Alert corso non disponibile**: Se un utente ha auto-booking attivo e il corso non è disponibile nei prossimi 4 giorni (VisibleDays), riceve un alert settimanale (una volta per settimana ISO).
- **Pausa auto-booking per corsi eliminati**: Quando un corso viene rimosso dalla cache dopo 4 settimane, gli utenti con auto-book attivo ricevono una notifica e l'auto-book viene messo in pausa (non eliminato). L'utente potrà riattivarlo manualmente se il corso riprende.
- **`db.py`**: Nuova migration `last_alert_week` su `auto_book_items` e funzione `update_auto_book_alert_week()` per tracciare l'ultimo alert inviato per corso.

### Removed
- **Bottone "Ricarica calendario"**: Rimosso completamente dalla UI (schermata giorni, schermata giorno, errore corso non trovato). Il refresh avviene automaticamente aprendo "Prenota".
- **`cb_force_refresh`**: Funzione e handler rimossi da `handlers/menu.py` e `handlers/corsi.py`.

## [2.0.1] - 2026-09-10

### Fixed
- **Cambio stagione automatico**: Il sistema rileva ora automaticamente il cambio stagione (es. "Prenotazioni 2025/2026" → "Prenotazioni 2026/2027") e migra i `service_id` degli `auto_book_items` senza intervento manuale.
- **Duplicati catalogo corsi**: La chiave del catalogo ora usa `(description, day_of_week, start_time, instructor)` invece di `service_id`, che cambia ad ogni stagione. Stessi corsi da stagioni diverse non creano più voci duplicate.
- **Fallback matching scheduler**: Se un `service_id` non viene trovato (cambio stagione non ancora migrato), lo scheduler prova il match per `description + orario` e aggiorna automaticamente il `service_id` nel DB.
- **Cambio istruttore**: Se l'istruttore di un corso cambia, l'auto-book ora prenota comunque (match rilassato su `service_id + orario`), aggiorna l'istruttore nel DB e notifica l'utente. Prima il bot smetteva silenziosamente di prenotare.
- **Catalogo — refresh dinamico**: Quando l'API restituisce dati per un giorno, le entries esistenti di quel giorno vengono cancellate e sostituite con dati freschi. I giorni oltre la finestra VisibleDays mantengono il catalogo cached. Nessun VisibleDays hardcoded.
- **Catalogo — pulizia legacy**: Rimosse automaticamente le entries con chiave vecchia formato `service_id:day:time:instructor`.

### Changed
- **`course_catalog.py`**: Chiave catalogo basata su description (stabile tra stagioni). Aggiunto campo `_meta` per tracciare category e ultimo aggiornamento. Aggiunte funzioni `get_saved_category()`, `clear_catalog()`, `find_service_id_by_description()`, `remove_legacy_keys()`.
- **`schedule_cache.py`**: Ogni refresh recupera la category dall'API `/webbooking/services` e attiva la migrazione se necessario. Pulizia automatica chiavi legacy prima di ogni refresh.
- **`scheduler.py`**: Fallback su match per description in `_process_item()` e `_process_retry_item()`. Match rilassato per cambio istruttore con notifica utente.

### New
- **`season_migration.py`**: Modulo per rilevamento e migrazione automatica cambio stagione. `detect_season_change()`, `migrate_service_ids()`, `run_migration_if_needed()`.
- **`db.py`**: `update_auto_book_service_id()`, `update_auto_book_instructor()` e `get_all_auto_book_items()` per supporto migrazione.

## [2.0.0] - 2026-09-03

### Fixed
- **Reminder 3H**: Rimosso `_verify_booking()` prima dell'invio — il reminder viene sempre inviato. La verifica API avviene solo per il 60min.
- **Reminder cancellazione**: Se la prenotazione è stata cancellata (dall'app o da altri), il bot invia un messaggio informativo con dettagli invece di eliminare silenziosamente.
- **Cancellazione < 60min**: Fix logica — usa stato del reminder (`reminder_60m_sent`) invece di ricalcolo temporale con `datetime.now()`.
- **Service ID cambio stagione**: Aggiornati tutti gli `auto_book_items` da ID 191 (2025/2026) a 219 (2026/2027).
- **Orario Martedì**: Aggiornato da 19:00 a 18:00 (cambiato dal server).
- **Istruttore Giovedì**: Aggiornato da Giacomo a Marco (cambiato dal server).
- **Fernet key permissions**: Corretti permessi da 644 a 600 nel container.

### Changed
- **Catalogo corsi**: Ricostruito da zero con dati 2026/2027 (38 corsi). Rimosso catalogo vecchio 2025/2026.
- **Dockerfile**: Rimosso `procps` (non necessario), migliorata struttura, `.dockerignore` esteso.
- **`.dockerignore`**: Aggiunti `.fernet_key`, `backups/`, `tests/`, `*.db*`, `*.pickle`.
- **Versione bot**: Aggiunta versione `2.0.0` nel banner e nella sezione Info.

### New
- **`AGENTS.md`**: Guida completa per handoff progetto a nuovi agenti/sviluppatori.
- **`docs/PLAN-v2.0.md`**: Piano completo con tutti i fix, miglioramenti UX, e roadmap.
- **`scripts/backup.sh`**: Utility backup/restore con supporto tar.gz.
- **`vicenza-fitness-bot.service`**: Systemd service per gestione container.
- **`vicenza-fitness-bot-backup.timer`**: Systemd timer per backup automatico giornaliero.
- **Reconciliation periodico**: Pianificato ogni 3 ore per sincronizzare prenotazioni dall'app.
- **Rilevamento cambio stagione**: Pianificato per rilevare automaticamente il cambio `CategoryDescription`.

### Cleanup
- Rimossi 4 `booking_reminders` per lezioni passate (maggio 2026).
- Reset `last_booked_lesson` e `last_booked_date` su tutti gli `auto_book_items`.

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
- **L1**: Input validation su `service_id` da callback
- **L2**: Notifiche scheduler via `asyncio.run_coroutine_threadsafe()` (no più HTTP diretto)
- **L3**: Logging strutturato JSON (timestamp, level, logger, message)
- **L4**: Cache key timezone-safe (ZoneInfo Europe/Rome)
- **L6**: Python 3.13 → 3.12 (stabilità)
- **L7**: File logging solo fuori Docker (stdout in container)
- **L8**: PicklePersistence integrato in SQLite (`bot_persistence` table)
- **L10**: Rate limit su callback query handlers

### Changed
- `README.md` — rimosse migliorie risolte, sezione "Problemi non fixabili" per H5
- `config.py` — aggiunto logging per sicurezza Fernet key
- `wellteam.py` — throttle API + session eager init
- `db.py` — `_LockedConnection` + `get_connection()` pubblico + tabella `bot_persistence`
- `scheduler.py` — notifiche via application.bot
- `main.py` — JSON logging + SqlitePersistence
- `Dockerfile` — python 3.12

### New
- `persistence.py` — SqlitePersistence (salva stato bot in SQLite)
- `tests/__init__.py`, `tests/test_db.py`

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
