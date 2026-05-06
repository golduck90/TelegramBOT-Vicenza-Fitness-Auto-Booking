"""
Handler: Menu principale — Nuova UI essenziale.

PRE-LOGIN:  solo 🔐 Login
POST-LOGIN: 📋 Corsi | 📅 Prenota | 🤖 Auto-Booking | ℹ️ Info
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import db

logger = logging.getLogger("bot")


# ═══════════════════════════════════════════════════════════
# MENU PRINCIPALE
# ═══════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🏠 Menu principale — cambia in base allo stato login."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)

    if not user:
        # PRE-LOGIN: solo bottone Login
        text = (
            "🏋️ *Benvenuto su Vicenza Fitness Bot!*\n\n"
            "Per utilizzare il bot, accedi con le tue credenziali WellTeam.\n\n"
            "👇 *Premi Login per iniziare*"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Login", callback_data="login_start")],
        ])
    else:
        # POST-LOGIN: statistiche + bottoni
        stats = db.get_bot_stats()
        total_bookings = stats['autobook_success'] + stats['book_success']
        text = (
            f"🏋️ *Vicenza Fitness Bot*\n\n"
            f"👤 *{user['username']}*\n\n"
            f"📊 *Statistiche bot:*\n"
            f"👥 Utenti: {stats['active_users']}\n"
            f"🤖 Iscrizioni auto-booking: {stats['active_autobook_items']}\n"
            f"✅ Corsi prenotati dal bot: {total_bookings}\n"
            f"📚 Corsi disponibili: {stats['courses_in_cache']}\n\n"
            f"Cosa vuoi fare?"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Prenota", callback_data="menu_prenota")],
            [InlineKeyboardButton("🎫 QR Code", callback_data="qr_genera"),
             InlineKeyboardButton("🤖 Auto-Booking", callback_data="menu_autobook")],
            [InlineKeyboardButton("ℹ️ Info", callback_data="menu_info"),
             InlineKeyboardButton("🚪 Logout", callback_data="logout_start")],
        ])

    # Se arriva da callback, edita — sennò rispondi
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def cb_menu_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: torna al menu principale."""
    # Reinserisce update come se fosse un /start
    update.callback_query = update.callback_query
    await cmd_start(update, context)


# ═══════════════════════════════════════════════════════════
# INFO BOT
# ═══════════════════════════════════════════════════════════

async def cb_menu_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ℹ️ Info sul bot — statistiche dettagliate."""
    query = update.callback_query
    await query.answer()

    stats = db.get_bot_stats()
    total_bookings = stats['autobook_success'] + stats['book_success']

    text = (
        "ℹ️ *Informazioni sul Bot*\n\n"
        "🏋️ *Vicenza Fitness Bot* automatizza le tue prenotazioni "
        "presso Vicenza Fitness (WellTeam).\n\n"
        f"📊 *Statistiche:*\n"
        f"👥 Utenti attivi: {stats['active_users']}\n"
        f"🤖 Iscrizioni auto-booking: {stats['active_autobook_items']}\n"
        f"✅ Prenotazioni totali: {total_bookings}\n"
        f"  • Manuali: {stats['book_success']}\n"
        f"  • Automatiche: {stats['autobook_success']}\n"
        f"📚 Corsi disponibili in cache: {stats['courses_in_cache']}\n\n"
        "🕐 *Reminder:* ricevi un promemoria 3h prima del corso.\n"
        "🌙 *Auto-booking:* prenotazione automatica ogni notte alle 00:10."
    )

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
        ])
    )


# ═══════════════════════════════════════════════════════════
# GESTIONE CORSISTI (aggiornamento cache)
# ═══════════════════════════════════════════════════════════

async def cb_force_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forza il refresh del calendario."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔄 *Aggiorno calendario...*",
        parse_mode="Markdown"
    )
    from schedule_cache import refresh_schedule
    import config

    user = db.get_user(query.from_user.id)
    if not user or not user.get("auth_token"):
        await query.edit_message_text(
            "❌ *Devi prima fare login!*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Login", callback_data="login_start")],
            ])
        )
        return

    success = refresh_schedule(
        query.from_user.id,
        user["auth_token"],
        user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
    )

    if success:
        await query.edit_message_text(
            "✅ *Calendario aggiornato!*\n\nOra puoi navigare i corsi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Scegli un corso", callback_data="menu_prenota")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
    else:
        await query.edit_message_text(
            "❌ *Errore aggiornamento.* Riprova più tardi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Riprova", callback_data="force_refresh")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )


# ═══════════════════════════════════════════════════════════
# HELP (minimale)
# ═══════════════════════════════════════════════════════════

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help rapido."""
    await update.message.reply_text(
        "🤖 *Comandi disponibili:*\n\n"
        "`/start` — 🏠 Menu principale\n"
        "`/login` — 🔐 Accedi\n"
        "`/logout` — 🚪 Esci\n\n"
        "Dopo il login avrai accesso a tutte le funzioni.",
        parse_mode="Markdown"
    )


# ═══════════════════════════════════════════════════════════
# REGISTRAZIONE
# ═══════════════════════════════════════════════════════════

def register(app):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))

    # Callback router
    app.add_handler(CallbackQueryHandler(cmd_start, pattern="^menu_home$"))
    app.add_handler(CallbackQueryHandler(cb_menu_info, pattern="^menu_info$"))
    app.add_handler(CallbackQueryHandler(cb_force_refresh, pattern="^force_refresh$"))

    logger.info("🏠 Menu registrato (pre/post login)")
