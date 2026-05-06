"""
Handler: Lista Corsi e Prenotazione.

📋 Lista Corsi → calendario settimanale (solo visualizzazione)
📅 Prenota → scegli corso → auto o singola prenotazione
"""
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import db
import wellteam
import config
from handlers.decorators import require_auth, rate_limit

logger = logging.getLogger("bot")

# ── Mapping errori server → messaggi user-friendly ──
_SERVER_ERROR_MAP = {
    "book_conflict": "Sei già prenotato per questo corso in questa data e orario.",
    "Internal Server Error": (
        "Il server WellTeam ha risposto con un errore per questo corso.\n"
        "Alcuni corsi (es. Gravity, Vacu Gym) potrebbero richiedere "
        "prenotazione direttamente in palestra.\n\n"
        "Prova con un altro corso o contatta la reception."
    ),
    "BadRequest": "Richiesta non valida. Verifica i dati del corso e riprova.",
    "Not Found": "Corso o lezione non trovata. Potrebbe essere stato rimosso.",
    "BookNr not valid": "Prenotazione multipla non supportata per questo corso.",
    "Unauthorized": "Sessione scaduta. Effettua di nuovo il login.",
}

def _friendly_error(msg: str) -> str:
    """Traduce un messaggio di errore del server in testo user-friendly."""
    if not msg:
        return "Errore sconosciuto durante la prenotazione. Riprova più tardi."

    msg_lower = msg.lower()

    # Cerca pattern specifici
    for key, friendly in _SERVER_ERROR_MAP.items():
        if key.lower() in msg_lower:
            return friendly

    # Se il messaggio è troppo generico o sembra un errore tecnico
    if msg_lower.startswith("badrequest") or msg_lower.startswith("error"):
        return (
            f"Il server ha risposto: \"{msg}\".\n\n"
            "Alcuni corsi speciali (Gravity, Vacu Gym, ecc.) "
            "potrebbero non essere prenotabili tramite bot. "
            "Prova a prenotare direttamente in palestra o "
            "contatta la reception."
        )

    # Fallback: mostra il messaggio originale ma con contesto
    return msg

DAY_NAMES = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _week_key():
    now = datetime.now()
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _next_week_key():
    from datetime import timedelta
    nxt = datetime.now() + timedelta(days=7)
    iso = nxt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


async def _edit_or_send(update, text, reply_markup=None):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


# ═══════════════════════════════════════════════════════════
# LISTA CORSI (solo visualizzazione)
# ═══════════════════════════════════════════════════════════

@rate_limit
@require_auth
async def cmd_lista_corsi(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """📋 Lista Corsi — mostra calendario settimanale."""
    await _show_corsi(update, context, mode="view")


@rate_limit
@require_auth
async def cmd_prenota(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """📅 Prenota — scegli corso e prenota."""
    await _show_corsi(update, context, mode="book")


async def _check_cache(telegram_id):
    """Verifica se c'è cache, altrimenti la forza."""
    cached = db.get_cached_schedule(telegram_id, _week_key())
    if not cached:
        cached = db.get_cached_schedule(telegram_id, _next_week_key())
    if not cached:
        # Forza refresh
        from schedule_cache import refresh_schedule
        user = db.get_user(telegram_id)
        if user:
            refresh_schedule(telegram_id, user["auth_token"], user.get("iyes_url", "") or config.WELLTEAM_IYES_URL)
            cached = db.get_cached_schedule(telegram_id, _week_key())
            if not cached:
                cached = db.get_cached_schedule(telegram_id, _next_week_key())
    return cached


async def _show_corsi(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str = "view"):
    """Mostra giorni con conteggio corsi."""
    telegram_id = update.effective_user.id
    cached = await _check_cache(telegram_id)

    if not cached:
        await _edit_or_send(update,
            "⚠️ *Calendario non ancora disponibile.*\n"
            "Tocca il pulsante per scaricarlo.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Scarica calendario", callback_data="force_refresh")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
        context.user_data["corsi_mode"] = mode  # Ricorda la modalità
        return

    # Conta per giorno
    day_count = {}
    for c in cached:
        dw = c["day_of_week"]
        day_count[dw] = day_count.get(dw, 0) + 1

    now_wd = datetime.now().weekday()
    # Finestra prenotabile: oggi + 3 giorni (VisibleDays=4)
    bookable_days = {(now_wd + d) % 7 for d in range(4)}
    mode_label = "📅 *Prenota un corso*"
    context.user_data["corsi_mode"] = mode

    msg = f"{mode_label}\n\n📆 *Scegli un giorno:*\n\n"
    buttons = []
    for i in range(7):
        cnt = day_count.get(i, 0)
        today = " ← Oggi" if i == now_wd else ""
        if cnt > 0:
            if i in bookable_days:
                icon = "🟢"
                label = "disponibile"
            else:
                icon = "🟡"
                label = "in arrivo"
            buttons.append([InlineKeyboardButton(
                f"{icon} {DAY_NAMES[i]} ({cnt} corsi, {label}){today}",
                callback_data=f"corsi_day_{i}"
            )])

    # Aggiungi legenda
    msg += "🟢 disponibile | 🟡 in arrivo (solo auto-booking) | ⚪ nessun corso\n\n"

    buttons.append([InlineKeyboardButton("🔄 Ricarica calendario", callback_data="force_refresh")])
    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="menu_home")])

    await _edit_or_send(update, msg, InlineKeyboardMarkup(buttons))


