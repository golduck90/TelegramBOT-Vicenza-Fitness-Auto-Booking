# Code Review: bot-palestra (Vicenza Fitness Bot)

**Review date:** 2026-05-06  
**Reviewer:** Automated code analysis  
**Scope:** All 17 Python files + Dockerfile  
**Bot version:** v5.0 (python-telegram-bot v22.7)

---

## 🔴 CRITICAL — Must Fix Immediately

### C1. `NameError` in `_confirm_autobook` — missing `context` parameter

**File:** `handlers/corsi.py`, line 445  
**Severity:** Crash on code path

The function signature is:
```python
async def _confirm_autobook(query, c, item_id, description, extra=""):
```
But at line 445 it references `context.user_data.pop("book_course", None)` — `context` is **not defined** in this scope. This raises `NameError` every time a user activates auto-booking from the course selection flow (callback `book_do_auto`).

**Fix:** Add `context` as a parameter and pass it from all call sites (`cb_book_auto` at lines 355, 368, 388, 394, 399).

### C2. Hardcoded timezone offset — scheduler wrong during CET (winter)

**File:** `scheduler.py`, line 29  
**Severity:** Scheduler misses nightly run 5 months/year

```python
ROME_OFFSET = timezone(timedelta(hours=2))  # Maggio → CEST (+2)
```
This is hardcoded to UTC+2 (CEST). During winter (CET, UTC+1, ~late-Oct to late-Mar), `datetime.now(ROME_OFFSET)` returns time with +2 offset while actual Rome time is +1. The TARGET_HOUR (0) check at line 191 will never match when `now.hour == 1` (what +2 produces when Rome is at midnight +1).

**Fix:** Use `zoneinfo.ZoneInfo("Europe/Rome")` (Python 3.9+):
```python
from zoneinfo import ZoneInfo
ROME_TZ = ZoneInfo("Europe/Rome")
```

### C3. Naive vs aware datetime comparison in scheduler

**File:** `scheduler.py`, lines 400-407  
**Severity:** Crash at runtime

```python
today = now_rome.replace(hour=0, minute=0, second=0, microsecond=0)
...
if now_rome > lesson_dt + timedelta(minutes=5):  # TypeError!
```
`today` is naive (tzinfo stripped by `.replace()`) → `lesson_dt` is naive.  
`now_rome` is timezone-aware (has `ROME_OFFSET`).  
Comparing naive with aware datetime raises `TypeError: can't compare offset-naive and offset-aware datetimes`.

**Fix:** Don't strip tzinfo — use `now_rome` directly and keep tzinfo throughout.

### C4. Exposed company-level `WELLTEAM_APP_TOKEN` in source + git history

**File:** `config.py`, line 24-27  
**Severity:** Security — token visible in repository forever

The default value of `WELLTEAM_APP_TOKEN` is a ~256-char hex token hardcoded in `config.py`. This is a company-level token for the Vicenza Fitness WellTeam API. Since it's in git history (`cfd4f44` and earlier), anyone with access to this repo can use it.

**Fix:** Remove the hardcoded default, require it via environment variable. Rotate the token at WellTeam. Purge it from git history with `git filter-repo`.

### C5. `WELLTEAM_APP_TOKEN` double-sent in login headers

**File:** `wellteam.py`, lines 48-52  
**Severity:** Incorrect API contract for authentication

```python
headers = {
    ...
    "AppToken": config.WELLTEAM_APP_TOKEN,   # Set at line 48
    ...
}
if config.WELLTEAM_APP_TOKEN:                 # Always true if default exists
    headers["AppToken"] = config.WELLTEAM_APP_TOKEN  # Overwrites with same value
```
The `if` block at lines 51-52 is dead code — it unconditionally overwrites the header with the same value. Minor, but indicates confusion about when the AppToken is used vs omitted.

**More importantly:** The login endpoint at `/security/authenticate` should use the **bootstrap** AppToken (the company-level one), while subsequent API calls should use the user-level token. The comment at line 43 says "IYESUrl + AppToken headers are RICHIESTI" for login, but the OLD system (`_headers()`) also always sends `config.WELLTEAM_APP_TOKEN` in every API call — which may be incorrect if the user has a different per-user `app_token`.

---

## 🟠 HIGH — Should Fix Soon

### H1. Dead code: `handlers/bookings.py` is never imported

**File:** `main.py`, lines 97-111 (register_all_handlers)  
`handlers/bookings.py` defines `register()` and `cmd_prenotazioni`/`cmd_book`, but **no line in main.py imports or registers it**. The entire file is dead code.

