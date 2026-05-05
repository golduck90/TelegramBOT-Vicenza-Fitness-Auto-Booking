"""
Database layer — SQLite con parametri, nessuna injection possibile.
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from cryptography.fernet import Fernet
import config

# Lock thread-safe per SQLite (single-writer)
_local = threading.local()
_db_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """Restituisce una connessione thread-safe al DB."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(config.DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")    # Concorrenza
        _local.conn.execute("PRAGMA foreign_keys=ON")      # Integrità
        _local.conn.execute("PRAGMA busy_timeout=5000")    # Timeout 5s
    return _local.conn


def init_db():
    """Crea le tabelle se non esistono."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id     INTEGER PRIMARY KEY,
            username        TEXT NOT NULL UNIQUE,
            encrypted_pass  TEXT NOT NULL,
            app_token       TEXT,
            auth_token      TEXT,
            iyes_url        TEXT DEFAULT 'http://185.103.80.254:65432/',
            company_id      INTEGER DEFAULT 2,
            user_id         INTEGER DEFAULT 0,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now')),
            last_login_at   TEXT,
            login_attempts  INTEGER DEFAULT 0,
            locked_until    TEXT
        );

        CREATE TABLE IF NOT EXISTS courses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id     INTEGER NOT NULL,
            service_id      INTEGER NOT NULL,
            description     TEXT NOT NULL,
            instructor      TEXT,
            category        TEXT,
            is_favorite     INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        );

        CREATE TABLE IF NOT EXISTS autobook_rules (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id     INTEGER NOT NULL,
            service_id      INTEGER NOT NULL,
            description     TEXT NOT NULL,
            instructor      TEXT,
            day_of_week     INTEGER NOT NULL,  -- 0=Mon ... 6=Sun
            book_for_day    INTEGER NOT NULL,  -- giorno relativo (0=stesso, 1=giorno dopo, 3=tra 3 gg...)
            start_time      TEXT NOT NULL,      -- es. "19:00"
            end_time        TEXT NOT NULL,      -- es. "19:45"
            is_enabled      INTEGER DEFAULT 1,
            last_booked     TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        );

        CREATE TABLE IF NOT EXISTS booking_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id     INTEGER NOT NULL,
            service_desc    TEXT,
            lesson_id       INTEGER,
            start_time      TEXT,
            action          TEXT,  -- 'book', 'cancel', 'autobook'
            success         INTEGER DEFAULT 1,
            message         TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        );

        -- Cache del calendario settimanale (aggiornato ogni notte)
        CREATE TABLE IF NOT EXISTS schedule_cache (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id     INTEGER NOT NULL,
            lesson_id       INTEGER NOT NULL,
            service_id      INTEGER NOT NULL,
            description     TEXT NOT NULL,
            day_of_week     INTEGER NOT NULL,  -- 0=Lun 6=Dom
            lesson_date     TEXT NOT NULL,      -- YYYY-MM-DD
            start_time      TEXT NOT NULL,      -- HH:MM
            end_time        TEXT NOT NULL,      -- HH:MM
            instructor      TEXT,
            category        TEXT,
            is_mine         INTEGER DEFAULT 0, -- già prenotato?
            week_key        TEXT NOT NULL,      -- "2026-W19"
            cached_at       TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        );

        -- Iscrizioni auto-booking (nuovo sistema)
        CREATE TABLE IF NOT EXISTS auto_book_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id     INTEGER NOT NULL,
            service_id      INTEGER NOT NULL,
            description     TEXT NOT NULL,
            day_of_week     INTEGER NOT NULL,  -- 0=Lun 6=Dom
            start_time      TEXT NOT NULL,      -- HH:MM
            end_time        TEXT NOT NULL,      -- HH:MM
            instructor      TEXT,
            is_active       INTEGER DEFAULT 1,
            last_booked_lesson  INTEGER,       -- lesson_id ultima prenotazione
            last_booked_date    TEXT,           -- YYYY-MM-DD ultima prenotazione
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        );

        CREATE INDEX IF NOT EXISTS idx_autobook_user ON autobook_rules(telegram_id, is_enabled);
        CREATE INDEX IF NOT EXISTS idx_booking_log_user ON booking_log(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_schedule_cache ON schedule_cache(telegram_id, week_key);
        CREATE INDEX IF NOT EXISTS idx_auto_book_user ON auto_book_items(telegram_id, is_active);

        -- Stato reminder prenotazioni (3h / 60min)
        CREATE TABLE IF NOT EXISTS booking_reminders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id     INTEGER NOT NULL,
            lesson_id       INTEGER NOT NULL,
            lesson_date     TEXT NOT NULL,          -- YYYY-MM-DD
            start_time      TEXT NOT NULL,          -- HH:MM
            course_name     TEXT NOT NULL,
            instructor      TEXT DEFAULT '',
            reminder_3h_sent    INTEGER DEFAULT 0,  -- 1 se inviato reminder 3h
            reminder_60m_sent   INTEGER DEFAULT 0,  -- 1 se inviato messaggio 60min
            user_response       TEXT,               -- 'yes', 'no', NULL
            responded_at        TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_reminder_lesson
            ON booking_reminders(telegram_id, lesson_id, lesson_date);
    """)
    conn.commit()
    # Genera chiave Fernet al primo avvio (trigger lato config)
    config.get_fernet_key()


