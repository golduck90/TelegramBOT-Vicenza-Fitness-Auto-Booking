"""
Handler: Booking Reminders (3h / 60min).

Ogni ora ai minuti :05 e :35 controlla tutte le prenotazioni future
degli utenti e invia reminder appropriati.

Logica:
- 3h prima → chiede conferma con bottoni SI/NO
  - SI → "Buon allenamento!"
  - NO → cancella prenotazione, "Grazie per aver liberato il posto"
  - Nessuna risposta → NON fare nulla
- < 60 min senza risposta → "Confermato, solo telefono +390444276206 per disdire"
- Blocco cancellazione manuale se < 60 min (in corsi.py)
"""
import asyncio
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode

import db
import wellteam
import config
from handlers.decorators import rate_limit

logger = logging.getLogger("reminders")

# Check ogni 5 minuti (invece che :05/:35)
CHECK_EVERY_N_MINUTES = 5
SLEEP_SECONDS = 15

# Soglie (minuti)
THRESHOLD_3H = 180     # 3 ore
THRESHOLD_60M = 60     # 60 minuti

# Callback patterns
CALLBACK_YES = "rem_yes_"
CALLBACK_NO = "rem_no_"

# Telefono Vicenza Fitness
PHONE_VF = "+39 0444 276 206"