`handlers/corsi.py` already registers its own `cmd_prenotazioni` handler (line 816) and `cmd_prenotazioni` is also in `handlers/corsi.py` (line 668). The only unique handler in `bookings.py` is `cmd_book` (for `/book <course_name>`), which is **unreachable**.

### H2. Dead code: `handlers/courses.py` is never imported

**File:** `main.py`, register_all_handlers  
`handlers/courses.py` defines `cmd_courses` and `cmd_schedule` with `/corsi` and `/calendario` commands, but **it's never imported**. The `/corsi` command is also registered in `handlers/corsi.py` (line 814), which IS imported. But `/calendario` and `corsi_disponibili` from `courses.py` are dead.

Both `handlers/courses.py` and `SERVICE_ID_MAP` are only referenced from `handlers/bookings.py` (also dead). No live code uses `SERVICE_ID_MAP`.

### H3. SQLite shared global `_db_lock` is defined but never used

**File:** `db.py`, line 14  
```python
_db_lock = threading.Lock()
```
It's never acquired anywhere. Multiple threads (main bot async, scheduler, reminder checker, cache thread) all write to the same SQLite database concurrently. SQLite in WAL mode with `busy_timeout=5000` provides _some_ protection, but without explicit locking, concurrent writes can lead to `sqlite3.OperationalError: database is locked`.

**Fix:** Use `_db_lock` to serialize writes, or switch to a connection pool.

### H4. Rate limiter is not thread-safe

**File:** `handlers/ratelimit.py`, line 8  
```python
_user_timestamps: dict = defaultdict(list)
```
Shared mutable state (`_user_timestamps`) is accessed and mutated from multiple threads without a lock. The scheduler, reminder checker, and main bot threads all call handler functions that invoke `check_rate_limit`. This can lead to race conditions, corrupted counters, or infinite loops.

**Fix:** Add `threading.Lock()` around all reads/writes to `_user_timestamps`.

### H5. Password logged in HTTP query params + Telegram command args

**Files:** 
- `wellteam.py`, line 56: `params={"login": username, "password": password, ...}`
- `handlers/auth.py`, line 149: `/login <username> <password>`

**Issues:**
1. GET request with password in query params → password appears in HTTP access logs, browser history, and proxy logs.
2. `/login username password` via Telegram command → Telegram logs all commands server-side.

**Mitigation:** Use POST for authentication. The direct `/login` command is documented as convenience but exposes passwords to Telegram's logging infrastructure.

### H6. ReminderChecker uses `application.loop` — fragile API access

**File:** `handlers/reminders.py`, line 192  
```python
loop = self._application.loop
```
`Application.loop` is an internal/legacy attribute in python-telegram-bot v20+. It may be `None` when the application hasn't started, or may not exist in future versions. The check at line 193 (`if loop and loop.is_running()`) is good, but accessing it could raise `AttributeError`.

**Fix:** Use `asyncio.get_running_loop()` or `self._application.create_task()` (ptb v20+).

### H7. `_process_retry_item` compares last_booked_date which may never match

**File:** `scheduler.py`, line 269  
```python
if item.get("last_booked_date") == date_str:
```
If `last_booked_date` is set but the lesson_id differs (user manually booked a different slot on the same day), the retry stops. This is probably intentional but worth verifying.

Also, the check at line 269 compares against `_retry_item`'s item data which may have stale `last_booked_date` if the user manually booked since the last retry cycle.

### H8. `wellteam.authenticate` doesn't validate token before returning

**File:** `wellteam.py`, lines 73-91  
The `/webuser/me` call (to get user_id) is treated as optional — if it fails, `user_id=0` and `app_token=auth_token` are returned anyway. This means a user could be "authenticated" (login succeeds) but the token might not work for subsequent API calls. No retry or fallback is attempted.

---

## 🟡 MEDIUM — Improvements

### M1. No `__init__.py` files for handler package

**File:** `handlers/__init__.py` is empty (0 lines). This is fine for Python 3.3+ (namespace packages), but an explicit init could expose shared utilities.

### M2. Direct access to `db._get_conn()` from other modules

**Files:**
- `schedule_cache.py`, line 24
- `handlers/autobook.py`, line 102

These access a private function (`_get_conn`) from `db.py`. While it works, this couples other modules to the internal implementation. `db.py` should expose a public `get_connection()` method.

### M3. Duplicate handler for `/prenotazioni` command