async def cb_show_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra corsi per un giorno specifico."""
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    day = int(query.data.split("_")[-1])
    mode = context.user_data.get("corsi_mode", "view")

    # Recupera dalla cache (prova settimana corrente, poi prossima)
    wk = _week_key()
    courses = db.get_cached_schedule_by_day(telegram_id, day, wk)
    if not courses:
        courses = db.get_cached_schedule_by_day(telegram_id, day, _next_week_key())

    if not courses:
        await query.edit_message_text(
            f"❌ Nessun corso per {DAY_NAMES[day]}.\n"
            "Prova ad aggiornare il calendario.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Aggiorna", callback_data="force_refresh")],
                [InlineKeyboardButton("🔙 Giorni", callback_data="corsi_back_days")],
            ])
        )
        return

    msg = f"📅 *{DAY_NAMES[day]}* — {len(courses)} corsi\n\n"

    # Determina se è un giorno prenotabile o in arrivo
    now_wd = datetime.now().weekday()
    bookable_days = {(now_wd + d) % 7 for d in range(4)}
    if day in bookable_days:
        msg += "🟢 *Corsi prenotabili* — posti disponibili aggiornati in tempo reale\n\n"
    else:
        msg += "🟡 *Corsi in arrivo* — non ancora prenotabili.\n"
        msg += "   Puoi impostare l'*auto-booking*, prenoterò appena disponibili!\n\n"
    buttons = []

    # Raggruppa per categoria
    cats = {}
    for c in courses:
        cat = c.get("category") or "Altri"
        if cat not in cats:
            cats[cat] = []
        cats[cat].append(c)

    for cat_name, cat_courses in sorted(cats.items()):
        msg += f"📂 *{cat_name}*\n"
        for c in sorted(cat_courses, key=lambda x: x["start_time"]):
            instr = f" — 👤 {c['instructor']}" if c.get("instructor") else ""
            ore = c["start_time"][:5]
            booked = " ✅ Già prenotato" if c.get("is_mine") else ""
            msg += f"  🕐 {ore} {c['description']}{instr}{booked}\n"
            if mode == "book":
                cb = f"book_pick_{c['service_id']}_{day}_{c['start_time']}|{c.get('instructor','')[:20]}"
                buttons.append([InlineKeyboardButton(f"📅 {c['description']} — {ore}", callback_data=cb)])

    msg += "\n"
    if mode == "book":
        msg += "*Tocca un corso per prenotarlo o impostare auto-booking.*"

    nav = [
        [InlineKeyboardButton("🔙 Giorni", callback_data="corsi_back_days"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu_home")],
    ]

    # Costruisce KB: navigation + corsi
    kb_rows = nav + buttons
    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_back_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Torna alla scelta giorni."""
    await _show_corsi(update, context, mode=context.user_data.get("corsi_mode", "view"))


# ═══════════════════════════════════════════════════════════
# PRENOTA UN CORSO (singola o auto)
# ═══════════════════════════════════════════════════════════

