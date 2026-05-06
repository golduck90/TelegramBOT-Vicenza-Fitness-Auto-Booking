"""
Handler: Auto-Booking — Gestione iscrizioni.

🤖 Prenotazioni Automatiche → elenco, stato, cancellazione.
Esecuzione ogni notte alle 00:10 (ora Roma).
"""
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import db
from handlers.decorators import require_auth, rate_limit

logger = logging.getLogger("bot")

DAY_NAMES = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


@rate_limit
@require_auth
async def cmd_autobook(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """🤖 Gestione prenotazioni automatiche."""
    telegram_id = update.effective_user.id
    items = db.get_user_auto_book_items(telegram_id)

    if not items:
        msg = (
            "🤖 *Prenotazioni Automatiche*\n\n"
            "Non hai ancora attivato nessuna prenotazione automatica.\n\n"
            "Cosa fa? Selezioni un corso 📅 e lo iscrivi all'auto-booking.\n"
            "Il bot lo prenoterà per te ogni settimana, appena disponibile!\n\n"
            "👇 *Inizia ora!*"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Scegli un corso", callback_data="menu_prenota")],
            [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
        ])
    else:
        msg = f"🤖 *Prenotazioni Automatiche ({len(items)})*\n\n"
        buttons = []
        for it in items:
            day_name = DAY_NAMES[it["day_of_week"]] if it["day_of_week"] < 7 else "?"
            status = "✅ Attivo" if it["is_active"] else "⏸️ In pausa"
            instr = f" — {it['instructor']}" if it.get("instructor") else ""

            # Statistiche
            stats = await _compute_stats(telegram_id, it)
            ultima = stats["last"]
            volte = stats["count"]
            da_quando = stats["since"]

            msg += (
                f"*{it['description']}*{instr}\n"
                f"📅 {day_name} {it['start_time'][:5]} | {status}\n"
                f"📊 Prenotato {volte} volte | {da_quando}\n"
            )
            if ultima:
                msg += f"✅ Ultima: {ultima}\n"

            # Bottoni gestione
            if it["is_active"]:
                buttons.append([InlineKeyboardButton(f"⏸️ Pausa #{it['id']} — {it['description']}", callback_data=f"ab_toggle_{it['id']}")])
            else:
                buttons.append([InlineKeyboardButton(f"✅ Riattiva #{it['id']} — {it['description']}", callback_data=f"ab_toggle_{it['id']}")])
            buttons.append([InlineKeyboardButton(f"🗑️ Rimuovi #{it['id']}", callback_data=f"ab_remove_{it['id']}")])
            msg += "\n"

        buttons.append([InlineKeyboardButton("📅 Aggiungi corso", callback_data="menu_prenota")])
        buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="menu_home")])

        kb = InlineKeyboardMarkup(buttons)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg[:4000], parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(msg[:4000], parse_mode="Markdown", reply_markup=kb)


async def _compute_stats(telegram_id: int, item: dict) -> dict:
    """Calcola statistiche per un auto-book item."""
    # Da quando è attivo
    created = item.get("created_at", "")
    since = "da poco"
    if created:
        try:
            created_dt = datetime.strptime(created[:10], "%Y-%m-%d")
            days = (datetime.now() - created_dt).days
            if days < 1:
                since = "da oggi"
            elif days == 1:
                since = "da ieri"
            elif days < 30:
                since = f"da {days} giorni"
            else:
                months = days // 30
                since = f"da {months} mese" if months == 1 else f"da {months} mesi"
        except:
            pass

    # Quante volte ha prenotato (dal booking_log)
    conn = db.get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM booking_log WHERE telegram_id = ? AND action = 'autobook' AND success = 1 AND service_desc = ?",
        (telegram_id, item["description"])
    ).fetchone()
    count = row["cnt"] if row else 0

    # Ultima prenotazione
    last = item.get("last_booked_date", "")
    if last:
        try:
            dt = datetime.strptime(last, "%Y-%m-%d")
            last = dt.strftime("%d/%m/%Y")
        except:
            pass

    return {"count": count, "last": last, "since": since}


async def cb_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attiva/disattiva auto-book item."""
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.split("_")[-1])
    new_state = db.toggle_auto_book_item(item_id, query.from_user.id)

    if new_state is True:
        await query.edit_message_text(
            "✅ *Riattivato!* Tornerò a prenotare questo corso.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Auto-Booking", callback_data="menu_autobook")],
            ])
        )
    elif new_state is False:
        await query.edit_message_text(
            "⏸️ *In pausa.* Non prenoterò questo corso finché non lo riattivi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Auto-Booking", callback_data="menu_autobook")],
            ])
        )
    else:
        await query.edit_message_text(
            "❌ *Non trovato.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Auto-Booking", callback_data="menu_autobook")],
            ])
        )


async def cb_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rimuove auto-book item."""
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.split("_")[-1])
    ok = db.remove_auto_book_item(item_id, query.from_user.id)

    if ok:
        await query.edit_message_text(
            "🗑️ *Rimosso!* Non prenoterò più questo corso.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Auto-Booking", callback_data="menu_autobook")],
            ])
        )
    else:
        await query.edit_message_text(
            "❌ *Non trovato.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Auto-Booking", callback_data="menu_autobook")],
            ])
        )


def register(app):
    app.add_handler(CallbackQueryHandler(cmd_autobook, pattern="^menu_autobook$"))
    app.add_handler(CallbackQueryHandler(cb_toggle, pattern=r"^ab_toggle_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_remove, pattern=r"^ab_remove_\d+$"))

    # Comando /autobook
    app.add_handler(CommandHandler("autobook", cmd_autobook))

    logger.info("🤖 Handler auto-booking registrato")
