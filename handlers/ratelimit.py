"""
Rate limiter — semplice sliding window per utente.
Thread-safe via threading.Lock.
"""
import time
import threading
from collections import defaultdict
from config import RATE_LIMIT_PER_MINUTE

_user_timestamps: dict = defaultdict(list)
_lock = threading.Lock()


def check_rate_limit(user_id: int) -> bool:
    """
    Verifica se l'utente ha superato il limite di richieste al minuto.
    Restituisce True se può procedere, False se è rate-limited.
    """
    now = time.time()
    window = 60.0  # 1 minuto

    with _lock:
        # Pulisci timestamp scaduti
        _user_timestamps[user_id] = [
            ts for ts in _user_timestamps[user_id]
            if now - ts < window
        ]

        if len(_user_timestamps[user_id]) >= RATE_LIMIT_PER_MINUTE:
            return False

        _user_timestamps[user_id].append(now)
        return True


def remaining_quota(user_id: int) -> int:
    """Quanti comandi può ancora fare l'utente in questo minuto."""
    now = time.time()
    window = 60.0
    with _lock:
        valid = [ts for ts in _user_timestamps[user_id] if now - ts < window]
        return max(0, RATE_LIMIT_PER_MINUTE - len(valid))
