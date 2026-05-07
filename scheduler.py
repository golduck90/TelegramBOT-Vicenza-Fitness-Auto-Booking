"""
Scheduler — Esecuzione auto-booking ogni notte alle 00:10 (ora Roma)
                con retry ogni ora su errori di rete/recuperabili.

Logica:
1. Ogni notte alle 00:10 esegue _execute_all() per tutti gli item attivi
2. Se un item fallisce per errore recuperabile (rete, server 500):
   - Prima volta → avvisa utente "riproverò ogni ora"
   - Retry ogni ora, max 20 tentativi
   - Retry silenziosi (2-19): nessun avviso
   - Notifica solo su: successo ✅ / errore esplicito ❌ / 20 esauriti ⛔
3. Se errore non recuperabile (posti esauriti, omaggi terminati...):
   - Notifica subito e non ritenta
"""
import asyncio
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from zoneinfo import ZoneInfo

import db
import wellteam
import config
from telegram.constants import ParseMode

logger = logging.getLogger("scheduler")

# Ora Roma: gestione automatica DST (CET/CEST)
ROME_TZ = ZoneInfo("Europe/Rome")

TARGET_HOUR = 0      # 00:10
TARGET_MINUTE = 10

TOKEN_REFRESH_COOLDOWN = 300  # 5 min tra tentativi di refresh
DAY_NAMES_NOTIFY = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

MAX_RETRY = 20                # Max tentativi di retry
RETRY_INTERVAL_HOURS = 1      # Ogni ora


# Pattern di errori recuperabili (rete, server temporaneo)
_RETRYABLE_ERRORS = [
    "Timeout", "timed out", "ConnectionError", "connection refused",
    "Connection refused", "ReadTimeout", "ConnectTimeout",
    "NetworkError", "Bad Gateway", "Internal Server Error",
    "Service Unavailable", "502", "503", "500",
    "getaddrinfo", "Name or service not known",
    "RemoteDisconnected", "Connection reset",
    "ReadError", "ChunkedEncodingError",
]


def _is_retryable(msg: str) -> bool:
    """True se l'errore è recuperabile (rete, server down, 500 temporaneo)."""
    if not msg:
        return True
    msg_lower = msg.lower()
    return any(p.lower() in msg_lower for p in _RETRYABLE_ERRORS)


