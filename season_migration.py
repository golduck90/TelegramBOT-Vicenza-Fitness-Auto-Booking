"""
Season Migration — Rileva cambio stagione e migra automaticamente i service_id.

Quando WellTeam cambia stagione (es. "Prenotazioni 2025/2026" → "Prenotazioni 2026/2027"),
tutti i service_id cambiano. Questo modulo:
1. Rileva il cambio confrontando la category dell'API con quella salvata nel catalogo
2. Aggiorna gli auto_book_items con i nuovi service_id
3. Svuota e ricostruisce il catalogo
4. Notifica gli utenti se un corso non è più trovato
"""
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import db
import wellteam
import config

logger = logging.getLogger("season_migration")


def detect_season_change(api_category: str) -> bool:
    """
    Confronta la category dell'API con quella salvata nel catalogo.
    Ritorna True se la stagione è cambiata.
    """
    from course_catalog import get_saved_category
    saved = get_saved_category()
    if not saved:
        return False  # Primo avvio, nessun dato precedente
    return saved != api_category


def migrate_service_ids(schedule_items: List[Dict], api_category: str) -> Dict[str, int]:
    """
    Migra i service_id degli auto_book_items quando cambia la stagione.

    Args:
        schedule_items: lezioni dalla API schedule (con nuovi service_id)
        api_category: category della nuova stagione

    Returns:
        {"migrated": N, "not_found": M, "unchanged": K}
    """
    stats = {"migrated": 0, "not_found": 0, "unchanged": 0}

    # Costruisci mappa (description, day_of_week, start_time, instructor) → new_service_id
    service_map = {}
    for item in schedule_items:
        desc = item.get("ServiceDescription", "").strip().lower()
        start_time = item.get("StartTime", "")[11:16] if len(item.get("StartTime", "")) > 16 else item.get("StartTime", "")
        instructor = item.get("AdditionalInfo", "").strip().lower()
        date_str = item.get("DateLesson", "")[:10]
        try:
            day_of_week = datetime.strptime(date_str, "%Y-%m-%d").weekday()
        except (ValueError, IndexError):
            continue

        key = (desc, day_of_week, start_time, instructor)
        if key not in service_map:
            service_map[key] = item.get("IDServizio")

    # Migra ogni auto_book_item attivo
    items = db.get_all_auto_book_items()
    for item in items:
        item_id = item["id"]
        old_service_id = item["service_id"]
        desc = item.get("description", "").strip().lower()
        day = item["day_of_week"]
        start = item["start_time"][:5]
        instr = (item.get("instructor") or "").strip().lower()

        key = (desc, day, start, instr)
        new_service_id = service_map.get(key)

        if new_service_id is None:
            # Prova match più rilassato (solo description + day + time)
            for (d, dy, s, i), sid in service_map.items():
                if d == desc and dy == day and s == start:
                    new_service_id = sid
                    logger.info(f"Item #{item_id}: match rilassato (istruttore diverso: '{instr}' vs '{i}')")
                    break

        if new_service_id is None:
            logger.warning(f"Item #{item_id}: '{item['description']}' non trovato nella nuova stagione")
            stats["not_found"] += 1
        elif new_service_id == old_service_id:
            stats["unchanged"] += 1
        else:
            db.update_auto_book_service_id(item_id, new_service_id)
            logger.info(f"Item #{item_id}: service_id {old_service_id} → {new_service_id} ({item['description']})")
            stats["migrated"] += 1

    return stats


def run_migration_if_needed(schedule_items: List[Dict], api_category: str) -> Optional[Dict[str, int]]:
    """
    Esegue la migrazione solo se la stagione è cambiata.
    Ritorna le statistiche se la migrazione è stata eseguita, None altrimenti.
    """
    if not detect_season_change(api_category):
        return None

    logger.info(f"🔄 Cambio stagione rilevato! '{api_category}' — avvio migrazione...")

    # 1. Migra i service_id
    stats = migrate_service_ids(schedule_items, api_category)

    # 2. Svuota il catalogo (verrà ricostruito dai dati nuovi)
    from course_catalog import clear_catalog
    clear_catalog()

    logger.info(
        f"✅ Migrazione completata: "
        f"{stats['migrated']} aggiornati, "
        f"{stats['not_found']} non trovati, "
        f"{stats['unchanged']} invariati"
    )

    return stats
