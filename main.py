#!/usr/bin/env python3
"""
🏋️ Vicenza Fitness Bot — v1.4.0

Solo auto-booking. Pre-login: solo Login. Post-login: 3 bottoni.
"""
import os, sys, logging, logging.handlers
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, Defaults,
    PersistenceInput, AIORateLimiter,
)
from telegram.constants import ParseMode
import db
from scheduler import AutoBookScheduler
from schedule_cache import refresh_all_users
from persistence import SqlitePersistence

logger = logging.getLogger("bot")


def setup_logging():
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    class JsonFormatter(logging.Formatter):
        """Custom JSON formatter for structured logging."""
        def format(self, record):
            import json
            log_entry = {
                "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0]:
                log_entry["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_entry, ensure_ascii=False)

    formatter = JsonFormatter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)

    # In Docker, logging goes to stdout via StreamHandler.
    # Only add RotatingFileHandler when running outside Docker.
    if not os.environ.get('DOCKER', '') == 'true' and not os.path.exists('/app/data'):
        file_handler = logging.handlers.RotatingFileHandler(
            config.LOG_FILE, maxBytes=10*1024*1024, backupCount=3
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console)
    if not os.environ.get('DOCKER', '') == 'true' and not os.path.exists('/app/data'):
        root.addHandler(file_handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return logging.getLogger("bot")


async def error_handler(update: Update, context):
    """Global error handler. NEVER crashes the bot.
    Skill: mostra errore specifico + azione di recupero."""
    error_type = type(context.error).__name__
    error_msg = str(context.error)[:200]
    logger.error(f"Update {update.update_id if update else '?'}: [{error_type}] {error_msg}", exc_info=context.error)
    if update and update.effective_message:
        try:
            # Messaggio amichevole ma specifico
            if "Conflict" in error_msg:
                text = (
                    "⚠️ *Conflitto di connessione.* "
                    "Il bot è stato riavviato. Usa `/start` per ricominciare."
                )
            elif "NetworkError" in error_msg or "Timeout" in error_msg:
                text = (
                    "⏳ *Errore di rete.* "
                    "Riprova tra qualche secondo."
                )
            elif "RetryAfter" in error_msg:
                text = "⏳ *Troppe richieste.* Aspetta un attimo e riprova."
            else:
                text = (
                    "❌ *Ops, qualcosa è andato storto.*\n"
                    "Riprova o usa `/start`."
                )
            await update.effective_message.reply_text(text, parse_mode="Markdown")
        except Exception:
            pass


async def post_init(app):
    """Comandi per autocomplete (dado)."""
    commands = [
        BotCommand("start", "🏠 Menu principale"),
        BotCommand("login", "🔐 Accedi con WellTeam"),
        BotCommand("logout", "🚪 Esci"),
        BotCommand("qr", "🎫 QR Code ingresso"),
        BotCommand("prenota", "📅 Prenota un corso"),
        BotCommand("corsi", "📋 Lista corsi"),
        BotCommand("autobook", "🤖 Prenotazioni automatiche"),
        BotCommand("prenotazioni", "📅 Le mie prenotazioni"),
        BotCommand("help", "❓ Aiuto"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info(f"✅ Comandi registrati: {len(commands)}")


def register_all_handlers(app):
    """Ordine: menu → auth → corsi → autobook → reminders."""
    from handlers.menu import register as reg_menu
    from handlers.auth import register as reg_auth
    from handlers.corsi import register as reg_corsi
    from handlers.autobook import register as reg_autobook
    from handlers.reminders import register as reg_reminders
    from handlers.qr import register as reg_qr

    reg_menu(app)        # Menu (catch-all per callback menu_*)
    reg_auth(app)        # Login/Logout
    reg_corsi(app)       # Lista corsi, Prenota, Prenotazioni
    reg_autobook(app)    # Auto-booking
    reg_reminders(app)   # Reminder 3h / 60min
    reg_qr(app)          # QR Code (sticky UX)

    # Fallback
    async def fallback(update: Update, context):
        await update.message.reply_text(
            "❓ Non ho capito. Usa `/start` per il menu.",
            parse_mode="Markdown"
        )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))

    logger.info("✅ Tutti gli handler registrati")


def _print_banner():
    """Stampa il banner di avvio con logo ASCII, versione e funzionalità."""
    banner = r"""╔════════════════════════════════════════════════════════════════════════════════╗
║  ────────────────────────────────────────────────────────────────────────────  ║
║  __          ________ _      _   _______ ______          __  __                ║
║  \ \        / /  ____| |    | | |__   __|  ____|   /\   |  \/  |               ║
║   \ \  /\  / /| |__  | |    | |    | |  | |__     /  \  | \  / |               ║
║    \ \/  \/ / |  __| | |    | |    | |  |  __|   / /\ \ | |\/| |               ║
║     \  /\  /  | |____| |____| |____| |  | |____ / ____ \| |  | |               ║
║      \/  \/   |______|______|______|_|  |______/_/    \_\_|  |_|               ║
║  ────────────────────────────────────────────────────────────────────────────  ║
╠════════════════════════════════════════════════════════════════════════════════╣
║           _    _ _______ ____    ____   ____   ____  _  _______ _   _  _____   ║
║      /\  | |  | |__   __/ __ \  |  _ \ / __ \ / __ \| |/ /_   _| \ | |/ ____|  ║
║     /  \ | |  | |  | | | |  | | | |_) | |  | | |  | | ' /  | | |  \| | |  __   ║
║    / /\ \| |  | |  | | | |  | | |  _ <| |  | | |  | |  <   | | | . ` | | |_ |  ║
║   / ____ \ |__| |  | | | |__| | | |_) | |__| | |__| | . \ _| |_| |\  | |__| |  ║
║  /_/    \_\____/   |_|  \____/  |____/ \____/ \____/|_|\_\_____|_| \_|\_____|  ║
╠════════════════════════════════════════════════════════════════════════════════╣
║                             Outbooking Bot  v1.4.0                             ║
║                        Telegram Bot per Vicenza Fitness                        ║
╚════════════════════════════════════════════════════════════════════════════════╝"""
    print(banner, flush=True)


def main():
    _print_banner()
    logger = setup_logging()
    logger.info("🚀 Avvio bot...")

    # Init database (crea tabelle se necessario)
    db.init_db()
    logger.info(f"✅ Database: {config.DB_PATH}")
    logger.info(f"👤 Utenti attivi: {db.count_active_users()}")

    # Crea app Telegram
    persistence = SqlitePersistence(
        store_data=PersistenceInput(
            user_data=True,
            chat_data=True,
            bot_data=False,
            callback_data=True,
        ),
    )
    builder = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN)
    builder.defaults(Defaults(parse_mode=ParseMode.MARKDOWN))
    builder.post_init(post_init)
    builder.concurrent_updates(True)
    builder.persistence(persistence)
    builder.rate_limiter(AIORateLimiter(
        overall_max_rate=30,
        overall_time_period=1,
        group_max_rate=20,
        group_time_period=1,
        max_retries=5,
    ))
    app = builder.build()

    # Error handler globale
    app.add_error_handler(error_handler)

    # Registra handler
    register_all_handlers(app)

    # Scheduler auto-booking (ogni notte 00:10 Roma + retry ogni ora)
    scheduler = AutoBookScheduler(application=app)
    scheduler.start()

    # Reminder checker (ogni ora a :05 e :35)
    from handlers.reminders import ReminderChecker
    reminder_checker = ReminderChecker(app)
    reminder_checker.start()

    # Cache notturna all'avvio (thread separato)
    import threading
    threading.Thread(target=refresh_all_users, daemon=True).start()
    logger.info("🌙 Cache calendario avviata in background")

    # Avvia bot
    webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()
    if webhook_url:
        port = int(os.environ.get("TELEGRAM_WEBHOOK_PORT", "8443"))
        app.run_webhook(listen="0.0.0.0", port=port,
                        url_path=config.TELEGRAM_BOT_TOKEN,
                        webhook_url=f"{webhook_url}/{config.TELEGRAM_BOT_TOKEN}")
    else:
        logger.info("🔄 Avvio in modalità POLLING")
        try:
            app.run_polling(allowed_updates=["message", "callback_query"])
        except KeyboardInterrupt:
            pass
        finally:
            scheduler.stop()
            logger.info("👋 Bot fermato")


if __name__ == "__main__":
    main()