class AutoBookScheduler:
    """
    Scheduler che esegue l'auto-booking ogni notte alle 00:10 ora Roma.
    Gestisce retry automatici su errori transitori con notifiche Telegram.
    """

    def __init__(self, application=None, interval_minutes: int = 30):
        self.interval = interval_minutes
        self._application = application
        self._running = False
        self._thread: threading.Thread = None
        self._last_run_day = -1
        self._last_token_refresh: Dict[int, float] = {}  # telegram_id → timestamp
        self._last_retry_check_minute = -1

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"✅ Scheduler avviato (esecuzione notturna 00:10 + retry ogni ora ora Roma)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)

    # ── Invio messaggi Telegram (thread-safe) ──────────────────────────

    def _send_message(self, telegram_id: int, text: str):
        """Invia messaggio Telegram da thread, usando l'event loop del bot."""
        if not self._application:
            logger.warning(f"Applicazione non disponibile, skip messaggio per {telegram_id}")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if not loop or not loop.is_running():
            logger.warning(f"Loop non attivo, skip messaggio per {telegram_id}")
            return

        try:
            coro = self._application.bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception as e:
            logger.error(f"Impossibile inviare messaggio a {telegram_id}: {e}")

    # ── Notifiche utente ───────────────────────────────────────────────

    def _notify_retry_started(self, item: Dict, error_msg: str):
        """Primo tentativo fallito → avvisa utente che riproverà."""
        telegram_id = item["telegram_id"]
        text = (
            f"🤖 *Auto-Booking — Errore temporaneo*\n\n"
            f"🏋️ *{item['description']}*\n"
            f"📅 {DAY_NAMES_NOTIFY[item['day_of_week']] if 0 <= item.get('day_of_week', -1) < 7 else '?'} alle {item['start_time'][:5]}\n"
            f"{'👤 ' + item.get('instructor', '') if item.get('instructor') else ''}\n\n"
            f"❌ *{error_msg[:120]}*\n\n"
            f"🔄 *Continuerò a riprovare ogni ora.*\n"
            f"Ti avviserò appena riesco a prenotare, "
            f"o dopo 20 tentativi se il problema persiste. 🤞\n\n"
            f"⏳ Pazienta, non devi fare nulla."
        )
        self._send_message(telegram_id, text)

    def _notify_retry_success(self, item: Dict, attempts: int, date: str):
        """Retry riuscito dopo X tentativi."""
        telegram_id = item["telegram_id"]
        text = (
            f"✅ *Auto-Booking riuscito!*\n\n"
            f"🏋️ *{item['description']}*\n"
            f"📅 {date} alle {item['start_time'][:5]}\n"
            f"{'👤 ' + item.get('instructor', '') if item.get('instructor') else ''}\n\n"
            f"💪 Prenotato dopo {attempts} tentativo{'i' if attempts > 1 else ''}!\n"
            f"Buon allenamento! 🎯"
        )
        self._send_message(telegram_id, text)

    def _notify_retry_gave_up(self, item: Dict):
        """20 tentativi esauriti → smette."""
        telegram_id = item["telegram_id"]
        last_err = item.get("retry_error", "errore sconosciuto")[:100]
        text = (
            f"⛔ *Auto-Booking — 20 tentativi esauriti*\n\n"
            f"🏋️ *{item['description']}*\n"
            f"📅 {DAY_NAMES_NOTIFY[item['day_of_week']] if 0 <= item.get('day_of_week', -1) < 7 else '?'} alle {item['start_time'][:5]}\n\n"
            f"Ho riprovato per 20 ore ma il server non risponde.\n"
            f"Ultimo errore: _{last_err}_\n\n"
            f"Prenota manualmente o riprova più tardi. 🙏"
        )
        self._send_message(telegram_id, text)

    def _notify_explicit_error(self, item: Dict, error_msg: str):
        """Errore esplicito dal server (non recuperabile)."""
        telegram_id = item["telegram_id"]
        text = (
            f"❌ *Auto-Booking non riuscito*\n\n"
            f"🏋️ *{item['description']}*\n"
            f"📅 {DAY_NAMES_NOTIFY[item['day_of_week']] if 0 <= item.get('day_of_week', -1) < 7 else '?'} alle {item['start_time'][:5]}\n\n"
            f"Motivo: _{error_msg[:200]}_\n\n"
            f"Prova a prenotare manualmente dal menu 📅 Prenota."
        )
        self._send_message(telegram_id, text)

    def _notify_success(self, item: Dict, date: str):
        """Prenotazione riuscita al primo tentativo."""
        telegram_id = item["telegram_id"]
        text = (
            f"✅ *Auto-Booking — Prenotato!*\n\n"
            f"🏋️ *{item['description']}*\n"
            f"📅 {date} alle {item['start_time'][:5]}\n"
            f"{'👤 ' + item.get('instructor', '') if item.get('instructor') else ''}\n\n"
            f"💪 Buon allenamento!"
        )
        self._send_message(telegram_id, text)

    # ── Loop principale ────────────────────────────────────────────────

    def _rome_now(self) -> datetime:
        return datetime.now(ROME_TZ)

    def _loop(self):
        while self._running:
            try:
                now = self._rome_now()
                # Esegue ogni giorno alle 00:10
                if now.hour == TARGET_HOUR and now.minute >= TARGET_MINUTE and self._last_run_day != now.day:
                    self._last_run_day = now.day
                    logger.info(f"🌙 Esecuzione auto-booking notturna ({now.strftime('%Y-%m-%d %H:%M')} Roma)")
                    self._execute_all()
                else:
                    # Forza esecuzione se appena avviato (primo ciclo)
                    if self._last_run_day == -1:
                        self._last_run_day = now.day
                        logger.info(f"🚀 Esecuzione auto-booking iniziale ({now.strftime('%Y-%m-%d %H:%M')} Roma)")
                        self._execute_all()

                # Controlla retry ogni minuto (ma esegue solo quelli scaduti)
                self._process_retries()

            except Exception as e:
                logger.error(f"Errore scheduler: {e}", exc_info=True)
            time.sleep(60)  # Check ogni minuto

    # ── Esecuzione notturna ────────────────────────────────────────────

    def _execute_all(self):
        """Esegue tutte le prenotazioni automatiche."""
        items = db.get_all_enabled_auto_book_items()
        if not items:
            logger.info("Nessun item auto-booking attivo")
            return

        logger.info(f"Processo {len(items)} item auto-booking")
        now_rome = self._rome_now()

        for item in items:
            try:
                self._process_item(item, now_rome)
            except Exception as e:
                logger.error(f"Errore processando item {item.get('id')}: {e}")

        logger.info("✅ Auto-booking notturno completato")

    # ── Gestione retry (eseguito ogni minuto) ──────────────────────────

    def _process_retries(self):
        """Controlla e processa item in retry che hanno superato la scadenza."""
        items = db.get_items_needing_retry()
        if not items:
            return

        logger.info(f"🔄 Controllo retry: {len(items)} item da riprovare")
        now_utc = datetime.now()

        for item in items:
            try:
                self._process_retry_item(item, now_utc)
            except Exception as e:
                logger.error(f"Errore retry item {item.get('id')}: {e}")

    def _process_retry_item(self, item: Dict, now_utc: datetime):
        """Processa un singolo retry."""
        item_id = item["id"]
        attempt = item.get("retry_count", 1)
        telegram_id = item["telegram_id"]
        service_id = item["service_id"]
        start_time = item["start_time"][:5]
        instructor = item.get("instructor") or ""
        auth_token = item["auth_token"]
        iyes_url = item.get("iyes_url", "") or config.WELLTEAM_IYES_URL
        company_id = item.get("company_id", 2)

        # La data target: cerco la prossima occorrenza del giorno
        day_of_week = item["day_of_week"]
        today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        target_lesson = None
        target_date = None

        for day_offset in range(14):
            check_date = today + timedelta(days=day_offset)
            if check_date.weekday() != day_of_week:
                continue
            date_str = check_date.strftime("%Y-%m-%d")
            if item.get("last_booked_date") == date_str and item.get("last_booked_lesson"):
                # Già prenotato per questa data (dal sistema auto-booking)
                logger.info(f"Item #{item_id}: già prenotato per {date_str}, retry annullato")
                db.reset_auto_book_retry(item_id)
                return

            success, lessons = self._get_schedule_with_refresh(
                auth_token, item, date_str, date_str, company_id
            )
            if not success or not lessons:
                continue

            for lesson in lessons:
                if lesson.get("IDServizio") != service_id:
                    continue
                les_start = lesson.get("StartTime", "")[11:16] if len(lesson.get("StartTime", "")) > 16 else lesson.get("StartTime", "")
                if les_start != start_time:
                    continue
                if instructor and instructor.lower() not in lesson.get("AdditionalInfo", "").lower():
                    continue

                if lesson.get("IsUserPresent"):
                    # Già prenotato (magari manualmente)
                    db.update_auto_book_last_booked(item_id, lesson.get("IDLesson"), date_str)
                    logger.info(f"Item #{item_id}: già prenotato per {date_str} (retry annullato)")
                    return

                if lesson.get("AvailablePlaces", 1) == 0:
                    logger.info(f"Item #{item_id}: {date_str} — posti esauriti")
                    continue

                target_lesson = lesson
                target_date = date_str
                break

            if target_lesson:
                break

        if not target_lesson:
            logger.debug(f"Item #{item_id}: nessuna lezione trovata nel retry")
            # Se non trovo lezioni, incremento comunque il retry?
            # No, se non ci sono lezioni per i prossimi 14 giorni, il corso
            # potrebbe non esistere più. Meglio notificare e smettere.
            error_msg = item.get("retry_error") or "Nessuna lezione trovata"
            if attempt >= MAX_RETRY:
                db.reset_auto_book_retry(item_id)
                self._notify_retry_gave_up(item)
                logger.warning(f"⛔ Item #{item_id}: retry esauriti ({MAX_RETRY}), smetto")
            else:
                # Riprogramma per dopo
                db.setup_auto_book_retry(item_id, error_msg, RETRY_INTERVAL_HOURS)
                logger.debug(f"Item #{item_id}: riprogrammo retry tra {RETRY_INTERVAL_HOURS}h (tentativo {attempt + 1}/{MAX_RETRY})")
            return

        # Trovata lezione → prova a prenotare
        lesson = target_lesson
        lesson_id = lesson["IDLesson"]
        date = lesson["DateLesson"][:10]
        bs = lesson["StartTime"]
        bs_time = bs[11:19] if len(bs) >= 19 and "1900-01-01" in bs else bs
        bs = f"{date}T{bs_time}"
        be = lesson["EndTime"]
        be_time = be[11:19] if len(be) >= 19 and "1900-01-01" in be else be
        be = f"{date}T{be_time}"

        ok, msg = self._book_with_refresh(auth_token, item, lesson_id, service_id, bs, be)
        description = item["description"]

        if ok:
            # ✅ SUCCESSO
            db.update_auto_book_last_booked(item_id, lesson_id, date)
            db.log_booking(telegram_id, description, lesson_id, bs, "autobook", True, msg)
            self._notify_retry_success(item, attempt, date)
            logger.info(f"✅ AUTO-BOOK RETRY #{item_id}: {description} il {date} (tentativo {attempt}/{MAX_RETRY})")
        else:
            # ❌ FALLITO
            db.log_booking(telegram_id, description, lesson_id, bs, "autobook", False, msg)
            logger.warning(f"❌ AUTO-BOOK RETRY #{item_id} FALLITO ({attempt}/{MAX_RETRY}): {description}: {msg}")

            if _is_retryable(msg):
                # Errore recuperabile → riprogramma
                if attempt >= MAX_RETRY:
                    db.reset_auto_book_retry(item_id)
                    self._notify_retry_gave_up(item)
                    logger.warning(f"⛔ Item #{item_id}: {MAX_RETRY} tentativi esauriti, smetto")
                else:
                    db.setup_auto_book_retry(item_id, msg, RETRY_INTERVAL_HOURS)
                    logger.info(f"🔄 Item #{item_id}: riprogrammo retry tra {RETRY_INTERVAL_HOURS}h (tentativo {attempt + 1}/{MAX_RETRY})")
            else:
                # Errore NON recuperabile → notifica e smetti
                db.reset_auto_book_retry(item_id)
                self._notify_explicit_error(item, msg)
                logger.warning(f"🚫 Item #{item_id}: errore non recuperabile: {msg}")

    # ── Processa un item (run notturno) ────────────────────────────────

    def _process_item(self, item: Dict, now_rome: datetime):
        """
        Processa un singolo item: cerca la prossima lezione e prenota.
        Se fallisce con errore recuperabile, imposta retry automatico.
        """
        telegram_id = item["telegram_id"]
        item_id = item["id"]
        service_id = item["service_id"]
        start_time = item["start_time"][:5]
        instructor = item.get("instructor") or ""
        auth_token = item["auth_token"]
        iyes_url = item.get("iyes_url", "") or config.WELLTEAM_IYES_URL
        company_id = item.get("company_id", 2)

        # Se c'è ancora un retry pendente, skippa (il retry è già in corso)
        if item.get("retry_count", 0) > 0:
            logger.debug(f"Item #{item_id}: retry già in corso ({item['retry_count']}/{MAX_RETRY}), skip esecuzione notturna")
            return

        # Prossimi 14 giorni
        today = now_rome.replace(hour=0, minute=0, second=0, microsecond=0)
        target_lesson = None
        target_date = None

        for day_offset in range(14):
            check_date = today + timedelta(days=day_offset)
            if check_date.weekday() != item["day_of_week"]:
                continue

            date_str = check_date.strftime("%Y-%m-%d")

            if item.get("last_booked_date") == date_str and item.get("last_booked_lesson"):
                logger.debug(f"Item #{item_id}: già prenotato per {date_str}")
                continue

            if check_date.date() == today.date():
                try:
                    h, m = map(int, start_time.split(":"))
                    lesson_dt = today.replace(hour=h, minute=m)
                    if now_rome > lesson_dt + timedelta(minutes=5):
                        continue
                except ValueError:
                    pass

            success, items = self._get_schedule_with_refresh(
                auth_token, item, date_str, date_str, company_id
            )

            if not success or not items:
                continue

            for lesson in items:
                if lesson.get("IDServizio") != service_id:
                    continue
                les_start = lesson.get("StartTime", "")[11:16] if len(lesson.get("StartTime", "")) > 16 else lesson.get("StartTime", "")
                if les_start != start_time:
                    continue
                if instructor and instructor.lower() not in lesson.get("AdditionalInfo", "").lower():
                    continue

                if lesson.get("IsUserPresent"):
                    db.update_auto_book_last_booked(item_id, lesson.get("IDLesson"), date_str)
                    logger.info(f"Item #{item_id}: già prenotato per {date_str}")
                    return

                if lesson.get("AvailablePlaces", 1) == 0:
                    logger.info(f"Item #{item_id}: {date_str} — posti esauriti")
                    continue

                target_lesson = lesson
                target_date = date_str
                break

            if target_lesson:
                break

        if not target_lesson:
            logger.debug(f"Item #{item_id}: nessuna lezione trovata nei prossimi 14 giorni")
            return

        # PRENOTA!
        lesson = target_lesson
        lesson_id = lesson["IDLesson"]
        date = lesson["DateLesson"][:10]
        bs = lesson["StartTime"]
        bs_time = bs[11:19] if len(bs) >= 19 and "1900-01-01" in bs else bs
        bs = f"{date}T{bs_time}"
        be = lesson["EndTime"]
        be_time = be[11:19] if len(be) >= 19 and "1900-01-01" in be else be
        be = f"{date}T{be_time}"

        ok, msg = self._book_with_refresh(
            auth_token, item, lesson_id, service_id, bs, be
        )

        if ok:
            logger.info(f"✅ AUTO-BOOK #{item_id}: {item['description']} il {date} alle {start_time}")
            db.update_auto_book_last_booked(item_id, lesson_id, date)
            db.log_booking(telegram_id, item["description"], lesson_id, bs, "autobook", True, msg)
            self._notify_success(item, date)
        else:
            logger.warning(f"❌ AUTO-BOOK #{item_id} FALLITO: {item['description']}: {msg}")
            db.log_booking(telegram_id, item["description"], lesson_id, bs, "autobook", False, msg)

            if _is_retryable(msg):
                # Errore recuperabile → avvia retry
                db.setup_auto_book_retry(item_id, msg, RETRY_INTERVAL_HOURS)
                # Prima notifica: avvisa che riproverà
                if not item.get("retry_notified"):
                    db.mark_auto_book_retry_notified(item_id)
                    self._notify_retry_started(item, msg)
                logger.info(f"🔄 Item #{item_id}: avviato retry automatico (1/{MAX_RETRY})")
            else:
                # Errore esplicito → notifica subito
                self._notify_explicit_error(item, msg)
                logger.warning(f"🚫 Item #{item_id}: errore non recuperabile: {msg}")

    # ── Token refresh ──────────────────────────────────────────────────

    def _refresh_token(self, item: Dict) -> Optional[str]:
        """
        Tenta di rinnovare il token WellTeam usando la password cifrata.
        Rispetta un cooldown per evitare refresh continui sullo stesso utente.
        """
        telegram_id = item["telegram_id"]
        now = time.time()

        last_refresh = self._last_token_refresh.get(telegram_id, 0)
        if telegram_id not in self._last_token_refresh:
            logger.warning(f"User {telegram_id}: _last_token_refresh vuoto (cache persa dopo riavvio)")
        if now - last_refresh < TOKEN_REFRESH_COOLDOWN:
            logger.debug(f"User {telegram_id}: refresh token in cooldown ({int(now - last_refresh)}s)")
            return None

        username = item.get("username", "")
        if not username:
            logger.error(f"User {telegram_id}: username mancante, impossibile refresh token")
            return None

        password = db.get_user_password(telegram_id)
        if not password:
            logger.error(f"User {telegram_id}: nessuna password salvata, impossibile refresh token")
            return None

        logger.info(f"🔄 User {telegram_id}: tentativo refresh token...")
        result = wellteam.authenticate(username, password)

        if not result:
            logger.warning(f"❌ User {telegram_id}: refresh token fallito (password errata?)")
            return None

        new_token = result["auth_token"]
        db.update_tokens(telegram_id, auth_token=new_token)
        self._last_token_refresh[telegram_id] = now
        logger.info(f"✅ User {telegram_id}: token rinnovato con successo")
        return new_token

    # ── Helper con refresh ─────────────────────────────────────────────

    def _get_schedule_with_refresh(self, auth_token: str, item: Dict,
                                    start_date: str, end_date: str,
                                    company_id: int) -> tuple:
        """Chiama get_schedule con retry se il token è scaduto."""
        iyes_url = item.get("iyes_url", "") or config.WELLTEAM_IYES_URL

        success, result = wellteam.get_schedule(
            auth_token=auth_token,
            app_token=config.WELLTEAM_APP_TOKEN,
            iyes_url=iyes_url,
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
        )

        if success:
            return success, result

        logger.info(f"Item #{item['id']}: get_schedule fallito, tentativo refresh token...")
        new_token = self._refresh_token(item)
        if new_token:
            return wellteam.get_schedule(
                auth_token=new_token,
                app_token=config.WELLTEAM_APP_TOKEN,
                iyes_url=iyes_url,
                start_date=start_date,
                end_date=end_date,
                company_id=company_id,
            )

        return False, result

    def _book_with_refresh(self, auth_token: str, item: Dict,
                            lesson_id: int, service_id: int,
                            start_time: str, end_time: str) -> tuple:
        """Chiama book_course con retry se il token è scaduto."""
        iyes_url = item.get("iyes_url", "") or config.WELLTEAM_IYES_URL

        ok, msg = wellteam.book_course(
            auth_token=auth_token,
            app_token=config.WELLTEAM_APP_TOKEN,
            iyes_url=iyes_url,
            lesson_id=lesson_id,
            service_id=service_id,
            start_time=start_time,
            end_time=end_time,
        )

        if ok:
            return ok, msg

        logger.info(f"Item #{item['id']}: book_course fallito, tentativo refresh token...")
        new_token = self._refresh_token(item)
        if new_token:
            return wellteam.book_course(
                auth_token=new_token,
                app_token=config.WELLTEAM_APP_TOKEN,
                iyes_url=iyes_url,
                lesson_id=lesson_id,
                service_id=service_id,
                start_time=start_time,
                end_time=end_time,
            )

        return False, msg