# ═══════════════════════════════════════════════════════════
# UTENTI
# ═══════════════════════════════════════════════════════════

def encrypt_password(password: str) -> str:
    """Cifra la password con Fernet."""
    key = config.get_fernet_key()
    f = Fernet(key)
    return f.encrypt(password.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """Decifra la password."""
    key = config.get_fernet_key()
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()


def register_user(telegram_id: int, username: str, password: str) -> bool:
    """Registra un nuovo utente o aggiorna la password se già esiste."""
    encrypted = encrypt_password(password)
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO users (telegram_id, username, encrypted_pass)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                encrypted_pass = excluded.encrypted_pass,
                is_active = 1,
                login_attempts = 0,
                locked_until = NULL
        """, (telegram_id, username, encrypted))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Recupera un utente per ID Telegram."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ? AND is_active = 1",
        (telegram_id,)
    ).fetchone()
    return dict(row) if row else None


def get_user_by_telegram_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Alias."""
    return get_user(telegram_id)


def update_tokens(telegram_id: int, auth_token: str, app_token: str = "", user_id: int = 0):
    """Aggiorna i token dopo il login."""
    conn = _get_conn()
    conn.execute("""
        UPDATE users SET
            auth_token = ?, app_token = ?, user_id = ?,
            last_login_at = datetime('now'),
            login_attempts = 0,
            locked_until = NULL
        WHERE telegram_id = ?
    """, (auth_token, app_token, user_id, telegram_id))
    conn.commit()


def increment_login_attempts(telegram_id: int) -> int:
    """Incrementa tentativi falliti. Restituisce il nuovo conteggio."""
    conn = _get_conn()
    conn.execute("""
        UPDATE users SET login_attempts = COALESCE(login_attempts, 0) + 1
        WHERE telegram_id = ?
    """, (telegram_id,))
    conn.commit()
    row = conn.execute(
        "SELECT login_attempts FROM users WHERE telegram_id = ?",
        (telegram_id,)
    ).fetchone()
    return row["login_attempts"] if row else 0


def lock_user(telegram_id: int, minutes: int = 15):
    """Blocca l'utente per N minuti."""
    from datetime import timedelta
    lock_until = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET locked_until = ? WHERE telegram_id = ?",
        (lock_until, telegram_id)
    )
    conn.commit()


def is_locked(telegram_id: int) -> bool:
    """Verifica se l'utente è bloccato."""
    from datetime import datetime
    user = get_user(telegram_id)
    if user and user.get("locked_until"):
        try:
            lock_time = datetime.fromisoformat(user["locked_until"])
            if datetime.utcnow() < lock_time:
                return True
        except (ValueError, TypeError):
            pass
    return False


def get_user_password(telegram_id: int) -> Optional[str]:
    """Restituisce la password in chiaro (solo per uso interno API)."""
    user = get_user(telegram_id)
    if user and user.get("encrypted_pass"):
        return decrypt_password(user["encrypted_pass"])
    return None