`handlers/corsi.py` (line 816) and `handlers/bookings.py` (line 205, dead) both register `CommandHandler("prenotazioni", ...)`. Even if `bookings.py` is dead, having duplicate handlers in the same file (`corsi.py` line 816 registers `cmd_prenotazioni` AND line 811 registers `menu_prenotazioni` callback) is confusing.

### M4. `cb_menu_home` is dead code

**File:** `handlers/menu.py`, lines 64-68  
The function `cb_menu_home` is defined but never registered as a handler. The `menu_home` callback is handled by `cmd_start` via the pattern `^menu_home$` at line 184.

### M5. Redundant `force_refresh` callback pattern

`menu.py` line 186 registers `^force_refresh$` pattern.  
`corsi.py` line 808+ does NOT register a handler for `force_refresh` — it relies on `menu.py`'s handler. This is fragile cross-file coupling.

### M6. Token refresh sends `app_token=config.WELLTEAM_APP_TOKEN` always

**File:** `scheduler.py`, line 515  
```python
db.update_tokens(telegram_id, auth_token=new_token, app_token=config.WELLTEAM_APP_TOKEN)
```
This overwrites the user's stored `app_token` with the company-level AppToken, which may not be correct. In the original login flow (`handlers/auth.py`, lines 96-101), `app_token=config.WELLTEAM_APP_TOKEN` is also used — so the app_token field may only ever hold the company token, not a user-specific one. This is confusing naming: the `app_token` column stores the company AppToken, not a user token.

### M7. `_last_token_refresh` cooldown is per-user but not persisted

**File:** `scheduler.py`, line 73  
```python
self._last_token_refresh: Dict[int, float] = {}  # in-memory only
```
If the bot restarts, this dict is cleared, so every user gets refreshed immediately on the first retry. Minor inefficiency.

### M8. `get_user_password` returns plaintext — encryption is cosmetic

**File:** `db.py`, lines 281-286  
The Fernet encryption key is stored on disk (`.fernet_key`) or in memory (`_AUTO_GENERATED_KEY`). If an attacker gains filesystem access, they can read the key and decrypt all passwords. This is better than plaintext but far from production-grade security. Consider:
- Use a proper secrets manager (Hashicorp Vault, AWS Secrets Manager)
- Or at minimum, require the `FERNET_KEY` environment variable (line 43 is optional — falls back to file)

### M9. `is_locked` compares naive + aware datetimes

**File:** `db.py`, lines 267-278  
```python
lock_time = datetime.fromisoformat(user["locked_until"])  # naive (from isoformat string)
if datetime.utcnow() < lock_time:                          # naive vs naive — works but ...
```
`datetime.utcnow()` returns naive UTC time. `fromisoformat()` on a string like `"2026-05-06T05:48:00"` also returns naive. This works but is timezone-ambiguous. If the server clock is not UTC (e.g., Rome time with Docker TZ), the comparison is off by hours.

**Fix:** Use `datetime.now(timezone.utc)` and store/compare timezone-aware datetimes.

### M10. `_get_schedule_with_refresh` refreshes token on ANY failure

**File:** `scheduler.py`, lines 522-552  
The code calls `wellteam.get_schedule()` and if it fails, attempts a token refresh and retries. But the initial failure could be due to any reason (no lessons, server error, network). Token refresh is attempted even for non-auth failures, which wastes API calls and can lock the user out if the password changed.

**Fix:** Only refresh on HTTP 401 or "Unauthorized" errors.

### M11. Cancel-60min check uses naive datetime comparison

**File:** `handlers/corsi.py`, lines 746-747  
```python
lesson_dt = datetime.strptime(start_iso[:16], "%Y-%m-%dT%H:%M")
minutes_until = (lesson_dt - datetime.now()).total_seconds() / 60.0
```
Both are naive, but `datetime.now()` returns local time while `start_iso` is the API's time (which may be timezone-specific). This can cause off-by-hour errors during DST transitions.

---

## 🟢 LOW — Suggestions

### L1. No input validation on `service_id` in callback data parsing

**File:** `handlers/corsi.py`, line 268  
```python
service_id = int(parts[0])
```
If `parts[0]` is not a valid integer (e.g., user sends a malformed callback), this raises `ValueError` and crashes the handler. The broad `cb_pick_course` pattern (`^book_pick_\d+_\d+_.+$`) should ensure it's digits, but the `rsplit` logic could produce unexpected results.

### L2. `_send_message` in scheduler uses direct HTTP — bypasses ptb rate limiter

**File:** `scheduler.py`, lines 100-108  
The scheduler sends messages via raw `requests.post` to Telegram API, bypassing the `AIORateLimiter` configured on the application builder. This could trigger Telegram's rate limits without the bot knowing.

