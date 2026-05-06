"""
WellTeam API Client — thread-safe con refresh automatico dei token.
"""
import requests
import logging
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
import config

logger = logging.getLogger("wellteam")

# Sessioni requests separate per thread (connessioni riutilizzabili)
_session = None


def _get_session() -> requests.Session:
    """Restituisce una session requests thread-safe."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": "okhttp/4.10.0",
            "Accept-Encoding": "gzip",
            "Accept-Language": "it",
        })
    return _session


# ═══════════════════════════════════════════════════════════
# AUTENTICAZIONE
# ═══════════════════════════════════════════════════════════

def authenticate(username: str, password: str, company_id: int = None) -> Optional[Dict[str, Any]]:
    """
    Esegue il login su WellTeam.
    Restituisce dict con auth_token, app_token, user_id oppure None.
    """
    if company_id is None:
        company_id = config.WELLTEAM_COMPANY_ID

    sess = _get_session()
    try:
        # Login: IYESUrl + AppToken headers sono RICHIESTI (bug server .NET)
        headers = {
            "Accept": "application/json",
            "Accept-Language": "it",
            "IYESUrl": config.WELLTEAM_IYES_URL,
            "AppToken": config.WELLTEAM_APP_TOKEN,
            "Content-Type": "application/json; charset=UTF-8",
        }
        if config.WELLTEAM_APP_TOKEN:
            headers["AppToken"] = config.WELLTEAM_APP_TOKEN

        r = sess.get(
            f"{config.WELLTEAM_BASE_URL}/security/authenticate",
            params={"login": username, "password": password, "companyid": company_id},
            headers=headers,
            timeout=15,
        )

        if r.status_code != 200:
            logger.warning(f"Login fallito per {username}: HTTP {r.status_code} {r.text[:200]}")
            return None

        data = r.json()
        if not data.get("Successful") or not data.get("Item"):
            err = data.get("ErrorMessage") or data.get("Comment") or "Errore sconosciuto"
            logger.warning(f"Login fallito per {username}: {err}")
            return None

        auth_token = data["Item"]

        # 2) Ottieni l'utente (per AppToken e user_id) — VALIDA il token
        r2 = sess.get(
            f"{config.WELLTEAM_BASE_URL}/webuser/me",
            headers={
                "AuthToken": auth_token,
                "IYESUrl": config.WELLTEAM_IYES_URL,
            },
            timeout=15,
        )

        if r2.status_code != 200:
            logger.warning(f"Login valido ma token non funziona per {username}: HTTP {r2.status_code}")
            return None

        me_data = r2.json()
        if not me_data.get("Successful") or not me_data.get("Item"):
            logger.warning(f"Token non valido per {username}: {me_data.get('ErrorMessage', 'risposta vuota')}")
            return None

        user_info = me_data["Item"]
        user_id = user_info.get("Id", 0)
        # L'AppToken di solito è lo stesso AuthToken per l'app
        app_token = auth_token

        return {
            "auth_token": auth_token,
            "app_token": app_token or auth_token,
            "user_id": user_id,
            "username": username,
        }

    except requests.RequestException as e:
        logger.error(f"Errore di rete durante login per {username}: {e}")
        return None
    except (ValueError, KeyError) as e:
        logger.error(f"Errore parsing risposta login per {username}: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# API WRAPPER (usa i token dell'utente)
# ═══════════════════════════════════════════════════════════

def _headers(auth_token: str, app_token: str = "", iyes_url: str = "") -> Dict:
    """Headers standard per le chiamate API.
    
    IMPORTANTE: L'AppToken di sistema (quello hardcoded dell'app) va SEMPRE
    incluso in ogni chiamata API, non solo in login. Non va confuso con
    l'AuthToken personale dell'utente.
    """
    h = {
        "AuthToken": auth_token,
        "AppToken": config.WELLTEAM_APP_TOKEN,
        "IYESUrl": iyes_url or config.WELLTEAM_IYES_URL,
        "Content-Type": "application/json; charset=UTF-8",
    }
    return h


def get_my_books(auth_token: str, app_token: str = "", iyes_url: str = "",
                 company_id: int = 2) -> Tuple[bool, Any]:
    """Elenco prenotazioni attive."""
    sess = _get_session()
    try:
        r = sess.get(
            f"{config.WELLTEAM_BASE_URL}/webbooking/mybooks",
            headers=_headers(auth_token, app_token, iyes_url),
            params={"companyID": company_id, "Type": ""},
            timeout=15,
        )
        data = r.json()
        if data.get("Successful"):
            return True, data.get("Items", [])
        return False, data.get("ErrorMessage", "Errore sconosciuto")
    except Exception as e:
        logger.error(f"get_my_books: {e}")
        return False, str(e)


def get_services(auth_token: str, app_token: str = "", iyes_url: str = "",
                 company_id: int = 2) -> Tuple[bool, Any]:
    """Elenco servizi/corsi disponibili."""
    sess = _get_session()
    try:
        r = sess.get(
            f"{config.WELLTEAM_BASE_URL}/webbooking/services",
            headers=_headers(auth_token, app_token, iyes_url),
            params={"companyID": company_id},
            timeout=15,
        )
        data = r.json()
        if data.get("Successful") and data.get("Items"):
            # Appiattisce la struttura nidificata
            flat = []
            for cat in data["Items"]:
                cat_name = cat.get("Description", "")
                for tip in cat.get("Tipologies", []):
                    flat.append({
                        "Id": tip["Id"],
                        "Type": tip.get("Type", 0),
                        "Description": tip["Description"],
                        "Category": cat_name,
                    })
            return True, flat
        return False, data.get("ErrorMessage", "Nessun corso trovato")
    except Exception as e:
        logger.error(f"get_services: {e}")
        return False, str(e)


def get_schedule(auth_token: str, app_token: str = "", iyes_url: str = "",
                 company_id: int = 2, start_date: str = None, end_date: str = None) -> Tuple[bool, Any]:
    """Calendario corsi (listwithmine)."""
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    if not end_date:
        end_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")

    sess = _get_session()
    body = {
        "CompanyID": company_id,
        "Types": [],
        "StartDate": f"{start_date}T00:00:00",
        "EndDate": f"{end_date}T23:30:00",
        "TimeStart": f"{start_date}T06:00:00",
        "TimeEnd": f"{end_date}T23:30:00",
    }
    try:
        r = sess.post(
            f"{config.WELLTEAM_BASE_URL}/webbooking/listwithmine",
            headers=_headers(auth_token, app_token, iyes_url),
            json=body,
            timeout=15,
        )
        data = r.json()
        if data.get("Successful"):
            return True, data.get("Items", [])
        return False, data.get("ErrorMessage", "Errore sconosciuto")
    except Exception as e:
        logger.error(f"get_schedule: {e}")
        return False, str(e)


def book_course(auth_token: str, app_token: str, iyes_url: str,
                lesson_id: int, service_id: int, start_time: str, end_time: str,
                book_nr: int = 1, note: str = "") -> Tuple[bool, str]:
    """Prenota un corso."""
    sess = _get_session()
    body = {
        "BookNr": book_nr,
        "BookingID": service_id,
        "IDDurata": 0,
        "EndTime": end_time,
        "IDLesson": lesson_id,
        "Note": note,
        "StartTime": start_time,
        "Type": 0,
    }
    try:
        r = sess.post(
            f"{config.WELLTEAM_BASE_URL}/webbooking/book",
            headers=_headers(auth_token, app_token, iyes_url),
            json=body,
            timeout=15,
        )
        data = r.json()
        if data.get("Successful"):
            return True, data.get("Comment", "Prenotato!")
        return False, data.get("ErrorMessage") or data.get("Comment", "Errore")
    except Exception as e:
        logger.error(f"book_course: {e}")
        return False, str(e)


def cancel_course(auth_token: str, app_token: str, iyes_url: str,
                  booking_id: int, lesson_id: int, start_time: str, end_time: str) -> Tuple[bool, str]:
    """Cancella una prenotazione."""
    sess = _get_session()
    body = {
        "BookingID": booking_id,
        "IDDurata": 0,
        "EndTime": end_time,
        "IDLesson": lesson_id,
        "StartTime": start_time,
        "Type": 0,
    }
    try:
        r = sess.post(
            f"{config.WELLTEAM_BASE_URL}/webbooking/cancel",
            headers=_headers(auth_token, app_token, iyes_url),
            json=body,
            timeout=15,
        )
        data = r.json()
        if data.get("Successful"):
            return True, data.get("Comment", "Cancellato!")
        return False, data.get("ErrorMessage") or data.get("Comment", "Errore")
    except Exception as e:
        logger.error(f"cancel_course: {e}")
        return False, str(e)


def get_qr_code(auth_token: str, app_token: str = "", iyes_url: str = "") -> Tuple[bool, str]:
    """Ottiene il codice QR per l'ingresso."""
    sess = _get_session()
    try:
        r = sess.get(
            f"{config.WELLTEAM_BASE_URL}/user/GetAccessCode",
            headers=_headers(auth_token, app_token, iyes_url),
            timeout=15,
        )
        data = r.json()
        if data.get("Successful") and data.get("Item"):
            return True, data["Item"]
        return False, data.get("ErrorMessage", "Errore")
    except Exception as e:
        logger.error(f"get_qr_code: {e}")
        return False, str(e)


