"""
Cache notturna del calendario WellTeam.

Ogni notte (cron 2:00 AM) scarica per ogni utente attivo la schedule
delle prossime 2 settimane e la salva in `schedule_cache`.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import db
import wellteam
import config

logger = logging.getLogger("schedule_cache")

WEEKDAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def refresh_all_users() -> int:
    """
    Scansiona tutti gli utenti attivi, scarica e cache la schedule.
    Restituisce il numero di utenti aggiornati.
    """
    conn = db._get_conn()
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
            logger.error(f"Cache notturna fallita per user {row['telegram_id']}: {e}")

    logger.info(f"🌙 Cache notturna: {updated}/{len(rows)} utenti aggiornati")
    return updated


def refresh_schedule(telegram_id: int, auth_token: str,
                     iyes_url: str = "") -> bool:
    """
    Scarica la schedule per un utente per le prossime 2 settimane.
    Salva nella cache divise per settimana.
    """
    today = datetime.now()
    # Prossimi 14 giorni
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
        logger.warning(f"User {telegram_id}: nessun item nella schedule")
        return False

    # Raggruppa per settimana
    weeks: Dict[str, list] = {}
    now = datetime.now()
    for item in items:
        date_str = item.get("DateLesson", "")[:10]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            # week_key = "2026-W19"
            iso = dt.isocalendar()
            week_key = f"{iso[0]}-W{iso[1]:02d}"
        except (ValueError, TypeError):
            week_key = now.strftime("%Y-W%W")

        # Aggiunge day_of_week
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d") if date_str else now
            item["DayOfWeek"] = dt.weekday()
        except ValueError:
            item["DayOfWeek"] = now.weekday()

        if week_key not in weeks:
            weeks[week_key] = []
        weeks[week_key].append(item)

    # Salva ogni settimana
    for week_key, wk_items in weeks.items():
        # Deduplica: stesso corso+orario+istruttore+giorno = un solo record
        seen = set()
        deduped = []
        for item in wk_items:
            key = (
                item.get("IDServizio"),
                item.get("DayOfWeek"),
                item.get("StartTime", "")[11:16] if len(item.get("StartTime", "")) > 16 else item.get("StartTime", ""),
                item.get("AdditionalInfo", ""),
            )
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        db.save_schedule_cache(telegram_id, deduped, week_key)

    logger.info(f"📅 User {telegram_id}: {sum(len(v) for v in weeks.values())} corsi cached in {len(weeks)} settimane")

    # Aggiorna il catalogo locale dei corsi (per visualizzazione offline)
    try:
        from course_catalog import update_from_schedule
        update_from_schedule(items)
    except Exception as e:
        logger.warning(f"Errore aggiornamento catalogo corsi: {e}")

    return True
