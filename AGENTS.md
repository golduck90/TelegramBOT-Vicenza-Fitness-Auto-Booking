# AGENTS.md — Guida per Agenti e Sviluppatori

## Panoramica Progetto

**Vicenza Fitness Bot** è un bot Telegram che automatizza le prenotazioni corsi presso Vicenza Fitness, palestra che usa il sistema WellTeam come backend. Il bot NON ha controllo sul server — interagisce solo via API REST.

### Architettura

```
Telegram Utente → Bot Python → API WellTeam (terze parti)
                     ↓
                 SQLite DB (locale)
                     ↓
              course_catalog.json (cache corsi)
```

### Stack Tecnologico
- **Python 3.12** su Docker
- **python-telegram-bot** v20+ (async)
- **SQLite** come database locale
- **requests** per chiamate API WellTeam
- **cryptography (Fernet)** per cifrare le password
- Docker Compose per deployment

---

## File Principali

| File | Responsabilità |
|------|---------------|
| `main.py` | Entry point, setup logging, registrazione handler, avvio scheduler |
| `config.py` | Caricamento config da env vars, chiave Fernet |
| `wellteam.py` | Client API WellTeam (authenticate, get_schedule, book, cancel, get_my_books) |
| `db.py` | Database layer SQLite (utenti, corsi, booking_log, auto_book_items, booking_reminders) |
| `scheduler.py` | Auto-booking notturno (00:10 Roma) + retry ogni ora |
| `schedule_cache.py` | Refresh catalogo corsi da API |
| `course_catalog.py` | Catalogo locale corsi su JSON (persistente oltre finestra VisibleDays) |
| `persistence.py` | SqlitePersistence per python-telegram-bot (stato conversazioni) |
| `handlers/menu.py` | Menu principale, info bot, help |
| `handlers/auth.py` | Login/logout WellTeam |
| `handlers/corsi.py` | Lista corsi, prenotazione, cancellazione, auto-booking setup |
| `handlers/autobook.py` | Gestione auto-booking (lista, toggle, rimuovi) |
| `handlers/reminders.py` | Reminder 3h e 60min prima del corso |
| `handlers/qr.py` | QR code ingresso (sticky UX) |
| `handlers/decorators.py` | Decoratori @require_auth, @rate_limit |
| `handlers/ratelimit.py` | Rate limiter sliding window |

---

## Database Schema

### Tabelle Principali

**users** — Utenti registrati
- `telegram_id` (PK), `username`, `encrypted_pass` (Fernet), `auth_token`, `app_token`
- `iyes_url`, `company_id`, `user_id`, `is_active`, `login_attempts`, `locked_until`

**auto_book_items** — Iscrizioni auto-booking
- `telegram_id` (FK), `service_id`, `description`, `day_of_week` (0=Lun 6=Dom)
- `start_time` (HH:MM), `end_time` (HH:MM), `instructor`
- `is_active`, `last_booked_lesson`, `last_booked_date`
- `retry_count`, `retry_error`, `retry_next_at`, `retry_notified`

**booking_reminders** — Reminder prenotazioni
- `telegram_id` (FK), `lesson_id`, `lesson_date` (YYYY-MM-DD), `start_time` (HH:MM)
- `course_name`, `instructor`
- `reminder_3h_sent`, `reminder_60m_sent`, `user_response` ('yes'/'no'/NULL)

**booking_log** — Log operazioni
- `telegram_id`, `service_desc`, `lesson_id`, `start_time`, `action` ('book'/'cancel'/'autobook')
- `success`, `message`

**course_catalog** — NON è nel DB, è un file JSON (`data/course_catalog.json`)

---

## API WellTeam

### Autenticazione
```
GET /security/authenticate?login={user}&password={pass}&companyid={id}
Headers: AppToken, IYESUrl
Response: { "Item": "AuthToken...", "Successful": true }
```

### Schedule Corsi
```
POST /webbooking/listwithmine
Body: { "CompanyID": 2, "Types": [], "StartDate": "...", "EndDate": "...", "TimeStart": "...", "TimeEnd": "..." }
Response: { "Items": [{ "IDServizio", "IDLesson", "DateLesson", "StartTime": "1900-01-01T19:00:00", "AvailablePlaces", "IsUserPresent", "ServiceDescription", "AdditionalInfo" }] }
```

**Nota formato StartTime**: L'API restituisce `"1900-01-01T19:00:00"` — data fittizia, l'ora reale è dopo la `T`. La data vera è in `DateLesson`.

### Prenotazioni Utente
```
GET /webbooking/mybooks?companyID=2&Type=
Response: { "Items": [{ "BookingID", "IDLesson", "StartTime", "EndTime", "ServiceDescription", "AdditionalInfo" }] }
```

### Prenota / Cancella
```
POST /webbooking/book
Body: { "BookingID": service_id, "IDLesson": lesson_id, "StartTime": "...", "EndTime": "...", "BookNr": 1 }

POST /webbooking/cancel
Body: { "BookingID": booking_id, "IDLesson": lesson_id, "StartTime": "...", "EndTime": "..." }
```