**Fix:** Use `asyncio.run_coroutine_threadsafe` with `application.bot.send_message()` like the ReminderChecker does.

### L3. No logging configuration for `sqlite3` or `requests` libraries

Only `httpx` and `httpcore` loggers are silenced. `requests` and `sqlite3` can be noisy at DEBUG level.

### L4. `schedule_cache.refresh_schedule` uses `datetime.now()` (naive)

**File:** `schedule_cache.py`, line 54  
```python
today = datetime.now()
```
This returns naive local time. In the Docker container with `TZ=Europe/Rome`, this is Rome time. But the cache key `week_key` at line 82 uses `now.strftime("%Y-W%W")` — `%W` depends on the system locale. This could cause inconsistent cache keys if the system timezone changes.

### L5. No healthcheck or readiness probe in Dockerfile

**File:** `Dockerfile`  
No `HEALTHCHECK` instruction. The bot runs as a long-lived process with no way to detect if it's hung or crashed.

### L6. Inconsistent Python version: `3.13-slim` in Dockerfile

**File:** `Dockerfile`, line 1  
```dockerfile
FROM python:3.13-slim
```
Python 3.13 is very new and may have compatibility issues with certain libraries. The codebase was developed with 3.11 (evidenced by `__pycache__/...cpython-311.pyc` files). Consider pinning to 3.11 or 3.12 for stability.

### L7. Log file grows unbounded on disk

**File:** `config.py`, line 72  
```python
LOG_FILE = BASE_DIR / "bot.log"
```
The `RotatingFileHandler` at main.py line 35-37 limits to 10MB with 3 backups, but the file path is at the project root. In Docker, this is inside the container and gets lost on restart. Consider logging to stdout (Docker best practice) and only using file logging for non-Docker deployments.

### L8. PicklePersistence at project root

**File:** `main.py`, lines 133-141  
`bot_state.pickle` is stored at `BASE_DIR`. In Docker, this means the persistence file is inside the container image. If the container restarts (e.g., due to updates), the persistence file is lost unless a volume is mounted.

**Fix:** Use a dedicated volume path, or make the path configurable via environment variable.

### L9. `_check_cache` calls `refresh_schedule` synchronously

**File:** `handlers/corsi.py`, lines 100-114  
```python
def _check_cache(telegram_id):
    ...
    refresh_schedule(telegram_id, ...)  # Blocking call
```
This is an `async`-defined calling context (called from `_show_corsi` which is `async`) but `_check_cache` is a regular `def`. Since `refresh_schedule` uses `requests` (synchronous), it blocks the asyncio event loop for up to 15 seconds (timeout). This degrades performance under load.

**Fix:** Make `_check_cache` async and run `refresh_schedule` in a thread executor.

### L10. No rate limits on callback query handlers

`@rate_limit` and `@require_auth` are applied to command handlers (`cmd_lista_corsi`, `cmd_prenota`) but NOT to their callback query equivalents (`cb_show_day`, `cb_pick_course`, `cb_book_now`, etc.). A user could rapidly click callback buttons and bypass rate limiting.

---

## 🏗️ ARCHITECTURAL Notes

### A1. Dual auto-booking systems (legacy + new)

The database has TWO auto-booking tables:
- `autobook_rules` (line 60-74 in db.py) — the OLD system
- `auto_book_items` (line 109-123) — the NEW system

The schema defines both, but the scheduler and UI code only use `auto_book_items`. The `autobook_rules` table and its associated functions (`add_autobook_rule`, `get_user_autobook_rules`, `get_all_enabled_rules`, `toggle_autobook_rule`, `remove_autobook_rule`, `update_autobook_last_booked`) are **dead code**. They should be removed to avoid confusion.

### A2. Three separate background threads with no coordination

1. **AutoBookScheduler** (`scheduler.py`) — checks every 60s
2. **ReminderChecker** (`reminders.py`) — checks every 30s
3. **Cache refresh** (`main.py`, line 173) — runs once at startup

All three access the same SQLite database and the same WellTeam API. There's no throttling or coordination between them. Under heavy load, this could overwhelm the WellTeam API.

### A3. Synchronous `requests` library in an async application

The entire codebase uses `requests` (synchronous) inside an `asyncio`-based application (python-telegram-bot). All API calls block the event loop:

- `wellteam.py` — all API calls block for up to 15s
- `scheduler.py` — runs in a separate thread, which is correct
- `reminders.py` — runs in a separate thread, correct
- `handlers/corsi.py`, `auth.py`, `qr.py` — run on the main event loop, **WRONG**

