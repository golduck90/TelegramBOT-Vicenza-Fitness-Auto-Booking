"""
Course Catalog — Catalogo locale dei corsi salvato su file JSON.

Costruito incrementalmente: ogni volta che il bot scarica la schedule
dal server, aggiunge i corsi trovati al catalogo locale.
Il catalogo contiene solo la struttura del corso (giorno, ora, istruttore,
descrizione, categoria) SENZA dati live (posti disponibili, prenotazioni).

Questo permette di:
- Vedere TUTTI i giorni della settimana, anche oltre la finestra VisibleDays
- Impostare auto-booking per corsi non ancora prenotabili
- Sapere quali corsi esistono senza dover chiamare il server ogni volta
"""
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import config

logger = logging.getLogger("catalog")

# Path del file catalogo (nella stessa directory del DB)
CATALOG_FILE = config.DATA_DIR / "course_catalog.json"

# Giorni della settimana in italiano
DAY_NAMES = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _load() -> Dict:
    """Carica il catalogo dal file JSON. Restituisce dict vuoto se non esiste."""
    if not CATALOG_FILE.exists():
        return {}
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Errore lettura catalogo: {e}")
        return {}


def _save(data: Dict):
    """Salva il catalogo su file JSON."""
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.debug(f"📝 Catalogo salvato: {len(data)} giorni")


def update_from_schedule(items: List[Dict]):
    """
    Aggiorna il catalogo con i corsi provenienti dalla schedule API.
    items: lista di lesson object dall'API WellTeam (via get_schedule).
    """
    data = _load()
    now = datetime.now()

    for item in items:
        # Estrai il giorno della settimana (0=Lun ... 6=Dom)
        date_str = item.get("DateLesson", "")[:10]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d") if date_str else now
            day_of_week = dt.weekday()
        except ValueError:
            day_of_week = now.weekday()

        # Crea una chiave univoca per il corso
        start_time = item.get("StartTime", "")[11:16] if len(item.get("StartTime", "")) > 16 else item.get("StartTime", "")
        course_key = (
            item.get("IDServizio"),
            day_of_week,
            start_time,
            item.get("AdditionalInfo", ""),
        )
        course_key_str = ":".join(str(k) for k in course_key)

        day_key = str(day_of_week)
        if day_key not in data:
            data[day_key] = {}

        if course_key_str not in data[day_key]:
            data[day_key][course_key_str] = {
                "service_id": item.get("IDServizio"),
                "description": item.get("ServiceDescription", ""),
                "day_of_week": day_of_week,
                "day_name": DAY_NAMES[day_of_week] if day_of_week < 7 else "?",
                "start_time": start_time,
                "end_time": item.get("EndTime", "")[11:16] if len(item.get("EndTime", "")) > 16 else item.get("EndTime", ""),
                "instructor": item.get("AdditionalInfo", ""),
                "category": item.get("CategoryDescription", ""),
                "first_seen": data[day_key].get(course_key_str, {}).get("first_seen", datetime.now().strftime("%Y-%m-%d")),
            }

    _save(data)
    total = sum(len(v) for v in data.values())
    logger.info(f"📚 Catalogo corsi: {len(data)} giorni, {total} corsi")


def get_day_courses(day_of_week: int) -> List[Dict]:
    """Restituisce tutti i corsi conosciuti per un dato giorno (0=Lun ... 6=Dom)."""
    data = _load()
    day_key = str(day_of_week)
    if day_key not in data:
        return []
    return sorted(
        list(data[day_key].values()),
        key=lambda c: c.get("start_time", "")
    )


def get_all_days_with_courses() -> Dict[int, int]:
    """Restituisce {day_of_week: count} per tutti i giorni che hanno corsi."""
    data = _load()
    result = {}
    for day_key, courses in data.items():
        result[int(day_key)] = len(courses)
    return result


def get_course_count() -> int:
    """Restituisce il numero totale di corsi unici nel catalogo."""
    data = _load()
    return sum(len(v) for v in data.values())


def next_date_for_weekday(day_of_week: int) -> str:
    """
    Calcola la prossima data (YYYY-MM-DD) per un dato giorno della settimana.

    Args:
        day_of_week: 0=Lunedì ... 6=Domenica

    Returns:
        Stringa data in formato YYYY-MM-DD.
        Se day_of_week è oggi, restituisce oggi.
        Se day_of_week è un giorno passato questa settimana,
        restituisce la stessa data della prossima settimana.
    """
    today = datetime.now()
    now_wd = today.weekday()
    offset = (day_of_week - now_wd) % 7
    target = today + timedelta(days=offset)
    return target.strftime("%Y-%m-%d")