async def cb_pick_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Utente ha scelto un corso → chiede auto o singola."""
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id

    # book_pick_{service_id}_{day}_{start_time}|{instructor}
    data = query.data
    payload = data[10:]  # Rimuovi "book_pick_" (10 chars)
    parts = payload.rsplit("_", 2)
    if len(parts) < 3:
        await query.edit_message_text("❌ Errore.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")]
        ]))
        return

    service_id = int(parts[0])
    day = int(parts[1])
    rest = parts[2].split("|")
    start_time = rest[0]
    instructor = rest[1] if len(rest) > 1 else ""

    # Recupera info corso dalla cache
    wk = _week_key()
    courses = db.get_cached_schedule_by_day(telegram_id, day, wk)
    if not courses:
        courses = db.get_cached_schedule_by_day(telegram_id, day, _next_week_key())
    desc = ""
    end_time = ""
    for c in courses:
        if c["service_id"] == service_id and c["start_time"] == start_time:
            desc = c["description"]
            end_time = c["end_time"]
            break

    if not desc:
        await query.edit_message_text(
            "❌ *Corso non trovato.* Forse il calendario è cambiato.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Aggiorna", callback_data="force_refresh")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
        return

    # Salva in context e chiedi decisione
    context.user_data["book_course"] = {
        "service_id": service_id,
        "day": day,
        "start_time": start_time,
        "end_time": end_time,
        "instructor": instructor,
        "description": desc,
    }

    instr_text = f" 👤 {instructor}" if instructor else ""
    await query.edit_message_text(
        f"🏋️ *{desc}*\n"
        f"📅 {DAY_NAMES[day]} alle {start_time[:5]}{instr_text}\n\n"
        f"*Cosa vuoi fare?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Prenota automaticamente ogni settimana", callback_data="book_do_auto")],
            [InlineKeyboardButton("🔙 Indietro", callback_data=f"corsi_day_{day}")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu_home")],
        ])
    )


async def cb_book_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Aggiunge all'auto-booking. Se non già prenotato per questa settimana,
    chiede se prenotare subito."""
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    c = context.user_data.get("book_course")
    if not c:
        await query.edit_message_text("❌ *Sessione scaduta.* Riprova.", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ]))
        return

    # 1) Aggiungi all'auto-booking
    description = c["description"]
    item_id = db.add_auto_book_item(
        telegram_id, c["service_id"], description,
        c["day"], c["start_time"], c["end_time"], c.get("instructor", "")
    )

    # 2) Calcola la prossima data per questo giorno della settimana
    from datetime import datetime, timedelta
    today = datetime.now()
    target_date = today + timedelta(days=(c["day"] - today.weekday()) % 7)
    if target_date <= today:
        target_date += timedelta(days=7)
    date_str = target_date.strftime("%Y-%m-%d")

    # 3) Recupera il calendario per quella data
    user = db.get_user(telegram_id)
    if not user or not user.get("auth_token"):
        # Conferma auto-booking e basta
        await _confirm_autobook(query, c, item_id, description)
        return

    import wellteam, config
    success, lessons = wellteam.get_schedule(
        auth_token=user["auth_token"],
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
        start_date=date_str,
        end_date=date_str,
    )

    if not success or not lessons:
        await _confirm_autobook(query, c, item_id, description,
                                extra=f"\n\n📅 {date_str} — calendario non disponibile, proverò al prossimo ciclo.")
        return

    # 4) Trova la lezione corrispondente
    start_wanted = c["start_time"][:5]
    instructor_wanted = c.get("instructor", "").lower()
    lesson = None
    for les in lessons:
        if les.get("IDServizio") != c["service_id"]:
            continue
        les_start = les.get("StartTime", "")[11:16] if len(les.get("StartTime", "")) > 16 else les.get("StartTime", "")
        if les_start != start_wanted:
            continue
        if instructor_wanted and instructor_wanted not in les.get("AdditionalInfo", "").lower():
            continue
        lesson = les
        break

    if not lesson:
        await _confirm_autobook(query, c, item_id, description,
                                extra=f"\n\n📅 {date_str} — corso non trovato nel calendario, proverò al prossimo ciclo.")
        return

    # 5) Controlla stato prenotazione
    if lesson.get("IsUserPresent"):
        await _confirm_autobook(query, c, item_id, description,
                                extra=f"\n\n✅ Sei già prenotato per {date_str}!")
        return

    if lesson.get("AvailablePlaces", 1) == 0:
        await _confirm_autobook(query, c, item_id, description,
                                extra=f"\n\n⏳ Posti esauriti per {date_str}. Riproverò al prossimo ciclo!")
        return

    # 6) Posto disponibile e non prenotato → chiedi se prenotare subito
    context.user_data["ab_booking"] = {
        "lesson_id": lesson["IDLesson"],
        "service_id": c["service_id"],
        "start_time": c["start_time"],
        "end_time": c["end_time"],
        "date": date_str,
        "description": description,
        "item_id": item_id,
        "instructor": c.get("instructor", ""),
    }

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sì, prenota ora", callback_data="ab_book_now_yes")],
        [InlineKeyboardButton("❌ No, dalla prossima settimana", callback_data="ab_book_now_no")],
        [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
    ])
    await query.edit_message_text(
        f"🤖 *Auto-booking attivato!* 🆔 #{item_id}\n\n"
        f"🏋️ *{description}*\n"
        f"📅 {DAY_NAMES[c['day']]} — {c['start_time'][:5]}\n\n"
        f"🎯 C'è un posto disponibile per *{date_str}*!\n"
        f"*Vuoi prenotarlo subito?*",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _confirm_autobook(query, c, item_id, description, extra=""):
    """Conferma che l'auto-booking è stato attivato."""
    await query.edit_message_text(
        f"✅ *Auto-booking attivato!* 🆔 #{item_id}\n\n"
        f"🏋️ *{description}*\n"
        f"📅 {DAY_NAMES[c['day']]} — {c['start_time'][:5]}\n\n"
        f"🤖 Lo prenoterò ogni settimana appena disponibile!\n"
        f"⏰ Controllo automatico ogni notte alle 00:10.{extra}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Gestisci auto-booking", callback_data="menu_autobook")],
            [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
        ])
    )
    context.user_data.pop("book_course", None)


