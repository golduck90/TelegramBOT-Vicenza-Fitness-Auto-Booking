"""
Handler: Prenotazioni (/book, /cancel, /prenotazioni)
Supporta sia comandi testuali sia callback dal menu.
"""
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler
import wellteam
import db
from handlers.decorators import require_auth, rate_limit

logger = logging.getLogger("bot")


def _get_service_id(name: str) -> int:
    key = name.strip().lower()
    try:
        from handlers.courses import SERVICE_ID_MAP
        if key in SERVICE_ID_MAP:
            return SERVICE_ID_MAP[key]
    except Exception:
        pass
    return 0


@rate_limit
@require_auth
async def cmd_prenotazioni(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """/prenotazioni — Le mie prenotazioni (alias per il menu)."""
    await update.message.reply_text("🔄 *Caricamento prenotazioni...*", parse_mode="Markdown")

    success, data = wellteam.get_my_books(
        user["auth_token"], user.get("app_token", ""), user.get("iyes_url", "")
    )

    if not success:
        await update.message.reply_text(
            f"❌ *Errore:* {data}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])
        )
        return

    if not data:
        await update.message.reply_text(
            "📭 *Nessuna prenotazione attiva.*\nUsa `/corsi` per vedere cosa prenotare.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Vedi corsi", callback_data="menu_corsi")],
                [InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")],
            ])
        )
        return

    msg = "*📅 Le tue prenotazioni:*\n\n"
    keyboard = []
    for b in data:
        start = b.get("StartTime", "")
        end = b.get("EndTime", "")
        desc = b.get("ServiceDescription", "?")
        instr = b.get("AdditionalInfo", "")

        try:
            dt = datetime.fromisoformat(start)
            day_names = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
            day_name = day_names[dt.weekday()]
            date_str = f"{day_name} {dt.day:02d}/{dt.month:02d}"
        except Exception:
            date_str = start[:10]

        msg += f"▫️ *{desc}* — {date_str}\n"
        msg += f"  🕐 {start[11:16]}-{end[11:16]} | 👤 {instr}\n\n"

        bid = b.get("BookingID", 0)
        lid = b.get("IDLesson", 0)
        cancel_data = f"cancel_{bid}_{lid}_{start}_{end}"
        keyboard.append([InlineKeyboardButton(f"❌ Cancella {desc} {start[11:16]}", callback_data=cancel_data)])

    keyboard.append([InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")])

    await update.message.reply_text(msg[:4000], parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@rate_limit
@require_auth
async def cmd_book(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """/book <nome corso> — Prenota un corso."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "✅ *Prenota un corso*\n\n"
            "Usa: `/book <nome corso>`\n"
            "*Esempi:*\n"
            "`/book Pilates`\n"
            "`/book All. Funzionale`\n"
            "`/book Group Cycling`\n\n"
            "Vedi tutti i corsi con `/corsi`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])
        )
        return

    course_name = " ".join(args)
    target_time = None
    if len(args) >= 2 and ":" in args[-1]:
        course_name = " ".join(args[:-1])
        target_time = args[-1]

    service_id = _get_service_id(course_name)
    if not service_id:
        await update.message.reply_text(
            f"❌ *Corso non trovato:* `{course_name}`\nUsa `/corsi` per la lista.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])
        )
        return

    now = datetime.now()
    start_date = now.strftime("%Y-%m-%d")
    end_date = (now + timedelta(days=3)).strftime("%Y-%m-%d")

    await update.message.reply_text(f"🔄 *Cerco `{course_name}`...*", parse_mode="Markdown")

    success, items = wellteam.get_schedule(
        user["auth_token"], user.get("app_token", ""), user.get("iyes_url", ""),
        start_date=start_date, end_date=end_date,
    )

    if not success or not items:
        await update.message.reply_text(
            f"📭 *Nessuna lezione disponibile.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])
        )
        return

    matching = [i for i in items if i.get("IDServizio") == service_id]
    if target_time:
        matching = [i for i in matching if target_time in i.get("StartTime", "")]

    if not matching:
        await update.message.reply_text(
            f"📭 *Nessuna lezione di `{course_name}` disponibile nei prossimi giorni.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])
        )
        return

    # Cerca primo con posti liberi
    lesson = None
    for m in sorted(matching, key=lambda x: x.get("DateLesson", "")):
        if m.get("AvailablePlaces", 0) > 0 and not m.get("IsUserPresent"):
            lesson = m
            break

    if not lesson:
        msg = f"❌ *`{course_name}` — nessun posto libero*\n\n"
        for m in matching[:5]:
            st = m.get("StartTime", "")[11:16]
            day = m.get("DateLesson", "")[:10]
            pl = m.get("AvailablePlaces", 0)
            status = "✅ Già prenotato" if m.get("IsUserPresent") else f"{'🔴' if pl == 0 else '🟢'} {pl} posti"
            msg += f"  • {day} {st} — {status}\n"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]]))
        return

    # Prenota!
    date = lesson["DateLesson"][:10]
    start_time = f"{date}T{lesson['StartTime'][11:19]}"
    end_time = f"{date}T{lesson['EndTime'][11:19]}"

    ok, resp = wellteam.book_course(
        user["auth_token"], user.get("app_token", ""), user.get("iyes_url", ""),
        lesson_id=lesson["IDLesson"], service_id=service_id,
        start_time=start_time, end_time=end_time,
    )

    db.log_booking(update.effective_user.id, lesson.get("ServiceDescription", course_name),
                   lesson["IDLesson"], start_time, "book", success=ok, message=resp)

    if ok:
        await update.message.reply_text(
            f"✅ *Prenotato!* 🎉\n\n"
            f"🏋️ *{lesson.get('ServiceDescription', course_name)}*\n"
            f"📅 {date}\n"
            f"🕐 {start_time[11:16]} - {end_time[11:16]}\n"
            f"👤 {lesson.get('AdditionalInfo', '?')}\n\n"
            f"_{resp}_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Le mie prenotazioni", callback_data="menu_prenotazioni")],
                [InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")],
            ])
        )
    else:
        await update.message.reply_text(
            f"❌ *Prenotazione fallita:* {resp}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])
        )


def register(app):
    app.add_handler(CommandHandler(["prenotazioni", "miei"], cmd_prenotazioni))
    app.add_handler(CommandHandler("book", cmd_book))
