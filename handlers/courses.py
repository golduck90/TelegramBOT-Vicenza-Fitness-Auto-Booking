"""
Handler: Corsi (/corsi) — Carica e mostra corsi disponibili.
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

SERVICE_ID_MAP = {}


@rate_limit
@require_auth
async def cmd_courses(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """/corsi — Elenco corsi disponibili."""
    await update.message.reply_text("🔄 *Caricamento corsi...*", parse_mode="Markdown")

    success, data = wellteam.get_services(
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
            "📭 *Nessun corso disponibile.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])
        )
        return

    db.save_courses(update.effective_user.id, data)

    # Popola mappa globale
    global SERVICE_ID_MAP
    SERVICE_ID_MAP.clear()
    for c in data:
        SERVICE_ID_MAP[c["Description"].lower()] = c["Id"]

    # Raggruppa per categoria
    cats = {}
    for c in data:
        cat = c.get("Category", "Altri")
        cats.setdefault(cat, []).append(c["Description"])

    msg = "*📋 Corsi disponibili:*\n\n"
    for cat, courses in cats.items():
        msg += f"▫️ *{cat}*\n"
        for corso in courses:
            msg += f"  • `{corso}`\n"
        msg += "\n"

    msg += "💡 Per prenotare: `/book Nome Corso`"

    await update.message.reply_text(
        msg[:4000],
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Prenota subito", callback_data="menu_book")],
            [InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")],
        ])
    )


@rate_limit
@require_auth
async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """/calendario — Corsi dei prossimi giorni."""
    await update.message.reply_text("🔄 *Caricamento calendario...*", parse_mode="Markdown")

    now = datetime.now()
    start = now.strftime("%Y-%m-%d")
    end = (now + timedelta(days=3)).strftime("%Y-%m-%d")

    success, items = wellteam.get_schedule(
        user["auth_token"], user.get("app_token", ""), user.get("iyes_url", ""),
        start_date=start, end_date=end,
    )

    if not success or not items:
        await update.message.reply_text(
            "📭 *Nessun corso nei prossimi giorni.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])
        )
        return

    days = {}
    for item in items:
        day = item.get("DateLesson", "")[:10]
        days.setdefault(day, []).append(item)

    msg = "*📅 Calendario corsi:*\n\n"
    day_names = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    for day in sorted(days.keys())[:4]:
        dt = datetime.strptime(day, "%Y-%m-%d")
        msg += f"▫️ *{day_names[dt.weekday()]} {day[-5:]}*\n"
        for item in days[day]:
            st = item.get("StartTime", "")[11:16]
            et = item.get("EndTime", "")[11:16]
            places = item.get("AvailablePlaces", 0)
            desc = item.get("ServiceDescription", "?")
            instr = item.get("AdditionalInfo", "")
            booked = "✅" if item.get("IsUserPresent") else ""
            pstr = f"{'🔴' if places == 0 else '🟢'}{places}"
            msg += f"  {booked} {st}-{et} | `{desc}` | {instr} | {pstr}\n"
        msg += "\n"

    await update.message.reply_text(
        msg[:4000],
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])
    )


def register(app):
    app.add_handler(CommandHandler("corsi", cmd_courses))
    app.add_handler(CommandHandler(["calendario", "corsi_disponibili"], cmd_schedule))