async def cb_ab_book_now_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prenota subito dopo che l'utente ha detto sì."""
    query = update.callback_query
    await query.answer()
    d = context.user_data.get("ab_booking")
    if not d:
        await query.edit_message_text("❌ *Sessione scaduta.*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ]))
        return

    await query.edit_message_text("🔄 *Prenoto...*", parse_mode="Markdown")

    user = db.get_user(query.from_user.id)
    import wellteam, config
    bs = f"{d['date']}T{d['start_time']}:00"
    be = f"{d['date']}T{d['end_time']}:00"

    ok, msg = wellteam.book_course(
        auth_token=user["auth_token"],
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
        lesson_id=d["lesson_id"],
        service_id=d["service_id"],
        start_time=bs,
        end_time=be,
    )

    db.log_booking(query.from_user.id, d["description"], d["lesson_id"], bs, "book", ok, msg)

    if ok:
        # Segna come prenotato anche nell'auto-booking
        db.update_auto_book_last_booked(d["item_id"], d["lesson_id"], d["date"])
        text = (
            f"✅ *Prenotato!*\n\n"
            f"🏋️ *{d['description']}*\n"
            f"📅 {d['date']} alle {d['start_time'][:5]}\n"
            f"{'👤 ' + d['instructor'] if d.get('instructor') else ''}\n\n"
            f"🎉 L'auto-booking prenoterà automaticamente le prossime settimane!"
        )
    else:
        from handlers.corsi import _friendly_error
        text = (
            f"❌ *Prenotazione non riuscita*\n\n"
            f"🏋️ *{d['description']}*\n"
            f"📅 {d['date']} alle {d['start_time'][:5]}\n\n"
            f"Motivo: _{_friendly_error(msg)}_\n\n"
            f"🤖 L'auto-booking è comunque attivo 🆔 #{d['item_id']}, "
            f"proverà al prossimo ciclo!"
        )

    context.user_data.pop("ab_booking", None)
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Gestisci auto-booking", callback_data="menu_autobook")],
            [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
        ])
    )


