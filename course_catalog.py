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


def update_from_schedule(items: List[Dict], category: str = ""):
    """
    Aggiorna il catalogo con i corsi provenienti dalla schedule API.
    Per ogni giorno futuro presente nei dati API, cancella le entries esistenti
    e le sostituisce con i dati freschi. Per il giorno corrente (oggi), esegue
    un merge: i corsi già iniziati (non più nell'API) vengono mantenuti.
    I giorni non presenti nei dati API (oltre la finestra VisibleDays)
    vengono lasciati intatti.

    items: lista di lesson object dall'API WellTeam (via get_schedule).
    category: category della stagione corrente (es. "Prenotazioni 2026/2027").
    """
    data = _load()
    now = datetime.now()

    # Aggiorna metadata stagione
    if "_meta" not in data:
        data["_meta"] = {}
    if category:
        data["_meta"]["category"] = category
    data["_meta"]["last_updated"] = now.strftime("%Y-%m-%d %H:%M:%S")

    # 1. Raccogli i giorni presenti nei dati API
    days_in_api = set()
    for item in items:
        date_str = item.get("DateLesson", "")[:10]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d") if date_str else now
            days_in_api.add(str(dt.weekday()))
        except ValueError:
            pass

    # 2. Per ogni giorno presente nei dati API, cancella le entries esistenti
    #    MA per oggi fai merge (non cancellare corsi già iniziati)
    today_weekday = now.weekday()
    for day_key in days_in_api:
        if day_key not in data:
            data[day_key] = {}
        if int(day_key) == today_weekday:
            pass  # OGGI: merge — passo 3 sovrascrive chi matcha, aggiunge chi manca
        else:
            data[day_key] = {}  # FUTURI: clear + replace

    # 3. Inserisci dati freschi
    for item in items:
        date_str = item.get("DateLesson", "")[:10]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d") if date_str else now
            day_of_week = dt.weekday()
        except ValueError:
            day_of_week = now.weekday()

        start_time = item.get("StartTime", "")[11:16] if len(item.get("StartTime", "")) > 16 else item.get("StartTime", "")
        description = item.get("ServiceDescription", "").strip()
        instructor = item.get("AdditionalInfo", "").strip()
        course_key = (
            description.lower(),
            day_of_week,
            start_time,
            instructor.lower(),
        )
        course_key_str = ":".join(str(k) for k in course_key)

        day_key = str(day_of_week)
        if day_key not in data:
            data[day_key] = {}

        existing_entry = data.get(day_key, {}).get(course_key_str, {})
        data[day_key][course_key_str] = {
            "service_id": item.get("IDServizio"),
            "description": description,
            "day_of_week": day_of_week,
            "day_name": DAY_NAMES[day_of_week] if day_of_week < 7 else "?",
            "start_time": start_time,
            "end_time": item.get("EndTime", "")[11:16] if len(item.get("EndTime", "")) > 16 else item.get("EndTime", ""),
            "instructor": instructor,
            "category": item.get("CategoryDescription", ""),
            "first_seen": existing_entry.get("first_seen", now.strftime("%Y-%m-%d")),
            "last_seen_api": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

    _save(data)
    total = sum(len(v) for k, v in data.items() if k != "_meta")
    logger.info(f"📚 Catalogo corsi: {total} corsi ({len(days_in_api)} giorni aggiornati)")


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


def get_courses_by_slot(description: str, day_of_week: int, start_time: str) -> List[Dict]:
    """Cerca nel catalogo tutte le entry che matchano (description, day, time)
    indipendentemente dall'istruttore. Usata per rilevare cambio istruttore."""
    data = _load()
    day_key = str(day_of_week)
    if day_key not in data:
        return []
    results = []
    desc_lower = description.strip().lower()
    for key_str, course in data[day_key].items():
        if (course.get("description", "").strip().lower() == desc_lower
                and course.get("start_time") == start_time):
            results.append(course)
    return results


def get_all_days_with_courses() -> Dict[int, int]:
    """Restituisce {day_of_week: count} per tutti i giorni che hanno corsi."""
    data = _load()
    result = {}
    for day_key, courses in data.items():
        if day_key == "_meta":
            continue
        try:
            result[int(day_key)] = len(courses)
        except (ValueError, TypeError):
            continue
    return result


def get_course_count() -> int:
    """Restituisce il numero totale di corsi unici nel catalogo."""
    data = _load()
    return sum(len(v) for k, v in data.items() if k != "_meta")


def get_saved_category() -> str:
    """Restituisce la category salvata nel catalogo (es. 'Prenotazioni 2026/2027')."""
    data = _load()
    return data.get("_meta", {}).get("category", "")


def clear_catalog():
    """Svuota completamente il catalogo (usato al cambio stagione)."""
    _save({})
    logger.info("🗑️ Catalogo svuotato")


def remove_legacy_keys() -> int:
    """
    Rimuove le entries con formato chiave legacy (service_id:day:time:instructor).
    Il formato legacy inizia con un numero (service_id), quello nuovo inizia con testo (description).
    """
    data = _load()
    removed = 0
    for day_key in list(data.keys()):
        if day_key == "_meta":
            continue
        courses = data.get(day_key, {})
        legacy = [k for k in courses if k.split(":")[0].isdigit()]
        for k in legacy:
            del courses[k]
            removed += 1
    if removed:
        _save(data)
        logger.info(f"🗑️ Rimosse {removed} entries legacy dal catalogo")
    return removed


def cleanup_stale_entries(max_age_days: int = 28) -> list:
    """
    Rimuove corsi non visti nell'API per max_age_days giorni.
    Restituisce lista di (description, day_of_week, start_time, instructor) rimossi.
    """
    data = _load()
    cutoff = datetime.now() - timedelta(days=max_age_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    removed = []

    for day_key in list(data.keys()):
        if day_key == "_meta":
            continue
        courses = data.get(day_key, {})
        to_remove = []
        for key_str, course in courses.items():
            last_seen = course.get("last_seen_api") or course.get("first_seen", "")
            if last_seen and last_seen < cutoff_str:
                to_remove.append(key_str)
                removed.append((
                    course.get("description", ""),
                    int(day_key),
                    course.get("start_time", ""),
                    course.get("instructor", ""),
                ))
        for k in to_remove:
            del courses[k]

    if removed:
        _save(data)
        logger.info(f"🗑️ Cleanup: rimossi {len(removed)} corsi stale (>{max_age_days}gg)")
    return removed


def find_service_id_by_description(description: str, day_of_week: int,
                                    start_time: str, instructor: str = "") -> Optional[int]:
    """
    Cerca il service_id nel catalogo per description + day + time + instructor.
    Usato per migrare auto_book_items al cambio stagione.
    """
    data = _load()
    day_key = str(day_of_week)
    if day_key not in data:
        return None

    for key_str, course in data[day_key].items():
        if (course.get("description", "").strip().lower() == description.strip().lower()
                and course.get("start_time") == start_time
                and (not instructor or instructor.lower() in course.get("instructor", "").lower())):
            return course.get("service_id")
    return None


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