class ReminderChecker:
    """
    Thread checker che ogni ora a :05 e :35:
    1. Ottiene tutti gli utenti attivi
    2. Per ognuno, chiama get_my_books
    3. Controlla ogni prenotazione e invia reminder appropriati
    """

    def __init__(self, application):
        self._application = application
        self._running = False
        self._thread: threading.Thread = None
        self._app_loop: asyncio.AbstractEventLoop = None

    def start(self):
        if self._running:
            return
        self._running = True
        # Acquisisce l'event loop principale (per invio messaggi da thread)
        try:
            self._app_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._app_loop = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"✅ ReminderChecker avviato (check ogni {CHECK_EVERY_N_MINUTES} minuti)")

    def stop(self):
        self._running = False

    def _run(self):
        last_checked_minute = -1
        while self._running:
            try:
                now = datetime.now()
                if now.minute % CHECK_EVERY_N_MINUTES == 0 and now.minute != last_checked_minute:
                    last_checked_minute = now.minute
                    logger.debug(f"🔍 Check reminder: {now.strftime('%H:%M')}")
                    self._check_all()
            except Exception as e:
                logger.error(f"Errore ReminderChecker: {e}", exc_info=True)
            time.sleep(SLEEP_SECONDS)

    def _check_all(self):
        """Scansiona tutti gli utenti attivi e processa le loro prenotazioni."""
        users = db.get_all_active_users_for_reminders()
        for user in users:
            try:
                self._check_user(user)
            except Exception as e:
                logger.error(f"Errore check reminder user {user['telegram_id']}: {e}")

    def _check_user(self, user: dict):
        """Processa le prenotazioni di un singolo utente."""
        telegram_id = user["telegram_id"]
        auth_token = user["auth_token"]
        iyes_url = user.get("iyes_url", "") or config.WELLTEAM_IYES_URL
        company_id = user.get("company_id", 2)

        success, books = wellteam.get_my_books(
            auth_token=auth_token,
            app_token=config.WELLTEAM_APP_TOKEN,
            iyes_url=iyes_url,
            company_id=company_id,
        )

        if not success or not books:
            return

        now = datetime.now()

        for book in books:
            try:
                self._process_booking(telegram_id, book, now, user)
            except Exception as e:
                logger.error(f"Errore processando booking {book.get('IDLesson')}: {e}")

    def _process_booking(self, telegram_id: int, book: dict, now: datetime, user: dict):
        """
        Processa una singola prenotazione.
        """
        lesson_id = book.get("IDLesson")
        if not lesson_id:
            return

        start_str = book.get("StartTime", "")
        if not start_str or len(start_str) < 16:
            return

        lesson_date = start_str[:10]         # "2026-05-06"
        start_time_iso = start_str[11:16]    # "19:00"
        course_name = book.get("ServiceDescription", "Corso")
        instructor = book.get("AdditionalInfo", "")

        # Parsing data/ora lezione
        try:
            lesson_dt = datetime.strptime(f"{lesson_date} {start_time_iso}", "%Y-%m-%d %H:%M")
        except ValueError:
            logger.warning(f"User {telegram_id}: impossibile parsare data {start_str}")
            return

        # La lezione è nel passato? Salta
        if lesson_dt < now:
            return

        # Calcola minuti mancanti
        minutes_until = (lesson_dt - now).total_seconds() / 60.0

        # Crea o aggiorna il reminder nel DB
        reminder_id = db.upsert_booking_reminder(
            telegram_id, lesson_id, lesson_date,
            start_time_iso, course_name, instructor,
        )

        # Recupera lo stato corrente
        reminder = db.get_booking_reminder(telegram_id, lesson_id, lesson_date)
        if not reminder:
            return

        # ── Reminder 3h: chiedi conferma (solo se non ancora inviato) ──
        if THRESHOLD_60M < minutes_until <= THRESHOLD_3H and not reminder["reminder_3h_sent"]:
            self._send_3h_reminder(telegram_id, reminder)
            db.mark_reminder_3h_sent(reminder_id)

        # ── Messaggio 60min: se non c'è stata risposta ──
        elif minutes_until <= THRESHOLD_60M and reminder["reminder_3h_sent"] and not reminder["reminder_60m_sent"]:
            # Se l'utente non ha risposto → messaggio 60min
            if reminder["user_response"] is None:
                self._send_60m_message(telegram_id, reminder)
                db.mark_reminder_60m_sent(reminder_id)
            # Se l'utente ha risposto SÌ → butta un "buon allenamento" se non ancora fatto
            elif reminder["user_response"] == "yes":
                if not reminder["reminder_60m_sent"]:
                    self._send_good_workout(telegram_id, reminder)
                    db.mark_reminder_60m_sent(reminder_id)

    # ── Metodi di invio messaggi (thread-safe via asyncio.run_coroutine_threadsafe) ──

    def _send_message(self, telegram_id: int, text: str, reply_markup=None):
        """Invia un messaggio Telegram da thread, usando l'event loop del bot."""
        try:
            coro = self._application.bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )
            if self._app_loop and self._app_loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, self._app_loop)
            else:
                logger.warning(f"Loop non attivo, accodo messaggio per {telegram_id}")
        except Exception as e:
            logger.error(f"Impossibile inviare messaggio a {telegram_id}: {e}")

    def _edit_message(self, telegram_id: int, message_id: int, text: str, reply_markup=None):
        """Modifica un messaggio esistente."""
        try:
            coro = self._application.bot.edit_message_text(
                chat_id=telegram_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )
            if self._app_loop and self._app_loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, self._app_loop)
        except Exception as e:
            logger.error(f"Impossibile editare messaggio per {telegram_id}: {e}")

    def _send_3h_reminder(self, telegram_id: int, reminder: dict):
        """Invia il reminder 3h con pulsanti SI/NO."""
        course_name = reminder["course_name"]
        lesson_date = reminder["lesson_date"]
        start_time = reminder["start_time"]
        instructor = reminder.get("instructor", "") or ""

        text = (
            f"⏰ *PROMEMORIA — Tra meno di 3 ore!*\n\n"
            f"🏋️ *{course_name}*\n"
            f"📅 {lesson_date} alle {start_time}\n"
        )
        if instructor:
            text += f"👤 {instructor}\n"
        text += (
            f"\n*Partecipi al corso?*\n\n"
            f"`SI` → ti auguriamo buon allenamento 🏆\n"
            f"`NO` → cancelliamo la prenotazione (liberi il posto per altri)"
        )

        lesson_id = reminder["lesson_id"]
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Sì, partecipo", callback_data=f"{CALLBACK_YES}{lesson_id}"),
                InlineKeyboardButton("❌ No, cancella", callback_data=f"{CALLBACK_NO}{lesson_id}"),
            ],
        ])

        self._send_message(telegram_id, text, reply_markup=kb)
        logger.info(f"📬 Reminder 3h inviato a {telegram_id}: {course_name} ({lesson_date} {start_time})")

    def _send_60m_message(self, telegram_id: int, reminder: dict):
        """Invia messaggio <60 min: confermato, solo telefono per disdire."""
        course_name = reminder["course_name"]
        lesson_date = reminder["lesson_date"]
        start_time = reminder["start_time"]
        instructor = reminder.get("instructor", "") or ""

        text = (
            f"✅ *PRENOTAZIONE CONFERMATA!* 🏋️\n\n"
            f"🏋️ *{course_name}*\n"
            f"📅 {lesson_date} alle {start_time}\n"
        )
        if instructor:
            text += f"👤 {instructor}\n"
        text += (
            f"\nLa tua prenotazione è confermata.\n\n"
            f"⚠️ Per disdire entro i 60 minuti prima del corso, "
            f"contatta direttamente Vicenza Fitness:\n📞 {PHONE_VF}\n\n"
            f"💪 Buon allenamento!"
        )

        self._send_message(telegram_id, text)
        logger.info(f"📬 Messaggio 60min inviato a {telegram_id}: {course_name}")

    def _send_good_workout(self, telegram_id: int, reminder: dict):
        """Invia messaggio di buon allenamento (risposta SI)."""
        course_name = reminder["course_name"]
        lesson_date = reminder["lesson_date"]
        start_time = reminder["start_time"]

        text = (
            f"💪 *Buon allenamento!*\n\n"
            f"🏋️ *{course_name}*\n"
            f"📅 {lesson_date} alle {start_time}\n\n"
            f"Ti aspettiamo! 🎯"
        )

        self._send_message(telegram_id, text)
        logger.info(f"📬 Buon allenamento inviato a {telegram_id}: {course_name}")

    def _send_cancelled(self, telegram_id: int, reminder: dict):
        """Invia messaggio di prenotazione cancellata (risposta NO)."""
        course_name = reminder["course_name"]
        lesson_date = reminder["lesson_date"]
        start_time = reminder["start_time"]

        text = (
            f"🗑️ *Prenotazione cancellata*\n\n"
            f"🏋️ *{course_name}*\n"
            f"📅 {lesson_date} alle {start_time}\n\n"
            f"Grazie per aver liberato il posto! "
            f"Qualcun altro potrà partecipare al tuo posto. 🙏"
        )

        self._send_message(telegram_id, text)
        logger.info(f"📬 Cancellazione confermata per {telegram_id}: {course_name}")


