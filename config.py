"""
Bot Palestra — Configurazione
================================
Carica tutto da variabili d'ambiente con fallback safe.
Non hardcodare MAI token sensibili qui dentro.
"""
import os
from pathlib import Path

# ── Percorsi ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR
DB_PATH = DATA_DIR / "palestra.db"
FERNET_KEY_FILE = DATA_DIR / ".fernet_key"

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN non impostato. Mettilo in .env o exportalo.")

# ── WellTeam API (token di default) ──────────────────────
# AppToken: token company-level di Vicenza Fitness (uguale per tutti)
# AuthToken: personale, ottenuto dopo login
WELLTEAM_APP_TOKEN = os.environ.get("WELLTEAM_APP_TOKEN")
if not WELLTEAM_APP_TOKEN:
    raise RuntimeError(
        "❌ WELLTEAM_APP_TOKEN non impostato. "
        "È il token company-level di Vicenza Fitness. "
        "Ottienilo dall'app WellTeam o da un backup."
    )
WELLTEAM_AUTH_TOKEN = os.environ.get("WELLTEAM_AUTH_TOKEN", "")
WELLTEAM_IYES_URL = os.environ.get("WELLTEAM_IYES_URL", "http://185.103.80.254:65432/")
WELLTEAM_BASE_URL = "https://inforyouwebgw.teamsystem.com/api/v1"
WELLTEAM_COMPANY_ID = 2

# ── Fernet key (crittografia password) ───────────────────
# Se non esiste, viene generata al primo avvio e salvata su file
_AUTO_GENERATED_KEY = None


def get_fernet_key() -> bytes:
    """Restituisce la chiave Fernet, generandola se necessario."""
    global _AUTO_GENERATED_KEY

    # 1) Variabile d'ambiente (priorità max)
    env_key = os.environ.get("FERNET_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key

    # 2) File .fernet_key
    if FERNET_KEY_FILE.exists():
        return FERNET_KEY_FILE.read_bytes()

    # 3) Genera e salva
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    FERNET_KEY_FILE.write_bytes(key)
    FERNET_KEY_FILE.chmod(0o600)  # Solo il proprietario legge
    _AUTO_GENERATED_KEY = key
    return key


# ── Bot settings ──────────────────────────────────────────
BOT_USERNAME = os.environ.get("BOT_USERNAME", "VicenzaFitnessBot")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
RATE_LIMIT_PER_MINUTE = 10  # Max comandi al minuto per utente
MAX_LOGIN_ATTEMPTS = 5      # Tentativi di login falliti prima del ban temporaneo
LOGIN_COOLDOWN_MINUTES = 15

# ── Scheduler ─────────────────────────────────────────────
AUTOBOOK_CHECK_INTERVAL_MINUTES = int(os.environ.get("AUTOBOOK_CHECK_INTERVAL", "30"))

# ── Logging ───────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "bot.log"
