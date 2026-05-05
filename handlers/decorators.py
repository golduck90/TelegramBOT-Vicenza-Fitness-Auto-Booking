"""
Decoratori di utilità per i comandi.
"""
import functools
import logging
from telegram import Update
from telegram.ext import ContextTypes
from handlers.ratelimit import check_rate_limit, remaining_quota
from db import get_user, is_locked

logger = logging.getLogger("bot")


def require_auth(func):
    """Decoratore: richiede che l'utente sia loggato."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user = get_user(user_id)
        if not user:
            msg = update.effective_message
            if msg:
                await msg.reply_text(
                    "❌ *Non sei loggato!*\n\n"
                    "Usa `/login` per accedere.",
                    parse_mode="Markdown"
                )
            return
        return await func(update, context, user)
    return wrapper


def rate_limit(func):
    """Decoratore: applica rate limiting.
    Supporta sia comandi diretti che callback query."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not check_rate_limit(user_id):
            quota = remaining_quota(user_id)
            msg = update.effective_message
            if msg:
                await msg.reply_text(
                    f"⏳ *Troppe richieste!* Riposa un attimo.\n"
                    f"Richiami rimasti: {quota}",
                    parse_mode="Markdown"
                )
            return
        return await func(update, context)
    return wrapper


def check_lock(func):
    """Decoratore: controlla se l'utente è bloccato (troppi login falliti).
    Supporta sia comandi diretti che callback query."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if is_locked(user_id):
            msg = update.effective_message
            if msg:
                await msg.reply_text(
                    "🔒 *Account temporaneamente bloccato*\n"
                    "Troppi tentativi di login falliti. Riprova tra 15 minuti.",
                    parse_mode="Markdown"
                )
            return
        return await func(update, context)
    return wrapper