When `cmd_prenotazioni` calls `wellteam.get_schedule()`, the entire bot is blocked for up to 15 seconds. Under load, this causes noticeable lag.

**Fix:** Either make the handler calls async (use `httpx.AsyncClient`), or wrap blocking calls in `asyncio.to_thread()`.

### A4. Token management is fragmented

- User tokens are stored in `users` table
- Token refresh is handled in `scheduler.py` (`_refresh_token`)
- Login sets tokens in `auth.py`
- The `app_token` field stores the company-level AppToken, not a user-specific token
- The scheduler's `_book_with_refresh` and `_get_schedule_with_refresh` implement a custom retry-on-failure pattern

This should be centralized into a single `TokenManager` that handles refresh transparently, similar to OAuth2 token refresh patterns.

### A5. Global `requests.Session` shared across threads

**File:** `wellteam.py`, lines 13-26  
```python
_session = None
def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session
```
While `requests.Session` is nominally thread-safe for most operations, there's a race condition in the lazy initialization (`_session is None` check + assignment is not atomic). Two threads entering simultaneously could create two sessions, though only one is kept.

**Fix:** Use `threading.Lock` or initialize eagerly at module level.

### A6. No test infrastructure

There are zero test files, no `tests/` directory, no `pytest` configuration, no `conftest.py`. The project has no automated testing whatsoever.

### A7. No CI/CD configuration

No `.github/workflows/`, no `docker-compose.yml`, no `Makefile`. The Dockerfile exists but there are no deployment manifests.

### A8. The `busy_timeout` safeguard

`PRAGMA busy_timeout=5000` is set on every connection. This means if a write is blocked by another writer, SQLite will wait up to 5 seconds before raising `OperationalError: database is locked`. The code does NOT handle this exception anywhere — a write that times out will crash the handler. Since there are 3+ concurrent threads writing to the DB, this is a realistic risk.

---

## Summary by File

| File | Lines | Critical | High | Medium | Low | Notes |
|------|-------|----------|------|--------|-----|-------|
| main.py | 195 | 0 | 0 | 1 | 3 | No test, no CI/CD |
| config.py | 72 | **1** | 0 | 1 | 1 | Hardcoded token, log path |
| db.py | 817 | 0 | 1 | 2 | 1 | Dead lock, password crypto, WAL |
| wellteam.py | 327 | 0 | 1 | 1 | 1 | Token in query params, session race |
| scheduler.py | 586 | **2** | 1 | 2 | 1 | Timezone hardcoded, naive/aware compare, token refresh |
| schedule_cache.py | 116 | 0 | 1 | 1 | 1 | Private func access, naive datetime |
| handlers/corsi.py | 818 | **1** | 0 | 2 | 2 | Missing `context` param, callback data fragility |
| handlers/menu.py | 188 | 0 | 0 | 1 | 0 | Dead code `cb_menu_home` |
| handlers/auth.py | 265 | 0 | 1 | 1 | 0 | Password in command args |
| handlers/bookings.py | 206 | 0 | 1 | 0 | 0 | Dead code (never imported) |
| handlers/courses.py | 130 | 0 | 1 | 0 | 0 | Dead code (never imported) |
| handlers/autobook.py | 187 | 0 | 0 | 1 | 1 | Private func access |
| handlers/reminders.py | 456 | 0 | 1 | 1 | 0 | `application.loop` fragility |
| handlers/qr.py | 208 | 0 | 0 | 0 | 1 | Temp file handling |
| handlers/decorators.py | 69 | 0 | 0 | 0 | 0 | Clean |
| handlers/ratelimit.py | 37 | 0 | **1** | 0 | 0 | Not thread-safe |
| handlers/__init__.py | 0 | 0 | 0 | 0 | 0 | Empty |
| Dockerfile | 30 | 0 | 0 | 0 | 2 | No healthcheck, Python 3.13 |

**Totals:** 5 CRITICAL, 8 HIGH, 13 MEDIUM, 13 LOW

---

## Recommended Fix Priority

1. **IMMEDIATE:** C1 (NameError crash), C2 (scheduler misses winter), C3 (datetime TypeError), C5/Rotate token
2. **WITHIN WEEK:** H1/H2 (register or remove dead code), H3 (database locking), H4 (rate limiter thread-safety), H8 (auth validation)
3. **WITHIN MONTH:** All MEDIUM items — particularly M1-M4 (code clarity), M6 (token management), M9 (timezone safety)
4. **BACKLOG:** LOW items and architectural notes