# ═══════════════════════════════════════════════════════════
# CALLBACK HANDLER (SI / NO ai pulsanti del reminder)
# ═══════════════════════════════════════════════════════════

@rate_limit
async def cb_reminder_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Utente ha premuto 'Sì, partecipo'."""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    lesson_id = int(query.data.replace(CALLBACK_YES, ""))

    reminder = db.get_reminder_by_lesson_id(lesson_id, telegram_id)
    if not reminder:
        await query.edit_message_text(
            "❌ *Reminder non trovato.* Probabilmente la prenotazione non è più valida.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    db.set_reminder_response(reminder["id"], "yes")

    course_name = reminder["course_name"]
    lesson_date = reminder["lesson_date"]
    start_time = reminder["start_time"]

    await query.edit_message_text(
        f"✅ *Confermato!*\n\n"
        f"🏋️ *{course_name}*\n"
        f"📅 {lesson_date} alle {start_time}\n\n"
        f"💪 *Buon allenamento!* 🎯",
        parse_mode=ParseMode.MARKDOWN,
    )


@rate_limit
async def cb_reminder_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Utente ha premuto 'No, cancella'."""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    lesson_id = int(query.data.replace(CALLBACK_NO, ""))

    reminder = db.get_reminder_by_lesson_id(lesson_id, telegram_id)
    if not reminder:
        await query.edit_message_text(
            "❌ *Reminder non trovato.* Probabilmente la prenotazione non è più valida.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    db.set_reminder_response(reminder["id"], "no")

    # Verifica se siamo ancora nei < 60 min — in quel caso blocca
    from datetime import datetime
    lesson_date = reminder["lesson_date"]
    start_time = reminder["start_time"]
    try:
        lesson_dt = datetime.strptime(f"{lesson_date} {start_time}", "%Y-%m-%d %H:%M")
        minutes_until = (lesson_dt - datetime.now()).total_seconds() / 60.0
        if minutes_until < THRESHOLD_60M:
            await query.edit_message_text(
                f"❌ *Impossibile cancellare.*\n\n"
                f"Mancano meno di 60 minuti all'inizio del corso.\n\n"
                f"Per disdire, contatta Vicenza Fitness:\n📞 {PHONE_VF}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
    except ValueError:
        pass

    # Procedi con cancellazione API
    user = db.get_user(telegram_id)
    if not user:
        await query.edit_message_text(
            "❌ *Devi fare login* per cancellare prenotazioni.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Login", callback_data="login_start")],
            ])
        )
        return

    # Recupera dettagli per la cancellazione...
    # Devo cercare il booking dal calendario dell'utente
    success, books = wellteam.get_my_books(
        auth_token=user["auth_token"],
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
    )

    target_book = None
    for book in books:
        if book.get("IDLesson") == lesson_id:
            target_book = book
            break

    if not target_book:
        await query.edit_message_text(
            "❌ *Prenotazione non trovata su WellTeam.*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    booking_id = target_book.get("BookingID")
    start_iso = target_book.get("StartTime", "")
    end_iso = target_book.get("EndTime", "")
    course_name = reminder["course_name"]

    if not booking_id or not start_iso:
        await query.edit_message_text(
            "❌ *Dati prenotazione incompleti.*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    ok, msg = wellteam.cancel_course(
        auth_token=user["auth_token"],
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
        booking_id=booking_id,
        lesson_id=lesson_id,
        start_time=start_iso,
        end_time=end_iso,
    )

    if ok:
        db.log_booking(telegram_id, course_name, lesson_id, start_iso, "cancel", True, msg)
        await query.edit_message_text(
            f"🗑️ *Prenotazione cancellata!*\n\n"
            f"🏋️ *{course_name}*\n"
            f"📅 {reminder['lesson_date']} alle {reminder['start_time']}\n\n"
            f"Grazie per aver liberato il posto! 🙏\n"
            f"Qualcun altro potrà partecipare. 🎯",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await query.edit_message_text(
            f"❌ *Errore cancellazione:* {msg}",
            parse_mode=ParseMode.MARKDOWN,
        )


# ═══════════════════════════════════════════════════════════
# REGISTRAZIONE
# ═══════════════════════════════════════════════════════════

def register(app):
    """Registra i callback handler per i pulsanti reminder."""
    app.add_handler(CallbackQueryHandler(cb_reminder_yes, pattern=f"^{CALLBACK_YES}\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_reminder_no, pattern=f"^{CALLBACK_NO}\\d+$"))
    logger.debug("✅ Handler reminder registrati")