async def cb_ab_book_now_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Utente dice no a prenotazione immediata."""
    query = update.callback_query
    await query.answer()
    d = context.user_data.get("ab_booking")
    if d:
        context.user_data.pop("ab_booking", None)

    await query.edit_message_text(
        f"✅ *Auto-booking attivato!* 🆔 #{d.get('item_id', '?') if d else '?'}\n\n"
        f"🤖 Prenoterò automaticamente dalla prossima settimana disponibile!\n"
        f"⏰ Controllo ogni notte alle 00:10.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Gestisci auto-booking", callback_data="menu_autobook")],
            [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
        ])
    )


async def cb_book_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prenota subito (singola volta)."""
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    c = context.user_data.get("book_course")
    if not c:
        await query.edit_message_text("❌ *Sessione scaduta.*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ]))
        return

    user = db.get_user(telegram_id)
    if not user:
        await query.edit_message_text("❌ *Devi fare login.*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Login", callback_data="login_start")],
            ]))
        return

    await query.edit_message_text("🔄 *Cerco posti disponibili...*", parse_mode="Markdown")

    # Cerca la prossima lezione disponibile
    from datetime import timedelta
    today = datetime.now()
    check_dates = [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(14)]

    found_lesson = None
    for date_str in check_dates:
        # Verifica che sia il giorno giusto
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.weekday() != c["day"]:
            continue

        success, items = wellteam.get_schedule(
            auth_token=user["auth_token"],
            app_token=config.WELLTEAM_APP_TOKEN,
            iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
            start_date=date_str,
            end_date=date_str,
        )
        if not success or not items:
            continue

        for lesson in items:
            if lesson.get("IDServizio") != c["service_id"]:
                continue
            les_start = lesson.get("StartTime", "")[11:16] if len(lesson.get("StartTime", "")) > 16 else lesson.get("StartTime", "")
            if les_start != c["start_time"]:
                continue
            if lesson.get("IsUserPresent"):
                await query.edit_message_text(
                    f"✅ *Sei già prenotato per {c['description']} il {date_str}!*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
                    ])
                )
                return
            if lesson.get("AvailablePlaces", 1) == 0:
                continue
            found_lesson = lesson
            break
        if found_lesson:
            break

    if not found_lesson:
        await query.edit_message_text(
            f"❌ *Nessun posto disponibile* per {c['description']}.\n\n"
            f"Prova con l'auto-booking: ti prenoto appena possibile! 🤖",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 Auto-booking", callback_data="menu_autobook")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
        return

    # Prenota!
    lesson = found_lesson
    lesson_id = lesson.get("IDLesson") or 0
    date = (lesson.get("DateLesson") or "")[:10]
    if not date:
        st = lesson.get("StartTime", "")
        date = st[:10] if len(st) >= 10 else datetime.now().strftime("%Y-%m-%d")
    bs = lesson.get("StartTime", "")
    # FIX: API restituisce "1900-01-01THH:MM:SS" (19 char). Estrai solo HH:MM:SS.
    bs_time = bs[11:19] if len(bs) >= 19 and "1900-01-01" in bs else bs
    bs = f"{date}T{bs_time}" if bs_time else bs
    be = lesson.get("EndTime", "")
    be_time = be[11:19] if len(be) >= 19 and "1900-01-01" in be else be
    be = f"{date}T{be_time}" if be_time else be

    ok, msg = wellteam.book_course(
        auth_token=user["auth_token"],
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
        lesson_id=lesson_id,
        service_id=c["service_id"],
        start_time=bs,
        end_time=be,
    )

    if ok:
        await query.edit_message_text(
            f"✅ *Prenotato!*\n\n"
            f"🏋️ *{c['description']}*\n"
            f"📅 {date} alle {c['start_time'][:5]}\n\n"
            f"Buon allenamento! 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 Auto-booking ricorrente", callback_data="menu_autobook")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
        db.log_booking(telegram_id, c["description"], lesson_id, bs, "book", True, msg)
    else:
        friendly_msg = _friendly_error(msg)
        await query.edit_message_text(
            f"❌ *{friendly_msg}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
        db.log_booking(telegram_id, c["description"], lesson_id, bs, "book", False, msg)

    context.user_data.pop("book_course", None)


# ═══════════════════════════════════════════════════════════
# PRENOTAZIONI ATTIVE (elenco, cancellazione)
# ═══════════════════════════════════════════════════════════

@rate_limit
@require_auth
async def cmd_prenotazioni(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    """Mostra prenotazioni attive."""
    telegram_id = update.effective_user.id
    success, books = wellteam.get_my_books(
        user["auth_token"],
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
    )

    if not success or not books:
        await _edit_or_send(update,
            "📭 *Nessuna prenotazione attiva.*\n\n"
            "Usa 📅 *Prenota* per prenotare un corso!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Prenota", callback_data="menu_prenota")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
        return

    msg = f"📅 *Le tue prenotazioni ({len(books)}):*\n\n"
    buttons = []
    # Salva i dettagli per la cancellazione (evita callback_data lunghi)
    context.user_data["cancel_bookings"] = {}
    for b in books:
        date = b.get("StartTime", "")[:10]
        time = b.get("StartTime", "")[11:16]
        desc = b.get("ServiceDescription", "")
        instr = b.get("AdditionalInfo", "")
        msg += f"🏋️ *{desc}*\n📅 {date} alle {time}"
        if instr:
            msg += f" — 👤 {instr}"
        msg += "\n\n"
        bid = b.get("BookingID")
        lid = b.get("IDLesson")
        if bid and lid:
            # Salva in context.user_data (persistente grazie a PicklePersistence)
            context.user_data["cancel_bookings"][str(bid)] = {
                "lesson_id": lid,
                "start_time": b.get("StartTime", ""),
                "end_time": b.get("EndTime", ""),
                "desc": desc,
            }
            buttons.append([InlineKeyboardButton(f"❌ Cancella: {desc[:20]} {date}", callback_data=f"cancel_{bid}")])

    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="menu_home")])
    await _edit_or_send(update, msg[:4000], InlineKeyboardMarkup(buttons))