def remove_user(telegram_id: int):
    """Rimuove un utente e tutti i suoi dati."""
    conn = _get_conn()
    conn.execute("DELETE FROM booking_reminders WHERE telegram_id = ?", (telegram_id,))
    conn.execute("DELETE FROM autobook_rules WHERE telegram_id = ?", (telegram_id,))
    conn.execute("DELETE FROM auto_book_items WHERE telegram_id = ?", (telegram_id,))
    conn.execute("DELETE FROM courses WHERE telegram_id = ?", (telegram_id,))
    conn.execute("DELETE FROM schedule_cache WHERE telegram_id = ?", (telegram_id,))
    conn.execute("DELETE FROM booking_log WHERE telegram_id = ?", (telegram_id,))
    conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
    conn.commit()


def count_active_users() -> int:
    """Conta utenti attivi."""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_active = 1").fetchone()
    return row["cnt"] if row else 0


# ═══════════════════════════════════════════════════════════
# CORSI / PREFERITI
# ═══════════════════════════════════════════════════════════

def save_courses(telegram_id: int, courses_list: List[Dict]):
    """Salva i corsi disponibili per un utente (cache)."""
    conn = _get_conn()
    conn.execute("DELETE FROM courses WHERE telegram_id = ?", (telegram_id,))
    for c in courses_list:
        conn.execute("""
            INSERT OR IGNORE INTO courses (telegram_id, service_id, description, instructor, category)
            VALUES (?, ?, ?, ?, ?)
        """, (telegram_id, c.get("Id"), c.get("Description"), c.get("Instructor"), c.get("Category")))
    conn.commit()


def get_user_courses(telegram_id: int) -> List[Dict]:
    """Corsi salvati per un utente."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM courses WHERE telegram_id = ? ORDER BY description",
        (telegram_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def toggle_favorite_course(telegram_id: int, service_id: int) -> bool:
    """Toggle preferito per un corso."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT is_favorite FROM courses WHERE telegram_id = ? AND service_id = ?",
        (telegram_id, service_id)
    ).fetchone()
    if row:
        new_val = 0 if row["is_favorite"] else 1
        conn.execute(
            "UPDATE courses SET is_favorite = ? WHERE telegram_id = ? AND service_id = ?",
            (new_val, telegram_id, service_id)
        )
        conn.commit()
        return bool(new_val)
    return False


# ═══════════════════════════════════════════════════════════
# AUTO-BOOKING RULES
# ═══════════════════════════════════════════════════════════

def add_autobook_rule(telegram_id: int, service_id: int, description: str,
                       instructor: str, day_of_week: int, book_for_day: int,
                       start_time: str, end_time: str) -> int:
    """Aggiunge una regola di auto-booking. Restituisce l'ID."""
    conn = _get_conn()
    cur = conn.execute("""
        INSERT INTO autobook_rules (telegram_id, service_id, description, instructor,
                                     day_of_week, book_for_day, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (telegram_id, service_id, description, instructor, day_of_week, book_for_day, start_time, end_time))
    conn.commit()
    return cur.lastrowid


def get_user_autobook_rules(telegram_id: int, enabled_only: bool = False) -> List[Dict]:
    """Elenco regole auto-booking di un utente."""
    conn = _get_conn()
    query = "SELECT * FROM autobook_rules WHERE telegram_id = ?"
    params = [telegram_id]
    if enabled_only:
        query += " AND is_enabled = 1"
    query += " ORDER BY day_of_week, start_time"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_all_enabled_rules() -> List[Dict]:
    """Tutte le regole attive di tutti gli utenti (per lo scheduler)."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT r.*, u.auth_token, u.app_token, u.iyes_url, u.company_id, u.username
        FROM autobook_rules r
        JOIN users u ON u.telegram_id = r.telegram_id
        WHERE r.is_enabled = 1 AND u.is_active = 1 AND u.auth_token IS NOT NULL
    """).fetchall()
    return [dict(r) for r in rows]


def toggle_autobook_rule(rule_id: int, telegram_id: int) -> bool:
    """Attiva/disattiva una regola. Restituisce il nuovo stato."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT is_enabled FROM autobook_rules WHERE id = ? AND telegram_id = ?",
        (rule_id, telegram_id)
    ).fetchone()
    if row:
        new_val = 0 if row["is_enabled"] else 1
        conn.execute(
            "UPDATE autobook_rules SET is_enabled = ? WHERE id = ?",
            (new_val, rule_id)
        )
        conn.commit()
        return bool(new_val)
    return False


