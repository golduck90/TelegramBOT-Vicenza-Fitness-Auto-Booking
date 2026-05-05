"""
Handler: Autenticazione.

Login guidato: Username → Password → Successo
Dopo login → menu principale con 3 bottoni.
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
import db
import wellteam
import config

logger = logging.getLogger("bot")

STEP_USERNAME, STEP_PASSWORD = range(2)
COMPANY_ID = config.WELLTEAM_COMPANY_ID


def _menu_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])


# ── Login guidato ──────────────────────────────────────────

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvia login: chiede username."""
    user_id = update.effective_user.id
    # Se già loggato, torna al menu
    if db.get_user(user_id):
        from handlers.menu import cmd_start
        return await cmd_start(update, context)

    # Determina se arriva da callback o da comando
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query
        reply = msg.edit_message_text
    else:
        msg = update.message
        reply = msg.reply_text

    await reply(
        "🔐 *Login — Passo 1/2*\n\n"
        "Inserisci il tuo *username* WellTeam:\n"
        "Esempio: `francesco.guerrini`\n\n"
        "✏️ *Scrivilo qui sotto*\n"
        "• `/annulla` per uscire",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")],
        ])
    )
    return STEP_USERNAME


async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Riceve username, chiede password."""
    context.user_data["login_user"] = update.message.text.strip()
    await update.message.reply_text(
        "🔐 *Login — Passo 2/2*\n\n"
        "Ora inserisci la *password*:\n\n"
        "🔒 Viene cifrata e mai condivisa.\n"
        "• `/annulla` per uscire",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")],
        ])
    )
    return STEP_PASSWORD


async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Riceve password, esegue login."""
    username = context.user_data.get("login_user", "")
    password = update.message.text.strip()

    wait_msg = await update.message.reply_text("🔄 *Accesso in corso...*", parse_mode="Markdown")

    result = wellteam.authenticate(username, password, COMPANY_ID)
    if not result:
        await wait_msg.edit_text(
            "❌ *Login fallito!* Username o password errati.\n\n"
            "Riprova con `/login` o usa il menu.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Riprova login", callback_data="login_start")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
        context.user_data.clear()
        return ConversationHandler.END

    # Salva utente (con password cifrata per auto-refresh token)
    db.register_user(update.effective_user.id, username, password)
    db.update_tokens(
        update.effective_user.id,
        auth_token=result["auth_token"],
        app_token=config.WELLTEAM_APP_TOKEN,
        user_id=result.get("user_id", 0),
    )

    await wait_msg.edit_text(
        f"✅ *Login effettuato!* 👤 `{username}`\n\n"
        f"Ora puoi usare tutte le funzioni.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu principale", callback_data="menu_home")],
        ])
    )
    context.user_data.clear()
    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Annulla login."""
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "❌ *Login annullato.*",
            parse_mode="Markdown",
            reply_markup=_menu_kb()
        )
    else:
        await update.message.reply_text(
            "❌ *Login annullato.*",
            parse_mode="Markdown",
            reply_markup=_menu_kb()
        )
    return ConversationHandler.END


# ── Login diretto (comando /login) ─────────────────────────

async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvia login guidato o diretto."""
    args = context.args
    # Già loggato → menu
    if db.get_user(update.effective_user.id):
        from handlers.menu import cmd_start
        return await cmd_start(update, context)

    if not args:
        return await login_start(update, context)

    if len(args) >= 2:
        username = args[0]
        password = " ".join(args[1:])
        wait_msg = await update.message.reply_text("🔄 *Accesso in corso...*", parse_mode="Markdown")
        result = wellteam.authenticate(username, password, COMPANY_ID)
        if result:
            db.register_user(update.effective_user.id, username, password)
            db.update_tokens(
                update.effective_user.id,
                auth_token=result["auth_token"],
                app_token=config.WELLTEAM_APP_TOKEN,
                user_id=result.get("user_id", 0),
            )
            await wait_msg.edit_text(
                f"✅ *Login riuscito!*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Menu", callback_data="menu_home")],
                ])
            )
        else:
            await wait_msg.edit_text(
                "❌ *Login fallito.*",
                parse_mode="Markdown",
                reply_markup=_menu_kb()
            )
        return ConversationHandler.END

    await update.message.reply_text(
        "⚠️ Usa: `/login <username> <password>`\nOppure solo `/login` per la guida.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── Logout ─────────────────────────────────────────────────

async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Logout con conferma."""
    user_id = update.effective_user.id
    if not db.get_user(user_id):
        msg = update.effective_message
        if msg:
            await msg.reply_text(
                "❌ *Non sei loggato.*",
                parse_mode="Markdown",
                reply_markup=_menu_kb()
            )
        return

    autobook = db.get_user_auto_book_items(user_id, enabled_only=True)
    autobook_count = len(autobook)
    warning_autobook = f"\n⚠️ *Attenzione:* hai {autobook_count} iscrizione{'i' if autobook_count != 1 else ''} all'auto-booking {'che verrà' if autobook_count == 1 else 'che verranno'} cancellata{'' if autobook_count == 1 else 'e'} con il logout." if autobook_count > 0 else ""

    text = (
        "🚪 *Sei sicuro di voler uscire?*\n\n"
        "Tutti i tuoi dati verranno cancellati." +
        warning_autobook
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sì, esci", callback_data="logout_confirm")],
        [InlineKeyboardButton("🔙 No, rimani", callback_data="menu_home")],
    ])

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    elif update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def cb_logout_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Conferma logout."""
    query = update.callback_query
    await query.answer()
    db.remove_user(query.from_user.id)
    await query.edit_message_text(
        "🚪 *Dati rimossi. Alla prossima!*\n\n"
        "Per rientrare: `/login <user> <pass>`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Login", callback_data="login_start")],
        ])
    )


# ── Registrazione ──────────────────────────────────────────

def register(app):
    # Conversation per login guidato
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("login", cmd_login),
            CallbackQueryHandler(login_start, pattern="^login_start$"),
        ],
        states={
            STEP_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_username),
                CommandHandler("annulla", login_cancel),
                CallbackQueryHandler(login_cancel, pattern="^menu_home$"),
            ],
            STEP_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_password),
                CommandHandler("annulla", login_cancel),
                CallbackQueryHandler(login_cancel, pattern="^menu_home$"),
            ],
        },
        fallbacks=[CommandHandler("annulla", login_cancel)],
        per_user=True, per_chat=True, per_message=False,
        allow_reentry=True,
    )
    app.add_handler(conv)

    # Logout
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(CallbackQueryHandler(cb_logout_confirm, pattern="^logout_confirm$"))
    # Callback login_start è gestito dal Conversation sopra
    # Callback logout_start → avvia sequenza logout
    app.add_handler(CallbackQueryHandler(cmd_logout, pattern="^logout_start$"))