async def cb_cancel_prenotazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancella una prenotazione."""
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    user = db.get_user(telegram_id)
    if not user:
        await query.edit_message_text("❌ *Non sei loggato.*", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Login", callback_data="login_start")]
        ]))
        return

    # cancel_{booking_id}
    booking_id = int(query.data.split("_")[-1])
    cancel_data = context.user_data.get("cancel_bookings", {}).get(str(booking_id))

    if not cancel_data:
        # Fallback: recupera le prenotazioni attive
        await query.edit_message_text("❌ *Dati non trovati.* Ricarica le prenotazioni.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Ricarica", callback_data="menu_prenotazioni")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ]))
        return

    # Blocco cancellazione se < 60 minuti all'inizio
    start_iso = cancel_data.get("start_time", "")
    if start_iso and len(start_iso) >= 16:
        try:
            lesson_dt = datetime.strptime(start_iso[:16], "%Y-%m-%dT%H:%M")
            minutes_until = (lesson_dt - datetime.now()).total_seconds() / 60.0
            if minutes_until < 60:
                await query.edit_message_text(
                    f"⏰ *Impossibile cancellare.*\n\n"
                    f"Mancano meno di 60 minuti all'inizio del corso.\n\n"
                    f"Per disdire, contatta direttamente Vicenza Fitness:\n"
                    f"📞 +39 0444 276 206",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
                    ])
                )
                return
        except ValueError:
            pass  # Se non si riesce a parsare, procedi comunque

    ok, msg = wellteam.cancel_course(
        auth_token=user["auth_token"],
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
        booking_id=booking_id,
        lesson_id=cancel_data["lesson_id"],
        start_time=cancel_data["start_time"],
        end_time=cancel_data["end_time"],
    )

    if ok:
        await query.edit_message_text(
            f"🗑️ *{cancel_data['desc'][:30]} cancellata.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Le mie prenotazioni", callback_data="menu_prenotazioni")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
        db.log_booking(telegram_id, cancel_data["desc"], cancel_data["lesson_id"], cancel_data["start_time"], "cancel", True, msg)
    else:
        friendly_msg = _friendly_error(msg)
        await query.edit_message_text(
            f"❌ *{friendly_msg}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )


# ═══════════════════════════════════════════════════════════
# REGISTRAZIONE
# ═══════════════════════════════════════════════════════════

def register(app):
    app.add_handler(CallbackQueryHandler(cb_show_day, pattern=r"^corsi_day_\d$"))
    app.add_handler(CallbackQueryHandler(cb_back_days, pattern="^corsi_back_days$"))
    app.add_handler(CallbackQueryHandler(cb_pick_course, pattern=r"^book_pick_\d+_\d+_.+$"))
    app.add_handler(CallbackQueryHandler(cb_book_auto, pattern="^book_do_auto$"))
    app.add_handler(CallbackQueryHandler(cb_book_now, pattern="^book_do_now$"))
    app.add_handler(CallbackQueryHandler(cb_cancel_prenotazione, pattern=r"^cancel_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ab_book_now_yes, pattern="^ab_book_now_yes$"))
    app.add_handler(CallbackQueryHandler(cb_ab_book_now_no, pattern="^ab_book_now_no$"))

    # Comandi / menu callback
    app.add_handler(CallbackQueryHandler(cmd_lista_corsi, pattern="^menu_corsi$"))
    app.add_handler(CallbackQueryHandler(cmd_prenota, pattern="^menu_prenota$"))
    app.add_handler(CallbackQueryHandler(cmd_prenotazioni, pattern="^menu_prenotazioni$"))

    # Comandi testuali (per autocomplete)
    app.add_handler(CommandHandler("corsi", cmd_lista_corsi))
    app.add_handler(CommandHandler("prenota", cmd_prenota))
    app.add_handler(CommandHandler("prenotazioni", cmd_prenotazioni))

    logger.info("📋 Handler corsi/prenotazioni registrati")