def remove_autobook_rule(rule_id: int, telegram_id: int) -> bool:
    """Elimina una regola."""
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM autobook_rules WHERE id = ? AND telegram_id = ?",
        (rule_id, telegram_id)
    )
    conn.commit()
    return cur.rowcount > 0


def update_autobook_last_booked(rule_id: int):
    """Aggiorna il timestamp dell'ultima prenotazione."""
    conn = _get_conn()
    conn.execute(
        "UPDATE autobook_rules SET last_booked = datetime('now') WHERE id = ?",
        (rule_id,)
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════
# BOOKING LOG
# ═══════════════════════════════════════════════════════════

def log_booking(telegram_id: int, service_desc: str, lesson_id: int,
                start_time: str, action: str, success: bool = True, message: str = ""):
    """Registra un'operazione di booking nel log."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO booking_log (telegram_id, service_desc, lesson_id, start_time, action, success, message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (telegram_id, service_desc, lesson_id, start_time, action, int(success), message[:500]))
    conn.commit()


def get_booking_history(telegram_id: int, limit: int = 20) -> List[Dict]:
    """Cronologia prenotazioni di un utente."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM booking_log
        WHERE telegram_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (telegram_id, limit)).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════
# SCHEDULE CACHE (calendario notturno)
# ═══════════════════════════════════════════════════════════

def clear_schedule_cache(telegram_id: int, week_key: str = None):
    """Svuota la cache per un utente (opzionalmente solo una settimana)."""
    conn = _get_conn()
    if week_key:
        conn.execute(
            "DELETE FROM schedule_cache WHERE telegram_id = ? AND week_key = ?",
            (telegram_id, week_key)
        )
    else:
        conn.execute(
            "DELETE FROM schedule_cache WHERE telegram_id = ?",
            (telegram_id,)
        )
    conn.commit()


def save_schedule_cache(telegram_id: int, items: List[Dict], week_key: str):
    """Salva il calendario nella cache. Sostituisce la settimana se già esiste."""
    conn = _get_conn()
    # Svuota solo questa settimana
    conn.execute(
        "DELETE FROM schedule_cache WHERE telegram_id = ? AND week_key = ?",
        (telegram_id, week_key)
    )
    for item in items:
        start = item.get("StartTime", "")
        end = item.get("EndTime", "")
        conn.execute("""
            INSERT INTO schedule_cache
                (telegram_id, lesson_id, service_id, description,
                 day_of_week, lesson_date, start_time, end_time,
                 instructor, category, is_mine, week_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            telegram_id,
            item.get("IDLesson"),
            item.get("IDServizio"),
            item.get("ServiceDescription", ""),
            item.get("DayOfWeek", 0),
            item.get("DateLesson", "")[:10] if item.get("DateLesson") else "",
            start[11:16] if len(start) > 16 else start,
            end[11:16] if len(end) > 16 else end,
            item.get("AdditionalInfo", ""),
            item.get("CategoryDescription", ""),
            1 if item.get("IsUserPresent") else 0,
            week_key,
        ))
    conn.commit()


def get_cached_schedule(telegram_id: int, week_key: str = None) -> List[Dict]:
    """Recupera il calendario dalla cache. Se week_key è None, prende la prossima."""
    if not week_key:
        from datetime import datetime
        week_key = datetime.now().strftime("%Y-W%W")
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM schedule_cache
        WHERE telegram_id = ? AND week_key = ?
        ORDER BY day_of_week, start_time
    """, (telegram_id, week_key)).fetchall()
    return [dict(r) for r in rows]


