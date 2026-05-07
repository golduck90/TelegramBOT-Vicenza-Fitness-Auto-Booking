"""
Schedule Refresh — Scarica la schedule WellTeam per aggiornare solo il catalogo.

Niente più cache DB: il catalogo JSON è l'unica fonte della verità per la struttura.
I dati live (posti, is_mine) vengono fetchati direttamente dall'API su richiesta.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
from zoneinfo import ZoneInfo
import wellteam
import config

logger = logging.getLogger("schedule_cache")

ROME_TZ = ZoneInfo("Europe/Rome")


def refresh_all_users() -> int:
    """Scansiona tutti gli utenti attivi e aggiorna il loro catalogo."""
    import db as db_module
    conn = db_module.get_connection()
    rows = conn.execute("""
        SELECT telegram_id, auth_token, COALESCE(iyes_url, '') as iyes_url
        FROM users
        WHERE is_active = 1 AND auth_token IS NOT NULL
    """).fetchall()

    updated = 0
    for row in rows:
        try:
            success = refresh_schedule(
                row["telegram_id"],
                row["auth_token"],
                row["iyes_url"] or config.WELLTEAM_IYES_URL,
            )
            if success:
                updated += 1
        except Exception as e:
            logger.error(f"Refresh fallito per user {row['telegram_id']}: {e}")

    logger.info(f"🌙 Refresh catalogo: {updated}/{len(rows)} utenti aggiornati")
    return updated


def refresh_schedule(telegram_id: int, auth_token: str,
                     iyes_url: str = "") -> bool:
    """
    Scarica la schedule WellTeam per i prossimi 14 giorni
    e aggiorna il course_catalog (aggiunge nuovi corsi, non rimuove mai).
    """
    today = datetime.now(ROME_TZ)
    end_date = today + timedelta(days=14)

    start_str = today.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    success, items = wellteam.get_schedule(
        auth_token=auth_token,
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=iyes_url,
        start_date=start_str,
        end_date=end_str,
    )

    if not success or not items:
        logger.debug(f"User {telegram_id}: nessun item nella schedule")
        return False

    from course_catalog import update_from_schedule
    update_from_schedule(items)

    logger.info(f"📚 User {telegram_id}: catalogo aggiornato con {len(items)} items dalla schedule")
    return True
