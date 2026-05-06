# 🗝️ WellTeam AppToken — Vicenza Fitness

> ℹ️ **Nota**: Questo è un token aziendale statico estratto dall'APK ufficiale
> WellTeam. Non è un secret critico — è pubblico nell'APK stesso.
> Va inserito in `.env` per far funzionare il bot.

## Token attivo

| Nome | Valore |
|------|--------|
| `WELLTEAM_APP_TOKEN` | `2AEAC60F19EF3A1C1BCAF55BE0A6CD189D3FB8697563C5E076D84A17DE343C36135E25EE562F12EF859291413467CA69D453402EC504AE90A0EEB824CA84DC7C52F20599130A126D363759FFA5E1EE25CEE5D098A6069BADEA343A53865F6EEBE98EADFA117D38BB30A0ADB20344B1DBF386B6580DC89D218EEF2ECFA08FBF5A0964A70805B0247469BD90CF7CCD9625BE52D238BFE6D1C12E35B8A9DBD432BF` |

## Come usarlo

```bash
cp .env.example .env
# inserisci i token in .env
```

Variabili richieste in `.env`:

| Variabile | Descrizione |
|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Token del bot Telegram (da @BotFather) |
| `WELLTEAM_APP_TOKEN` | Token company-level WellTeam (sopra) |

## Note

- Il token è statico, estratto dall'APK WellTeam originale
- Può essere tranquillamente pubblico (è già nell'APK)
- `TELEGRAM_BOT_TOKEN` invece è un vero secret — **non condividerlo mai**
