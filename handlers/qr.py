"""
Handler: QR Code ingresso — UX "sticky"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Il QR code rimane visibile come messaggio separato mentre
l'utente naviga i pulsanti sottostanti.

Pattern:
  1. Utente preme "🎫 QR Code"
  2. Bot invia QR photo (messaggio separato — STICKY)
  3. Bot risponde con bottoni sotto (Rigenera / Menu)
  4. QR resta in alto quando si torna al menu
"""
import logging, subprocess, os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import db, wellteam
from handlers.decorators import require_auth, rate_limit

logger = logging.getLogger("bot")

# Costante: quanto vale il QR in secondi (default 5 minuti)
QR_TTL_SECONDS = 300


def back_home() -> InlineKeyboardMarkup:
    """Pulsante singolo per tornare al menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Menu principale", callback_data="qr_torna_menu")],
    ])


def qr_actions() -> InlineKeyboardMarkup:
    """Bottoni sotto al QR: rigenera + torna al menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Rigenera QR", callback_data="qr_rigenera")],
        [InlineKeyboardButton("🔙 Menu principale", callback_data="qr_torna_menu")],
    ])


@rate_limit
@require_auth
async def cmd_qr(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """/qr — Genera e mostra QR code ingresso (sticky)."""
    await _generate_and_send_qr(update, context, user)


async def cb_qr_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: pulsante QR dal menu principale."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = db.get_user(user_id)
    if not user:
        await query.edit_message_text("❌ Devi fare login prima.", reply_markup=back_home())
        return
    await _generate_and_send_qr(update, context, user)


async def cb_rigenera(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rigenera il QR (cancella il vecchio e invia nuovo)."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = db.get_user(user_id)
    if not user:
        await query.edit_message_text("❌ Devi fare login prima.", reply_markup=back_home())
        return

    # Se c'è un QR precedente, prova a cancellarlo
    old_qr_msg_id = context.user_data.get("qr_msg_id")
    if old_qr_msg_id:
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=old_qr_msg_id)
        except Exception:
            pass  # Se già cancellato, nessun problema

    await _generate_and_send_qr(update, context, user)


async def cb_torna_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Torna al menu — il QR photo resta visibile più in alto."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user = db.get_user(user_id)

    if not user:
        await query.edit_message_text(
            "🏋️ *Vicenza Fitness Bot*\n\nEffettua il login per iniziare.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Login", callback_data="login_start")],
            ])
        )
        return

    stats = db.get_bot_stats()
    total_bookings = stats['autobook_success'] + stats['book_success']
    text = (
        f"🏋️ *Vicenza Fitness Bot*\n\n"
        f"👤 *{user['username']}*\n\n"
        f"📊 *Statistiche:*\n"
        f"👥 Utenti: {stats['active_users']}\n"
        f"✅ Corsi prenotati: {total_bookings}\n\n"
        f"Cosa vuoi fare?"
    )

    # Il QR (se presente) è un messaggio separato più in alto —
    # editiamo SOLO il messaggio del menu, il QR rimane
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Lista Corsi", callback_data="menu_corsi"),
             InlineKeyboardButton("📅 Prenota", callback_data="menu_prenota")],
            [InlineKeyboardButton("🎫 QR Code", callback_data="qr_genera"),
             InlineKeyboardButton("🤖 Auto-Booking", callback_data="menu_autobook")],
            [InlineKeyboardButton("ℹ️ Info", callback_data="menu_info"),
             InlineKeyboardButton("🚪 Logout", callback_data="logout_start")],
        ])
    )


async def _generate_and_send_qr(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """Core: genera QR e lo invia come messaggio separato sticky."""
    qr_path = f"/tmp/qr_{update.effective_user.id}.png"

    # 1. Ottieni stringa QR dall'API
    success, qr_string = wellteam.get_qr_code(
        user["auth_token"],
        user.get("app_token", ""),
        user.get("iyes_url", ""),
    )
    if not success:
        await update.effective_message.reply_text(
            f"❌ *Errore QR:* {qr_string}",
            parse_mode="Markdown",
            reply_markup=back_home(),
        )
        return

    # 2. Genera immagine QR con qrencode
    try:
        subprocess.run(
            ["qrencode", "-o", qr_path, "-s", "10", "-l", "M", qr_string],
            check=True, capture_output=True, timeout=10,
        )
    except Exception as e:
        logger.error(f"qrencode: {e}")
        await update.effective_message.reply_text(
            f"❌ *Errore nella generazione del QR.*\nCodice: `{qr_string}`",
            parse_mode="Markdown",
            reply_markup=back_home(),
        )
        return

    # 3. Invia QR come FOTO (messaggio separato — sticky)
    now = datetime.now().strftime("%H:%M")
    caption = (
        f"📱 *QR Code ingresso* 🏋️\n"
        f"⏱️ Generato alle *{now}* — valido circa 5 minuti\n"
        f"Mostralo al tornello per entrare!"
    )

    try:
        with open(qr_path, "rb") as f:
            qr_msg = await update.effective_message.reply_photo(
                photo=f,
                caption=caption,
                parse_mode="Markdown",
                # Nessun reply_markup qui — i bottoni sono nel messaggio SOTTO
            )
    except Exception as e:
        logger.error(f"send_photo: {e}")
        await update.effective_message.reply_text(
            "❌ *Errore nell'invio del QR.* Riprova.",
            parse_mode="Markdown",
            reply_markup=back_home(),
        )
        return

    # Salva message_id del QR per future cancellazioni
    context.user_data["qr_msg_id"] = qr_msg.message_id

    # 4. Messaggio interattivo SOTTO il QR con le azioni
    await update.effective_message.reply_text(
        "👇 *Cosa vuoi fare?*",
        parse_mode="Markdown",
        reply_markup=qr_actions(),
    )

    # 5. Opzionale: pulisci file temporaneo
    try:
        os.remove(qr_path)
    except Exception:
        pass


# ─── Registrazione ───────────────────────────────────

def register(app):
    app.add_handler(CommandHandler("qr", cmd_qr))
    app.add_handler(CallbackQueryHandler(cb_qr_button, pattern="^qr_genera$"))
    app.add_handler(CallbackQueryHandler(cb_rigenera, pattern="^qr_rigenera$"))
    app.add_handler(CallbackQueryHandler(cb_torna_menu, pattern="^qr_torna_menu$"))
    logger.info("🎫 QR handler registrato (sticky UX)")
