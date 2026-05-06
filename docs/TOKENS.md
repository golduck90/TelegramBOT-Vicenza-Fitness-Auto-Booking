# 🗝️ WellTeam APPTOKEN — Vicenza Fitness

> ⚠️ **ATTENZIONE**: Questo file contiene token aziendali reali.
> Equivalgono a password. Non condividerli, non esporli.

Questo file raccoglie i **company-level APPTOKEN** necessari per
autenticarsi all'API WellTeam di Vicenza Fitness.

## Token attivi

| Nome | Valore | Note |
|------|--------|------|
| `WELLTEAM_APP_TOKEN` | `WELLTEAM_APP_TOKEN_RIMOSSO` | Token company-level originale (da APK decompilato) |

## Come ottenere un nuovo token (se serve)

1. Decomprimi l'APK ufficiale WellTeam: `apktool d WellTeam.apk`
2. Cerca in `res/values/strings.xml` la stringa `app_token` o `AppToken`
3. Oppure cerca nel codice decompilato (jadx) la costante `APP_TOKEN`

## Come usarlo

Copia `.env.example` → `.env` e inserisci il token:

```env
WELLTEAM_APP_TOKEN=2AEAC60F19EF...
```

Il bot carica il token automaticamente all'avvio.
