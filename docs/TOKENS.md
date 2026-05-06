# 🗝️ WellTeam APPTOKEN — Vicenza Fitness

> ⚠️ **ATTENZIONE**: Questo file è un riferimento, non contiene token reali.
> I token vanno inseriti nel file `.env` locale (vedi `.env.example`).

Questo file documenta come ottenere il **company-level APPTOKEN** necessario
per autenticarsi all'API WellTeam di Vicenza Fitness.

## Come ottenere il token

1. Decomprimi l'APK ufficiale WellTeam: `apktool d WellTeam.apk`
2. Cerca in `res/values/strings.xml` la stringa `app_token` o `AppToken`
3. Oppure cerca nel codice decompilato (jadx) la costante `APP_TOKEN`

## Come usarlo

```bash
cp .env.example .env
# Inserisci i token reali in .env
```

Variabili richieste in `.env`:

| Variabile | Descrizione |
|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Token del bot Telegram (da @BotFather) |
| `WELLTEAM_APP_TOKEN` | Company-level token WellTeam (da APK decompilato) |

## Note

- Il token è salvato solo nel `.env` locale (`.gitignore` lo esclude)
- Non committare MAI `.env` su GitHub
- Se il token viene esposto, rigenerarlo dall'APK
