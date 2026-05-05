"""
Handler: QR Code e stato utente (/qr, /stato, /storico)
"""
import logging, subprocess
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler
import db, wellteam
from handlers.decorators import require_auth, rate_limit

logger = logging.getLogger("bot")


def back_home():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu principale", callback_data="menu_home")]])


@rate_limit
@require_auth
async def cmd_qr(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """/qr — QR code ingresso."""
    await update.message.reply_text("🔄 *Genero QR code...*", parse_mode="Markdown")

    success, qr_string = wellteam.get_qr_code(user["auth_token"], user.get("app_token", ""), user.get("iyes_url", ""))
    if not success:
        await update.message.reply_text(f"❌ *Errore QR:* {qr_string}", parse_mode="Markdown", reply_markup=back_home())
        return

    qr_path = f"/tmp/qr_{update.effective_user.id}.png"
    try:
        subprocess.run(["qrencode", "-o", qr_path, "-s", "10", "-l", "M", qr_string],
                       check=True, capture_output=True, timeout=10)
    except Exception as e:
        logger.error(f"qrencode: {e}")
        await update.message.reply_text(f"❌ *Errore QR.* Codice: `{qr_string}`", parse_mode="Markdown", reply_markup=back_home())
        return

    await update.message.reply_photo(
        photo=open(qr_path, "rb"),
        caption="📱 *QR Code valido*\nMostralo al tornello per entrare 🏋️",
        parse_mode="Markdown",
        reply_markup=back_home()
    )


@rate_limit
@require_auth
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """/stato — Abbonamento e certificato."""
    await update.message.reply_text("🔄 *Carico stato...*", parse_mode="Markdown")

    success, data = wellteam.get_my_status(user["auth_token"], user.get("app_token", ""), user.get("iyes_url", ""))
    if not success:
        await update.message.reply_text(f"❌ *Errore:* {data}", parse_mode="Markdown", reply_markup=back_home())
        return

    item = data.get("Item", data)
    if isinstance(item, dict):
        quota = item.get("FreeQuotaDescription", "N/D")
        medical = item.get("MedicalCertificateExpiration", "N/D")
        try:
            if medical and medical != "N/D":
                med_dt = datetime.fromisoformat(medical.replace("Z", ""))
                medical = med_dt.strftime("%d/%m/%Y")
        except:
            pass

        await update.message.reply_text(
            f"*📊 Stato utente:*\n\n"
            f"👤 `{user['username']}`\n"
            f"📦 *Quota:* {quota}\n"
            f"🏥 *Certificato medico:* {medical}\n"
            f"🔗 Vicenza Fitness 🏋️",
            parse_mode="Markdown", reply_markup=back_home()
        )
    else:
        await update.message.reply_text(f"*📊 Stato:* `{str(data)[:1000]}`", parse_mode="Markdown", reply_markup=back_home())


@rate_limit
@require_auth
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """/storico — Cronologia prenotazioni."""
    logs = db.get_booking_history(update.effective_user.id, limit=15)
    if not logs:
        await update.message.reply_text("📭 *Nessuna attività.*", parse_mode="Markdown", reply_markup=back_home())
        return

    msg = "*📜 Cronologia recente:*\n\n"
    for log in logs[:15]:
        icon = "✅" if log["action"] == "book" else "❌" if log["action"] == "cancel" else "🤖"
        ok = "✅" if log["success"] else "❌"
        t = log.get("created_at", "")[:16].replace("T", " ")
        desc = log.get("service_desc", "?") or "?"
        msg += f"{icon} {ok} {t} — *{desc}*\n"

    await update.message.reply_text(msg[:4000], parse_mode="Markdown", reply_markup=back_home())


def register(app):
    app.add_handler(CommandHandler("qr", cmd_qr))
    app.add_handler(CommandHandler(["stato", "status"], cmd_status))
    app.add_handler(CommandHandler(["storico", "history"], cmd_history))