def get_cached_schedule_by_day(telegram_id: int, day_of_week: int,
                                week_key: str = None) -> List[Dict]:
    """Corsi di un giorno specifico dalla cache."""
    if not week_key:
        from datetime import datetime
        week_key = datetime.now().strftime("%Y-W%W")
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM schedule_cache
        WHERE telegram_id = ? AND week_key = ? AND day_of_week = ?
        ORDER BY start_time
    """, (telegram_id, week_key, day_of_week)).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════
# AUTO-BOOK ITEMS (nuovo sistema)
# ═══════════════════════════════════════════════════════════

def add_auto_book_item(telegram_id: int, service_id: int, description: str,
                        day_of_week: int, start_time: str, end_time: str,
                        instructor: str = "") -> int:
    """Aggiunge un corso alla lista auto-booking."""
    conn = _get_conn()
    # Evita duplicati (stesso corso+giorno+orario+istruttore)
    existing = conn.execute("""
        SELECT id FROM auto_book_items
        WHERE telegram_id = ? AND service_id = ? AND day_of_week = ?
          AND start_time = ? AND COALESCE(instructor,'') = ?
        LIMIT 1
    """, (telegram_id, service_id, day_of_week, start_time, instructor or "")).fetchone()
    if existing:
        # Riattiva se era disattivato
        conn.execute(
            "UPDATE auto_book_items SET is_active = 1 WHERE id = ?",
            (existing["id"],)
        )
        conn.commit()
        return existing["id"]
    cur = conn.execute("""
        INSERT INTO auto_book_items
            (telegram_id, service_id, description, day_of_week,
             start_time, end_time, instructor)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (telegram_id, service_id, description, day_of_week,
          start_time, end_time, instructor or None))
    conn.commit()
    return cur.lastrowid


def remove_auto_book_item(item_id: int, telegram_id: int) -> bool:
    """Rimuove un item auto-booking."""
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM auto_book_items WHERE id = ? AND telegram_id = ?",
        (item_id, telegram_id)
    )
    conn.commit()
    return cur.rowcount > 0


def toggle_auto_book_item(item_id: int, telegram_id: int) -> Optional[bool]:
    """Attiva/disattiva. Restituisce il nuovo stato o None se non trovato."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT is_active FROM auto_book_items WHERE id = ? AND telegram_id = ?",
        (item_id, telegram_id)
    ).fetchone()
    if not row:
        return None
    new_val = 0 if row["is_active"] else 1
    conn.execute(
        "UPDATE auto_book_items SET is_active = ? WHERE id = ?",
        (new_val, item_id)
    )
    conn.commit()
    return bool(new_val)


def get_user_auto_book_items(telegram_id: int, enabled_only: bool = False) -> List[Dict]:
    """Elenco item auto-booking di un utente."""
    conn = _get_conn()
    query = "SELECT * FROM auto_book_items WHERE telegram_id = ?"
    params = [telegram_id]
    if enabled_only:
        query += " AND is_active = 1"
    query += " ORDER BY day_of_week, start_time"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_all_enabled_auto_book_items() -> List[Dict]:
    """Tutti gli item attivi di tutti gli utenti (per scheduler)."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT a.*, u.auth_token, u.iyes_url, u.company_id, u.username
        FROM auto_book_items a
        JOIN users u ON u.telegram_id = a.telegram_id
        WHERE a.is_active = 1 AND u.is_active = 1 AND u.auth_token IS NOT NULL
    """).fetchall()
    return [dict(r) for r in rows]


def update_auto_book_last_booked(item_id: int, lesson_id: int, lesson_date: str):
    """Aggiorna ultima prenotazione di un item."""
    conn = _get_conn()
    conn.execute("""
        UPDATE auto_book_items
        SET last_booked_lesson = ?, last_booked_date = ?
        WHERE id = ?
    """, (lesson_id, lesson_date, item_id))
    conn.commit()


def is_course_in_cache(telegram_id: int, service_id: int, day_of_week: int,
                        start_time: str, instructor: str = "") -> bool:
    """Verifica se un corso esiste nella cache per evitare iscrizioni a corsi spariti."""
    conn = _get_conn()
    row = conn.execute("""
        SELECT 1 FROM schedule_cache
        WHERE telegram_id = ? AND service_id = ?
          AND day_of_week = ? AND start_time = ?
          AND COALESCE(instructor,'') = COALESCE(?,'')
        LIMIT 1
    """, (telegram_id, service_id, day_of_week, start_time, instructor)).fetchone()
    return row is not None


# ═══════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════

def get_bot_stats() -> dict:
    """Restituisce statistiche del bot per il messaggio di benvenuto."""
    conn = _get_conn()
    return {
        "active_users": conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_active = 1").fetchone()["cnt"],
        "total_autobook_items": conn.execute("SELECT COUNT(*) as cnt FROM auto_book_items").fetchone()["cnt"],
        "active_autobook_items": conn.execute("SELECT COUNT(*) as cnt FROM auto_book_items WHERE is_active = 1").fetchone()["cnt"],
        "autobook_success": conn.execute("SELECT COUNT(*) as cnt FROM booking_log WHERE action='autobook' AND success=1").fetchone()["cnt"],
        "book_success": conn.execute("SELECT COUNT(*) as cnt FROM booking_log WHERE action='book' AND success=1").fetchone()["cnt"],
        "courses_in_cache": conn.execute("SELECT COUNT(DISTINCT service_id) as cnt FROM schedule_cache").fetchone()["cnt"],
    }


# ═══════════════════════════════════════════════════════════
# BOOKING REMINDERS (3h / 60 min)
# ═══════════════════════════════════════════════════════════

def upsert_booking_reminder(telegram_id: int, lesson_id: int, lesson_date: str,
                             start_time: str, course_name: str, instructor: str = "") -> int:
    """Inserisce o aggiorna un reminder per una prenotazione. Restituisce l'ID."""
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM booking_reminders WHERE telegram_id = ? AND lesson_id = ? AND lesson_date = ?",
        (telegram_id, lesson_id, lesson_date)
    ).fetchone()
    if existing:
        conn.execute("""
            UPDATE booking_reminders SET
                start_time = ?, course_name = ?, instructor = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (start_time, course_name, instructor, existing["id"]))
        conn.commit()
        return existing["id"]
    cur = conn.execute("""
        INSERT INTO booking_reminders
            (telegram_id, lesson_id, lesson_date, start_time, course_name, instructor)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (telegram_id, lesson_id, lesson_date, start_time, course_name, instructor))
    conn.commit()
    return cur.lastrowid