def get_my_status(auth_token: str, app_token: str = "", iyes_url: str = "") -> Tuple[bool, Any]:
    """Stato utente (abbonamento, certificato medico)."""
    sess = _get_session()
    try:
        r = sess.get(
            f"{config.WELLTEAM_BASE_URL}/user/mystatus",
            headers=_headers(auth_token, app_token, iyes_url),
            timeout=15,
        )
        data = r.json()
        if data.get("Successful"):
            return True, data
        return False, data.get("ErrorMessage", "Errore")
    except Exception as e:
        logger.error(f"get_my_status: {e}")
        return False, str(e)


def find_lesson(items: List[Dict], service_id: int, instructor: str = None,
                target_time: str = None) -> Optional[Dict]:
    """
    Cerca una lezione specifica nella lista.
    service_id: ID del corso
    instructor: nome istruttore (case-insensitive, parziale)
    target_time: orario in formato HH:MM (es. "19:00")
    """
    if not items:
        return None
    for item in items:
        if item.get("IDServizio") != service_id:
            continue
        if instructor and instructor.lower() not in item.get("AdditionalInfo", "").lower():
            continue
        if target_time:
            item_time = item.get("StartTime", "")
            if not item_time.endswith(f"{target_time}:00"):
                continue
        return item
    return None