### Servizi (cambia con la stagione)
```
GET /webbooking/services?companyID=2
Response: { "Items": [{ "Description": "Prenotazioni 2026/2027", "VisibleDays": 4, "Tipologies": [{ "Id": 219, "Description": "All. Funzionale" }] }] }
```

---

## Concetti Chiave

### Service ID e Cambio Stagione
- Ogni corso ha un `service_id` (es. 219 per "All. Funzionale" nel 2026/2027)
- **Questi ID cambiano ad ogni cambio stagione** (es. 191 → 219)
- Le **descrizioni** dei corsi sono stabili tra le stagioni
- La chiave `(description, day_of_week, start_time)` è affidabile per il matching
- Il cambio stagione si rileva dalla `CategoryDescription` nell'API `/webbooking/services`

### VisibleDays
- Il server pubblica solo i prossimi **4 giorni** di corsi
- **Non è gestibile lato bot** — dipende dal server
- Il catalogo locale (`course_catalog.json`) serve per mostrare corsi oltre la finestra

### Password in Chiaro
- Le password sono cifrate con Fernet (chiave simmetrica) in `encrypted_pass`
- La chiave Fernet è in `/app/data/.fernet_key` (nel volume Docker)
- La password viene usata per il refresh automatico del token quando scade
- **Questo è un compromesso accettato** — necessario per l'auto-booking

### Timezone
- Tutto il bot usa `Europe/Rome` via `zoneinfo.ZoneInfo`
- Docker ha `TZ=Europe/Rome` settato
- SQLite salva datetime come stringhe (senza timezone)
- Lo scheduler usa `datetime.now(ROME_TZ)` per i calcoli

---

## Come Fare il Deploy

### Build e Avvio
```bash
cd /root/apk-work/bot-palestra
docker compose down
docker compose build
docker compose up -d
```

### Log
```bash
docker logs -f vicenza-fitness-bot --tail=100
```

### Accesso al DB
```bash
docker exec vicenza-fitness-bot sqlite3 /app/data/palestra.db "SELECT * FROM users;"
```

### Accesso al Container
```bash
docker exec -it vicenza-fitness-bot bash
```

---

## Piani di Sviluppo

Il piano completo è in `docs/PLAN-v2.0.md`. Le priorità sono:

1. **Fase 1** — Fix critici (reminder, cancellazione, cambio stagione)
2. **Fase 2** — Sincronizzazione con prenotazioni dall'app (reconciliation ogni 3 ore)
3. **Fase 3** — UX best practices (auto-delete, menu home, toast)
4. **Fase 4** — Affidabilità (coda notifiche, token refresh)
5. **Fase 5** — Sicurezza (ownership, log, dockerignore)

---

## Note per lo Sviluppo

### Testare Localmente
- Il bot può girare fuori Docker con `python3 main.py`
- Serve `.env` con `TELEGRAM_BOT_TOKEN` e `WELLTEAM_APP_TOKEN`
- Il DB viene creato in `data/palestra.db`

### Modifiche al DB
- Le migration sono in `db.py` (funzioni `_migrate_*`)
- Per aggiungere colonne: `ALTER TABLE ... ADD COLUMN`
- SQLite non supporta `DROP COLUMN` (usare recreate se necessario)

### Modifiche agli Handler
- Ogni handler ha una funzione `register(app)` che registra i handler
- L'ordine di registrazione in `main.py:register_all_handlers()` conta
- I callback pattern devono essere univoci

### Logging
- Logging strutturato JSON (formatter custom in `main.py`)
- Livello configurabile via `LOG_LEVEL` env var
- In Docker: stdout. Fuori Docker: file `bot.log`

### Rate Limiting
- `handlers/ratelimit.py` — sliding window per utente
- Default: 40 comandi/minuto per utente
- `AIORateLimiter` di python-telegram-bot per rate limit globale

---

## Problemi Noti

1. **Service ID cambiano ad ogni stagione** — serve migrazione automatica (vedi piano)
2. **Reminder non sempre arrivano** — `_verify_booking()` può eliminare reminder prematuramente
3. **Cancellazione mostra "meno di 60 min" erroneamente** — ricalcolo temporale sbagliato
4. **Nessuna sincronizzazione con app** — se prenoti dall'app, il bot non crea reminder
5. **Token refresh può fallire** — se la password cambia, il bot non può rinnovare il token

---

## Contatti

- **Server**: root@172.20.23.95
- **Container**: `vicenza-fitness-bot` (Docker)
- **DB**: `/root/apk-work/bot-palestra/palestra.db` (sul server) / `/app/data/palestra.db` (nel container)
- **Catalogo**: `/root/apk-work/bot-palestra/data/course_catalog.json`
- **Config**: `/root/apk-work/bot-palestra/.env`
- **Fernet Key**: `/root/apk-work/bot-palestra/.fernet_key` / `/app/data/.fernet_key` (nel container)