def get_booking_reminder(telegram_id: int, lesson_id: int, lesson_date: str) -> Optional[Dict]:
    """Recupera un reminder specifico."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM booking_reminders WHERE telegram_id = ? AND lesson_id = ? AND lesson_date = ?",
        (telegram_id, lesson_id, lesson_date)
    ).fetchone()
    return dict(row) if row else None


def get_all_active_users_for_reminders() -> List[Dict]:
    """Tutti gli utenti attivi con auth_token, per il checker reminder."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT telegram_id, auth_token, app_token, iyes_url, company_id, username "
        "FROM users WHERE is_active = 1 AND auth_token IS NOT NULL"
    ).fetchall()
    return [dict(r) for r in rows]


def mark_reminder_3h_sent(reminder_id: int):
    """Segna che il reminder 3h è stato inviato."""
    conn = _get_conn()
    conn.execute(
        "UPDATE booking_reminders SET reminder_3h_sent = 1, updated_at = datetime('now') WHERE id = ?",
        (reminder_id,)
    )
    conn.commit()


def mark_reminder_60m_sent(reminder_id: int):
    """Segna che il messaggio 60min è stato inviato."""
    conn = _get_conn()
    conn.execute(
        "UPDATE booking_reminders SET reminder_60m_sent = 1, updated_at = datetime('now') WHERE id = ?",
        (reminder_id,)
    )
    conn.commit()


def set_reminder_response(reminder_id: int, response: str):
    """Salva la risposta dell'utente al reminder."""
    conn = _get_conn()
    conn.execute("""
        UPDATE booking_reminders SET
            user_response = ?, responded_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
    """, (response, reminder_id))
    conn.commit()


def get_reminder_by_lesson_id(lesson_id: int, telegram_id: int) -> Optional[Dict]:
    """Recupera un reminder per lesson_id e telegram_id (per callback)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM booking_reminders WHERE lesson_id = ? AND telegram_id = ?",
        (lesson_id, telegram_id)
    ).fetchone()
    return dict(row) if row else None
