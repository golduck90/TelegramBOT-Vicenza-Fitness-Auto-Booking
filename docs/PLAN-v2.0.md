# Piano Completo — Vicenza Fitness Bot v2.0

## Indice

1. [Contesto e Vincoli](#1-contesto-e-vincoli)
2. [Bug Critici da Fixare](#2-bug-critici-da-fixare)
3. [Cambio Stagione — Rilevamento e Migrazione Automatica](#3-cambio-stagione--rilevamento-e-migrazione-automatica)
4. [Sincronizzazione con Prenotazioni dall'App](#4-sincronizzazione-con-prenotazioni-dallapp)
5. [UX Best Practices — Pulizia Chat e Interazione](#5-ux-best-practices--pulizia-chat-e-interazione)
6. [Miglioramenti Affidabilità](#6-miglioramenti-affidabilità)
7. [Miglioramenti Sicurezza](#7-miglioramenti-sicurezza)
8. [Ordine di Implementazione](#8-ordine-di-implementazione)
9. [Testing](#9-testing)

---

## 1. Contesto e Vincoli

### Contesto

- Bot Telegram che semplifica l'uso dell'app WellTeam di Vicenza Fitness
- Il backend WellTeam è di terze parti — **nessuna modifica lato server**
- Il server pubblica solo i prossimi **4 giorni** di corsi (`VisibleDays: 4`)
- I `service_id` cambiano ad ogni cambio stagione es. "Prenotazioni 2025/2026" → "Prenotazioni 2026/2027"
- Le **descrizioni dei corsi sono stabili** tra le stagioni (verificato)
- La combinazione `(description, day_of_week, start_time)` è univoca e affidabile per il matching

### Vincoli

- Solo chiamate API REST verso WellTeam (GET/POST)
- Password salvata in locale per auto-refresh token (necessario, accettato)
- Docker su server Linux con TZ=Europe/Rome
- SQLite come database locale

### API WellTeam — Endpoint Principali

| Endpoint | Metodo | Uso |
| ---------- | -------- | ----- |
| `/security/authenticate` | GET | Login → restituisce AuthToken |
| `/webuser/me` | GET | Info utente (valida token) |
| `/webbooking/services` | GET | Lista corsi/tipologie (cambia con la stagione) |
| `/webbooking/listwithmine` | POST | Schedule lezioni per date (con `IsUserPresent`) |
| `/webbooking/mybooks` | GET | Prenotazioni attive dell'utente |
| `/webbooking/book` | POST | Prenota una lezione |
| `/webbooking/cancel` | POST | Cancella una prenotazione |
| `/user/GetAccessCode` | GET | QR code ingresso |
| `/user/mystatus` | GET | Stato abbonamento/certificato |

---

## 2. Bug Critici da Fixare

### Bug 2.1 — Reminder non sempre arriva + verifica prenotazione

**File**: `handlers/reminders.py:108-160`

**Problema**: `_process_reminder()` chiama `_verify_booking()` PRIMA di inviare il reminder 3h. Se la verifica API ritorna `success=True` ma il `lesson_id` non è nella lista (API bug, timing, lista vuota), il reminder viene **eliminato dal DB** senza mai essere inviato.

**Fix**: Prima di OGNI notifica (3h e 60min), verificare se la prenotazione è ancora attiva:
- Se **attiva** → procedi normalmente con la notifica
- Se **cancellata** → invia messaggio informativo con dettagli della prenotazione cancellata
- Se **API fallisce** → invia comunque la notifica (meglio falso positivo che mancata notifica)

```python
# PRIMA (buggato)
if THRESHOLD_60M < minutes_until <= THRESHOLD_3H and not reminder["reminder_3h_sent"]:
    exists, user = await self._verify_booking(telegram_id, reminder["lesson_id"])
    if not exists:
        db.delete_booking_reminder(reminder_id)  # ← BUG: elimina senza inviare
        return
    await self._send_3h_reminder(telegram_id, reminder)

# DOPO (fixato)
if THRESHOLD_60M < minutes_until <= THRESHOLD_3H and not reminder["reminder_3h_sent"]:
    exists, user = await self._verify_booking(telegram_id, reminder["lesson_id"])
    if not exists:
        # Prenotazione cancellata → invia messaggio informativo
        await self._send_booking_cancelled_notice(telegram_id, reminder)
        db.delete_booking_reminder(reminder_id)
        return
    await self._send_3h_reminder(telegram_id, reminder)
    db.mark_reminder_3h_sent(reminder_id)
    return

# Stessa logica per il 60min
if minutes_until <= THRESHOLD_60M and reminder["reminder_3h_sent"] and not reminder["reminder_60m_sent"]:
    exists, user = await self._verify_booking(telegram_id, reminder["lesson_id"])
    if not exists:
        await self._send_booking_cancelled_notice(telegram_id, reminder)
        db.delete_booking_reminder(reminder_id)
        return
    # ... resto della logica 60min
```

**Nuovo metodo `_send_booking_cancelled_notice()`**:
```python
async def _send_booking_cancelled_notice(self, telegram_id: int, reminder: dict):
    """Invia notifica che la prenotazione è stata cancellata (dall'app o da altri)."""
    text = (
        f"ℹ️ *Prenotazione cancellata*\n\n"
        f"🏋️ *{reminder['course_name']}*\n"
        f"📅 {reminder['lesson_date']} alle {reminder['start_time']}\n"
        f"👤 {reminder.get('instructor', '')}\n\n"
        f"La prenotazione non risulta più attiva su WellTeam.\n"
        f"Se non l'hai cancellata tu, verifica dall'app WellTeam."
    )
    await self._send_message(telegram_id, text)
```

---

### Bug 2.2 — Cancellazione mostra "meno di 60 minuti" erroneamente

**File**: `handlers/reminders.py:357-372`

**Problema**: `cb_reminder_no` ricalcola `minutes_until` con `datetime.now()` al momento del click. Il calcolo è **oggettivamente sbagliato** — non è una questione di percezione dell'utente. Guardando l'orologio, mancano più di 60 minuti, ma il codice dice il contrario.

**Causa probabile**: Il reminder 3h viene inviato in ritardo (es. alle 17:10 per lezione delle 18:00) perché il check precedente ha fallito la verifica API o il bot era giù. Quando l'utente clicca "Cancella" alle 17:15, il codice calcola `18:00 - 17:15 = 45 minuti` → "meno di 60 minuti". Ma il reminder dice "Tra meno di 3 ore!" → contraddizione evidente.

**Fix**: Usare lo stato del reminder (`reminder_3h_sent`, `reminder_60m_sent`) invece di ricalcolare il tempo. Questo elimina completamente il problema del ricalcolo.

```python
# PRIMA (buggato)
lesson_dt = datetime.strptime(f"{lesson_date} {start_time}", "%Y-%m-%d %H:%M")
minutes_until = (lesson_dt - datetime.now()).total_seconds() / 60.0
if minutes_until < THRESHOLD_60M:
    await query.edit_message_text("❌ Impossibile cancellare...")

# DOPO (fixato)
if reminder["reminder_60m_sent"]:
    # Messaggio 60min già inviato → siamo sotto i 60 min → blocca
    await query.edit_message_text("❌ Impossibile cancellare...")
    return
# Altrimenti → siamo nella finestra 3h-60min → permetti cancellazione
```

**Nota**: il ricalcolo con `datetime.now()` va rimosso completamente. Lo stato del reminder è l'unica fonte di verità affidabile.

---

### Bug 2.3 — Service ID cambiati (stagione 2025/2026 → 2026/2027)

**File**: `scheduler.py`, `db.py`, `course_catalog.py`

**Problema**: Tutti i `service_id` cambiano ad ogni cambio stagione. Gli `auto_book_items` nel DB puntano ai vecchi ID → l'auto-booking non trova mai le lezioni.

**Verificato**: Le descrizioni dei corsi sono identiche tra le stagioni. La chiave `(description, day_of_week, start_time)` è affidabile.

**Fix**: Vedi sezione 3 (Cambio Stagione).

---

### Bug 2.4 — `corsi.py` modalità "view" non mostra bottoni

**File**: `handlers/corsi.py:296-298`

**Problema**: I bottoni per i corsi vengono generati solo se `mode == "book"`. In modalità "view" (`cmd_lista_corsi`), l'utente vede i corsi ma non può interagire.

**Fix**: Generare bottoni anche in modalità "view" (almeno per attivare auto-booking).

---

### Bug 2.5 — `cb_pick_course` non ha `@require_auth`

**File**: `handlers/corsi.py:319`

**Problema**: `cb_pick_course` ha `@rate_limit` ma non `@require_auth`. Un utente non loggato potrebbe accedere al flusso di prenotazione.

**Fix**: Aggiungere `@require_auth`.

---

### Bug 2.6 — Login via GET con password in query string

**File**: `wellteam.py:68-73`

**Problema**: La password viene passata come query parameter in una GET request. Finisce nei log del server, nei proxy, nella cronologia.

**Fix**: Non è possibile cambiare il metodo HTTP (API di terze parti). Ma si può:

1. Loggare solo il risultato, non la richiesta
2. Aggiungere un warning nel log se il livello è DEBUG

---

## 3. Cambio Stagione — Rilevamento e Migrazione Automatica

### 3.1 Rilevamento

Il cambio stagione si rileva confrontando la `CategoryDescription` dall'API `/webbooking/services` con quella salvata nel catalogo.

```python
# In schedule_cache.py o course_catalog.py
def detect_season_change(api_category: str) -> bool:
    """Confronta la category dell'API con quella del catalogo locale."""
    catalog = _load()
    if not catalog:
        return False  # Primo avvio, nessun dato
    saved_category = catalog.get("_meta", {}).get("category", "")
    return saved_category != api_category
```

### 3.2 Migrazione Automatica

Quando si rileva un cambio stagione:

1. **Salvare la nuova category** nel catalogo (`_meta.category`)
2. **Ricostruire la mappa service_id** usando `(description, day_of_week, start_time)`:
   - Per ogni `auto_book_item` nel DB, cercare il nuovo `service_id` nella schedule live
   - Se trovato → aggiornare il `service_id` nel DB
   - Se non trovato → segnare l'item come "da verificare" (il corso potrebbe non esistere più)
3. **Svuotare il catalogo** e ricostruirlo dai dati live
4. **Notificare l'utente** se un suo auto-book item non è più disponibile

### 3.3 Implementazione

**Nuovo file**: `season_migration.py`

```python
def migrate_service_ids(app) -> dict:
    """
    Rileva cambio stagione e migra i service_id.
    Ritorna {"migrated": N, "not_found": M, "unchanged": K}
    """
    # 1. Carica la category corrente dal catalogo
    # 2. Chiama /webbooking/services per la nuova category
    # 3. Se diversa → migrazione
    # 4. Per ogni auto_book_item attivo:
    #    - Cerca nella schedule live per (description, day_of_week, start_time)
    #    - Se trovato → UPDATE auto_book_items SET service_id = nuovo_id
    #    - Se non trovato → segna come "non trovato"
    # 5. Aggiorna il catalogo
    # 6. Ritorna statistiche
```

**Chiamata**: nel `post_init()` di `main.py`, dopo il refresh catalogo.

### 3.4 Matching Lezioni nel Scheduler

Modificare `_process_item()` e `_process_retry_item()` per fallback su description:

```python
# Cerca per service_id (veloce)
for lesson in lessons:
    if lesson.get("IDServizio") == service_id:
        # ... prenota

# Se non trovato per service_id → fallback su description
if not target_lesson:
    for lesson in lessons:
        if (lesson.get("ServiceDescription") == item["description"] and
            lesson.get("StartTime", "")[11:16] == start_time):
            # Trovato! Aggiorna il service_id nel DB
            db.update_auto_book_service_id(item["id"], lesson["IDServizio"])
            target_lesson = lesson
            break
```

---

## 4. Sincronizzazione con Prenotazioni dall'App

### 4.1 Problema

Se un utente prenota dall'app WellTeam, il bot non lo sa:

- L'auto-booking potrebbe provare a prenotare di nuovo (riceve "già prenotato" → ok)
- Ma il reminder non viene creato → l'utente non riceve il promemoria

### 4.2 Soluzione: Reconciliation Periodico (ogni 3 ore)

Aggiungere una funzione di reconciliation che gira **ogni 3 ore** (es. 00:05, 03:05, 06:05, 09:05, 12:05, 15:05, 18:05, 21:05):

```python
def reconcile_bookings(app):
    """
    Per ogni utente attivo:
    1. Chiama get_my_books() per ottenere le prenotazioni reali
    2. Confronta con i booking_reminders nel DB
    3. Crea reminder mancanti per le prenotazioni esistenti
    4. Rimuove reminder per prenotazioni non più esistenti
    5. Aggiorna last_booked_date negli auto_book_items se necessario
    """
    users = db.get_all_active_users_for_reminders()
    for user in users:
        success, books = wellteam.get_my_books(...)
        if not success:
            continue
        
        # Prendi tutti i lesson_id reali dal server
        real_lesson_ids = set()
        for book in books:
            lesson_id = book.get("IDLesson")
            lesson_date = book.get("StartTime", "")[:10]
            real_lesson_ids.add((lesson_id, lesson_date))
            
            # Se non c'è un reminder → crealo
            existing = db.get_booking_reminder(user["telegram_id"], lesson_id, lesson_date)
            if not existing:
                db.upsert_booking_reminder(
                    user["telegram_id"], lesson_id, lesson_date,
                    book.get("StartTime", "")[11:16],
                    book.get("ServiceDescription", ""),
                    book.get("AdditionalInfo", ""),
                )
        
        # Rimuovi reminder per prenotazioni non più esistenti
        pending = db.get_pending_reminders_for_user(user["telegram_id"])
        for reminder in pending:
            if (reminder["lesson_id"], reminder["lesson_date"]) not in real_lesson_ids:
                db.delete_booking_reminder(reminder["id"])
```

**Implementazione**: Aggiungere un job periodico nello scheduler che esegue `reconcile_bookings()` ogni 3 ore.

### 4.3 Verifica Pre-Booking

Nel scheduler, prima di prenotare, verificare se l'utente ha già prenotato:

```python
# In _process_item(), dopo aver trovato la lezione
if lesson.get("IsUserPresent"):
    # Già prenotato (dall'app o da altro)
    db.update_auto_book_last_booked(item_id, lesson.get("IDLesson"), date_str)
    # Crea reminder se mancante
    db.upsert_booking_reminder(telegram_id, lesson_id, date_str, start_time, description, instructor)
    return
```

Questo è già implementato ma va verificato che il reminder venga creato.

---

## 5. UX Best Practices — Pulizia Chat e Interazione

### 5.1 Auto-Delete Vecchi Messaggi

**Problema**: La chat si riempie di vecchi messaggi del bot (menu, risultati, conferme).

**Soluzione**: Tracciare i `message_id` dei messaggi inviati dal bot e cancellarli dopo un timeout.

**Implementazione**:

```python
# In handlers/menu.py o modulo dedicato
import asyncio

async def send_and_track(update, text, context, reply_markup=None, **kwargs):
    """Invia un messaggio e traccia il message_id per auto-delete."""
    msg = await update.effective_message.reply_text(text, reply_markup=reply_markup, **kwargs)
    
    # Salva il message_id per auto-delete
    tracked = context.user_data.setdefault("tracked_messages", [])
    tracked.append({"chat_id": msg.chat_id, "message_id": msg.message_id, "sent_at": time.time()})
    
    # Mantieni solo gli ultimi 10 messaggi tracciati
    if len(tracked) > 10:
        old = tracked.pop(0)
        try:
            await context.bot.delete_message(chat_id=old["chat_id"], message_id=old["message_id"])
        except Exception:
            pass
    
    return msg


async def cleanup_old_messages(context: ContextTypes.DEFAULT_TYPE):
    """Job periodico che cancella messaggi più vecchi di 30 minuti."""
    # Itera su tutti gli user_data (da persistence)
    # Per ogni utente, cancella i messaggi tracked più vecchi di 30 min
```

**Alternativa più semplice**: Quando l'utente preme un bottone del menu, cancellare il messaggio precedente prima di inviare il nuovo.

```python
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu principale — cancella il vecchio messaggio se è una callback."""
    if update.callback_query:
        # Cancella il messaggio precedente
        try:
            await update.callback_query.message.delete()
        except Exception:
            pass
        # Invia un nuovo messaggio (pulito)
        await update.effective_chat.send_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)
```

### 5.2 Menu Principale come "Home Base"

**Problema**: Ogni volta che l'utente preme "🔙 Menu", il bot edita il messaggio corrente. Dopo molte interazioni, il messaggio è stato editato tante volte e Telegram potrebbe mostrare "edited".

**Soluzione**: Quando si torna al menu, **cancellare il messaggio corrente e inviare un nuovo messaggio**.

```python
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except Exception:
            pass
    # Invia sempre un nuovo messaggio per il menu
    msg = await update.effective_chat.send_text(text, reply_markup=kb)
    context.user_data["menu_message_id"] = msg.message_id
```

### 5.3 Gestione Callback Query Migliorata

**Problema**: Alcuni handler non chiamano `query.answer()` o lo chiamano con ritardo.

**Soluzione**: Chiamare `query.answer()` **immediatamente** in ogni callback handler, prima di qualsiasi operazione lenta.

```python
async def cb_some_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # SEMPRE primo comando
    # ... operazioni lente (API calls, DB)
```

### 5.4 Messaggi di Caricamento

**Problema**: Quando il bot chiama l'API WellTeam (1-3 secondi), l'utente non vede nulla.

**Soluzione**: Mostrare un messaggio "⏳ Caricamento..." e aggiornarlo quando arrivano i dati.

```python
async def cmd_prenota(update, context, user):
    msg = await update.effective_message.reply_text("🔄 *Caricamento corsi...*", parse_mode="Markdown")
    # ... chiama API ...
    await msg.edit_text(result_text, reply_markup=kb)
```

Questo è già fatto in alcuni handler (`wait_msg` in auth.py) ma va esteso a tutti.

### 5.5 Pulizia Automatica Booking Reminders Vecchi

**Problema**: I reminder per lezioni passate rimangono nel DB.

**Soluzione**: Già implementato in `_process_reminder()` (elimina se `lesson_dt < now`). Ma aggiungere anche un job periodico di pulizia:

```python
async def cleanup_old_reminders():
    """Rimuove reminder per lezioni passate più vecchie di 24 ore."""
    conn = db.get_connection()
    conn.execute("""
        DELETE FROM booking_reminders 
        WHERE reminder_60m_sent = 1 
        AND updated_at < datetime('now', '-1 day')
    """)
    conn.commit()
```

### 5.6 Feedback Visivo Azioni

**Problema**: Quando l'utente preme un bottone (es. "Attiva auto-booking"), il bot risponde dopo 2-3 secondi senza feedback immediato.

**Soluzione**: Usare `query.answer()` con testo toast per feedback immediato:

```python
await query.answer("✅ Auto-booking attivato!")  # Toast visivo
# Poi aggiorna il messaggio
await query.edit_message_text(...)
```

### 5.7 Navigazione Breadcrumbs

**Problema**: L'utente non sa dove si trova nella navigazione.

**Soluzione**: Aggiungere header con breadcrumb nei messaggi:

```
🏠 > 📅 Prenota > Lunedì > All. Funzionale

🏋️ All. Funzionale
📅 Lunedì alle 19:00
👤 Giacomo
```

---

## 6. Miglioramenti Affidabilità

### 6.1 Notifiche Perse al Riavvio

**File**: `scheduler.py:98-116`

**Problema**: Lo scheduler (thread separato) esegue l'auto-booking alle 00:10, ma l'event loop potrebbe non essere attivo → notifiche perse.

**Fix**: In `_send_message()`, se l'event loop non è attivo, salvare il messaggio in una coda e inviarlo quando il loop diventa disponibile.

```python
def _send_message(self, telegram_id: int, text: str):
    loop = self._event_loop
    if not loop or not loop.is_running():
        # Salva in coda per invio successivo
        self._pending_messages.append((telegram_id, text))
        return
    # ... invio normale
```

E in `set_loop()`:

```python
def set_loop(self, loop):
    self._event_loop = loop
    # Invia messaggi in coda
    for telegram_id, text in self._pending_messages:
        self._send_message(telegram_id, text)
    self._pending_messages.clear()
```

### 6.2 Token Refresh Migliorato

**File**: `scheduler.py:498-534`

**Problema**: Se il token scade, il bot prova a fare refresh con la password salvata. Ma se il refresh fallisce (password errata, server down), continua a provare senza mai invalidare il token.

**Fix**:

1. Dopo N fallimenti consecutivi di refresh, notificare l'utente che deve fare re-login
2. Aggiungere un flag `token_invalid` nel DB per evitare refresh continui

### 6.3 Rate Limiter Memory Leak

**File**: `handlers/ratelimit.py:10`

**Problema**: `_user_timestamps` cresce indefinitamente.

**Fix**: Aggiungere pulizia periodica:

```python
def _cleanup_old_entries():
    """Rimuove utenti inattivi da più di 5 minuti."""
    now = time.time()
    with _lock:
        inactive = [uid for uid, ts_list in _user_timestamps.items() 
                    if not ts_list or now - ts_list[-1] > 300]
        for uid in inactive:
            del _user_timestamps[uid]
```

### 6.4 Backfill Asincrono

**File**: `main.py:276`

**Problema**: `_backfill_booking_reminders()` è sincrono e blocca l'avvio.

**Fix**: Eseguirlo in un task asincrono dopo l'avvio:

```python
async def post_init(app):
    # ... existing code ...
    # Backfill asincrono (non blocca l'avvio)
    asyncio.create_task(_backfill_async(app))
```

---

## 7. Miglioramenti Sicurezza

### 7.1 Controllo Ownership su Cancellazione

**File**: `handlers/corsi.py:867`

**Problema**: `cb_cancel_prenotazione` non verifica che il `booking_id` appartenga all'utente.

**Fix**: Verificare che il `booking_id` sia nei `cancel_bookings` dell'utente (già fatto, ma il controllo è nel `context.user_data` che potrebbe essere stale). Aggiungere verifica API:

```python
# Prima di cancellare, verifica che il booking appartenga all'utente
success, books = wellteam.get_my_books(...)
booking_ids = {b.get("BookingID") for b in books}
if booking_id not in booking_ids:
    await query.edit_message_text("❌ Prenotazione non trovata o non tua.")
    return
```

### 7.2 Rimuovere Password dai Log

**File**: `wellteam.py:76`

**Problema**: In caso di errore, il log potrebbe contenere la password nella query string.

**Fix**: Non loggare la richiesta, solo la risposta:

```python
# PRIMA
logger.warning(f"Login fallito per {username}: HTTP {r.status_code} {r.text[:200]}")

# DOPO
logger.warning(f"Login fallito per {username}: HTTP {r.status_code}")
```

### 7.3 `.dockerignore` — Escludere `.fernet_key`

**File**: `.dockerignore`

**Problema**: `.fernet_key` non è nel `.dockerignore`. Se qualcuno fa `docker build` con il file presente, la chiave finisce nell'immagine.

**Verifica completata**: La chiave Fernet è correttamente montata nel container via Docker volume (`/var/lib/docker/volumes/bot-palestra_palestra_data/_data -> /app/data`). Il file `/app/data/.fernet_key` esiste nel container con permessi `600` (dopo fix). La chiave persiste across restart.

**Fix**: Aggiungere `.fernet_key` al `.dockerignore` per evitare che finisca in build future.

---

## 8. Ordine di Implementazione

### Fase 1 — Fix Critici (priorità massima)

| # | Task | File | Tempo stimato |
| --- | ------ | ------ | --------------- |
| 1.1 | Fix reminder 3H (rimuovere verifica API) | `handlers/reminders.py` | 30 min |
| 1.2 | Fix cancellazione < 60min (usare stato reminder) | `handlers/reminders.py` | 30 min |
| 1.3 | Rilevamento cambio stagione | Nuovo: `season_migration.py` | 2h |
| 1.4 | Migrazione service_id automatica | `season_migration.py`, `db.py` | 2h |
| 1.5 | Fallback matching per description nello scheduler | `scheduler.py` | 1h |

### Fase 2 — Sincronizzazione App

| # | Task | File | Tempo stimato |
| --- | ------ | ------ | --------------- |
| 2.1 | Reconciliation periodico (prima dell'auto-booking) | `scheduler.py` | 1.5h |
| 2.2 | Crea reminder per prenotazioni dall'app | `scheduler.py`, `db.py` | 30 min |
| 2.3 | Verifica pre-booking (IsUserPresent + crea reminder) | `scheduler.py` | 30 min |

### Fase 3 — UX Best Practices

| # | Task | File | Tempo stimato |
| --- | ------ | ------ | --------------- |
| 3.1 | Auto-delete vecchi messaggi (tracked messages) | Nuovo: `handlers/ux.py` | 1.5h |
| 3.2 | Menu come "home base" (delete + new message) | `handlers/menu.py` | 1h |
| 3.3 | Feedback toast su callback | Tutti gli handler | 30 min |
| 3.4 | Messaggi di caricamento estesi | `handlers/corsi.py` | 30 min |
| 3.5 | Pulizia automatica reminders vecchi | `handlers/reminders.py` | 30 min |
| 3.6 | Breadcrumb navigazione | `handlers/corsi.py`, `handlers/menu.py` | 1h |

### Fase 4 — Affidabilità

| # | Task | File | Tempo stimato |
| --- | ------ | ------ | --------------- |
| 4.1 | Coda messaggi per notifiche perse | `scheduler.py` | 1h |
| 4.2 | Token refresh con notifica utente | `scheduler.py` | 1h |
| 4.3 | Rate limiter cleanup | `handlers/ratelimit.py` | 15 min |
| 4.4 | Backfill asincrono | `main.py` | 30 min |

### Fase 5 — Sicurezza

| # | Task | File | Tempo stimato |
| --- | ------ | ------ | --------------- |
| 5.1 | Ownership check cancellazione | `handlers/corsi.py` | 30 min |
| 5.2 | Rimuovi password dai log | `wellteam.py` | 15 min |
| 5.3 | `.dockerignore` aggiorna | `.dockerignore` | 5 min |
| 5.4 | Aggiungere `@require_auth` dove manca | `handlers/corsi.py` | 15 min |

### Tempo Totale Stimato: ~16-18 ore

---

## 9. Testing

### Test Manuali

1. **Reminder 3H**: Prenota un corso tra 3h e verifica che il reminder arrivi
2. **Cancellazione**: Clicca "Cancella" dal reminder 3h con > 60min rimanenti → deve funzionare
3. **Cambio stagione**: ⚠️ Non testabile manualmente — bisogna aspettare che la palestra cambi la stagione del calendario. Il test va fatto al cambio reale.
4. **Reconciliation**: Prenota dall'app e verifica che il bot crei il reminder entro 3 ore
5. **Auto-delete**: Naviga il menu e verifica che i vecchi messaggi vengano cancellati
6. **Notifica cancellazione**: Cancella una prenotazione dall'app e verifica che il bot invii il messaggio informativo

### Test Automatici

Aggiungere test per:

- `detect_season_change()`
- `migrate_service_ids()`
- `_process_reminder()` con diversi scenari temporali
- `cb_reminder_no()` con diversi stati del reminder
- Matching lezioni per description

---

## Note Aggiuntive

### Sul catalogo corsi

Il catalogo `course_catalog.json` va mantenuto come cache locale per mostrare i corsi anche quando il server non li restituisce (oltre i 4 giorni). Ma va aggiornato con:

- Campo `_meta.category` per rilevare il cambio stagione
- Campo `_meta.last_updated` per sapere quando è stato aggiornato
- Rimozione automatica dei corsi della stagione precedente quando ne viene rilevata una nuova

### Sul formato StartTime dell'API

L'API restituisce `StartTime: "1900-01-01T19:00:00"` — una data fittizia con l'ora reale. Il codice attuale gestisce questo con:

```python
bs_time = bs[11:19] if len(bs) >= 19 and "1900-01-01" in bs else bs
```

Questo funziona ma è fragile. Valutare di estrarre sempre l'ora dopo la `T`:

```python
time_part = start_time.split("T")[1][:5] if "T" in start_time else start_time[:5]
```

### Sul VisibleDays

Il server restituisce `VisibleDays: 4` nell'endpoint `/webbooking/services`. Questo significa che il server pubblica solo 4 giorni in avanti. **VisibleDays non è gestibile lato bot** — dipende interamente dal server. Il bot deve:

1. Usare il catalogo locale per mostrare corsi oltre i 4 giorni
2. Per l'auto-booking, cercare solo nei giorni disponibili dal server
3. Se non trova lezioni nei 4 giorni → riprovare al prossimo ciclo (non è un errore)

---

## 10. Operazioni Eseguite (2026-09-02)

### Pulizia Catalogo
- Rimosso catalogo vecchio 2025/2026 (30 corsi con service_id obsoleti)
- Ricostruito catalogo 2026/2027 da API live (38 corsi, 3 giorni)
- Aggiunto campo `_meta.category` per rilevamento cambio stagione

### Aggiornamento Auto-Book Items
- Aggiornati 4 auto_book_items da `service_id=191` a `service_id=219` (All. Funzionale)
- Aggiornato orario Martedì da 19:00 a 18:00 (cambiato dal server)
- Aggiornato istruttore Giovedì da Giacomo a Marco (cambiato dal server)
- Reset `last_booked_lesson` e `last_booked_date` (lesson_id non più validi)

### Pulizia Reminder
- Rimossi 4 booking_reminders per lezioni passate (maggio 2026)

### Sicurezza
- Corretti permessi `.fernet_key` da `644` a `600` nel container
