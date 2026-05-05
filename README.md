# 🏋️ Vicenza Fitness Bot

Bot Telegram per la gestione delle prenotazioni dei corsi presso **Vicenza Fitness** (piattaforma WellTeam).

## ✨ Funzionalità

- 🔐 **Login guidato** con credenziali WellTeam (password cifrata localmente)
- 📋 **Lista corsi** con calendario settimanale
- 📅 **Prenotazione singola** di un corso
- 🤖 **Auto-booking ricorrente** — prenota automaticamente lo stesso corso ogni settimana
- 🗑️ **Cancellazione** prenotazioni
- ⏰ **Reminder 3 ore prima** — ti chiede conferma con pulsanti SI/NO
- 🚫 **Blocco cancellazione** se mancano meno di 60 minuti
- 📞 **Avviso telefono** se non rispondi al reminder entro 60 minuti
- 📊 **Statistiche** utenti e prenotazioni
- 🔄 **Refresh automatico token** — se il token scade, il bot si riloggia automaticamente

## 🖼️ Comandi

| Comando | Descrizione |
|---------|-------------|
| `/start` | 🏠 Menu principale |
| `/login` | 🔐 Accedi con WellTeam |
| `/logout` | 🚪 Esci |
| `/prenota` | 📅 Prenota un corso |
| `/corsi` | 📋 Lista corsi |
| `/prenotazioni` | 📅 Le mie prenotazioni |
| `/autobook` | 🤖 Gestisci auto-booking |
| `/help` | ❓ Aiuto |

## 🚀 Installazione

### Prerequisiti

- Python 3.10+
- Token Telegram Bot (da [@BotFather](https://t.me/BotFather))
- AppToken WellTeam (dall'app WellTeam della palestra)

### Setup

```bash
# 1. Clona il repository
git clone https://github.com/tuo-utente/vicenza-fitness-bot.git
cd vicenza-fitness-bot

# 2. Crea ambiente virtuale
python3 -m venv venv
source venv/bin/activate

# 3. Installa dipendenze
pip install -r requirements.txt

# 4. Configura variabili d'ambiente
cp .env.example .env
nano .env  # Inserisci TELEGRAM_BOT_TOKEN e WELLTEAM_APP_TOKEN

# 5. Avvia il bot
python3 main.py
```

### Docker

```bash
# 1. Crea un file .env con i token
cp .env.example .env
nano .env   # Inserisci TELEGRAM_BOT_TOKEN e WELLTEAM_APP_TOKEN

# 2. Build e avvia con docker compose
docker compose up --build -d

# 3. Log in tempo reale
docker compose logs -f
```

### Docker manuale

```bash
docker build -t vicenza-fitness-bot .
docker run -d \
  --name vicenza-fitness-bot \
  --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN="il_tuo_token" \
  -e WELLTEAM_APP_TOKEN="il_tuo_app_token" \
  -e DATA_DIR=/app/data \
  -v vicenza_data:/app/data \
  --cap-drop=ALL \
  --cap-add=CHOWN \
  --memory=256M \
  --cpus=0.5 \
  vicenza-fitness-bot
```

## 🔧 Configurazione

Tutta la configurazione avviene tramite **variabili d'ambiente** (vedi `.env.example`):

| Variabile | Obbligatoria | Descrizione |
|-----------|:-----------:|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token del bot Telegram |
| `WELLTEAM_APP_TOKEN` | ✅ | AppToken WellTeam (company-level) |
| `WELLTEAM_IYES_URL` | ❌ | URL server WellTeam (default: `http://185.103.80.254:65432/`) |
| `FERNET_KEY` | ❌ | Chiave per crittografia password (auto-generata) |
| `LOG_LEVEL` | ❌ | Livello di log (default: `INFO`) |
| `ADMIN_IDS` | ❌ | ID Telegram admin (separati da virgola) |

## 🏗️ Architettura

```
vicenza-fitness-bot/
├── main.py                 # Entry point
├── config.py               # Configurazione (da env)
├── db.py                   # Database SQLite
├── wellteam.py             # API WellTeam
├── scheduler.py            # Auto-booking notturno
├── schedule_cache.py       # Cache calendario
├── handlers/
│   ├── menu.py             # Menu principale + Info
│   ├── auth.py             # Login/Logout
│   ├── corsi.py            # Lista corsi + Prenotazione + Cancellazione
│   ├── autobook.py         # Gestione auto-booking
│   ├── reminders.py        # Reminder 3h / 60min
│   ├── decorators.py       # Decoratori (auth, rate limit)
│   ├── ratelimit.py        # Rate limiter
│   └── qr.py               # QR Code ingresso
├── .env.example            # Esempio configurazione
└── requirements.txt        # Dipendenze Python
```

## 🧠 Come funziona

### Flusso di prenotazione
1. L'utente fa login con le credenziali WellTeam
2. Sceglie un corso dal calendario
3. Seleziona "Prenota una volta" o "Auto-booking settimanale"
4. Il bot chiama l'API WellTeam e conferma

### Auto-booking
- Viene eseguito ogni notte alle **00:10** (ora Roma)
- Controlla tutti gli item attivi e prenota la prossima occorrenza
- Se il token è scaduto, fa **re-login automatico** con la password cifrata
- Evita duplicati (controlla se già prenotato)

### Reminder pre-corso
- **3 ore prima**: messaggio con pulsanti "Sì, partecipo / No, cancella"
- **60 minuti prima** (se nessuna risposta): prenotazione confermata, disdetta solo via telefono
- **< 60 minuti**: impossibile cancellare dal bot (blocco automatico)

## 🛡️ Sicurezza

- Le password WellTeam sono **cifrate con Fernet** (AES-128-CBC)
- La chiave Fernet è salvata su file con permessi `600`
- I token di accesso sono gestiti in memoria e DB cifrato
- L'AppToken WellTeam va passato come variabile d'ambiente, **mai hardcodato**
- Rate limiting sulle richieste Telegram (`30 msg/s`, `20 msg/gruppo`)

## 📝 Note per altri gestori di palestre

Questo bot funziona con l'API **WellTeam** utilizzata da molte palestre italiane.
Per adattarlo alla tua palestra:

1. Ottieni l'**AppToken** dall'app WellTeam della tua palestra
2. Verifica l'**URL del server** (`IYESUrl`) — potrebbe essere diverso
3. Controlla se il `companyID` è diverso da `2`
4. Alcuni corsi speciali (Gravity, Vacu Gym) potrebbero non essere prenotabili via API

## ⚖️ Licenza

MIT — Libero di usare, modificare e distribuire.

---

*Realizzato con ❤️ per Vicenza Fitness*
