"""
Handler: Lista Corsi e Prenotazione.

📋 Lista Corsi → calendario settimanale (solo visualizzazione)
📅 Prenota → scegli corso → auto o singola prenotazione

Architettura:
- course_catalog.json è l'unica fonte della verità per la struttura dei corsi
- I dati live (posti disponibili, is_mine) vengono fetchati dall'API su richiesta
- Niente più cache DB intermedia
"""
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import db
import wellteam
import config
from handlers.decorators import require_auth, rate_limit
from handlers.menu import cb_force_refresh

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
    for key, friendly in _SERVER_ERROR_MAP.items():
        if key.lower() in msg_lower:
            return friendly
    if msg_lower.startswith("badrequest") or msg_lower.startswith("error"):
        return (
            f"Il server ha risposto: \"{msg}\".\n\n"
            "Alcuni corsi speciali (Gravity, Vacu Gym, ecc.) "
            "potrebbero non essere prenotabili tramite bot. "
            "Prova a prenotare direttamente in palestra o "
            "contatta la reception."
        )
    return msg

DAY_NAMES = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


async def _edit_or_send(update, text, reply_markup=None):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


# ═══════════════════════════════════════════════════════════
# HELPERS: catalog refresh + API live fetch
# ═══════════════════════════════════════════════════════════

async def _ensure_catalog_updated(telegram_id: int):
    """Assicura che il catalogo sia popolato, forza refresh se vuoto, con retry."""
    from course_catalog import get_course_count
    if get_course_count() > 0:
        return True  # catalogo già popolato
    # Primo tentativo
    ok = await _force_catalog_refresh(telegram_id)
    if not ok:
        logger.warning("Primo refresh catalogo fallito, riprovo...")
        await asyncio.sleep(2)
        ok = await _force_catalog_refresh(telegram_id)
    return ok


async def _force_catalog_refresh(telegram_id: int) -> bool:
    """Chiama l'API e aggiorna il catalogo."""
    from schedule_cache import refresh_schedule
    user = db.get_user(telegram_id)
    if not user or not user.get("auth_token"):
        return False
    return await asyncio.to_thread(
        refresh_schedule, telegram_id, user["auth_token"],
        user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
    )


async def _fetch_live_schedule(telegram_id: int, auth_token: str, iyes_url: str,
                                date_str: str) -> list:
    """Chiama l'API WellTeam per un singolo giorno e restituisce i corsi live."""
    success, items = await asyncio.to_thread(
        wellteam.get_schedule,
        auth_token=auth_token,
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=iyes_url,
        start_date=date_str,
        end_date=date_str,
    )
    return items if success else []


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


async def _show_corsi(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str = "view"):
    """Mostra giorni con conteggio corsi — tutto dal catalogo."""
    telegram_id = update.effective_user.id
    await _ensure_catalog_updated(telegram_id)

    from course_catalog import get_all_days_with_courses
    catalog_days = get_all_days_with_courses()

    if not catalog_days:
        await _edit_or_send(update,
            "⚠️ *Catalogo non ancora disponibile.*\n"
            "Tocca il pulsante per scaricarlo.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Scarica calendario", callback_data="force_refresh")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ])
        )
        context.user_data["corsi_mode"] = mode
        return

    now_wd = datetime.now().weekday()
    bookable_days = {(now_wd + d) % 7 for d in range(4)}
    mode_label = "📅 *Prenota un corso*"
    context.user_data["corsi_mode"] = mode

    msg = f"{mode_label}\n\n📆 *Scegli un giorno:*\n\n"
    buttons = []
    for i in range(7):
        cnt = catalog_days.get(i, 0)
        if cnt == 0:
            continue
        today = " ← Oggi" if i == now_wd else ""

        if i in bookable_days:
            icon = "🟢"
            label = f"{cnt} corsi, prenotabili"
        else:
            icon = "🟠"
            label = f"{cnt} corsi, solo auto-booking"

        buttons.append([InlineKeyboardButton(
            f"{icon} {DAY_NAMES[i]} ({label}){today}",
            callback_data=f"corsi_day_{i}"
        )])

    msg += "🟢 prenotabili | 🟠 solo auto-booking (da catalogo)\n\n"

    buttons.append([InlineKeyboardButton("🔄 Ricarica calendario", callback_data="force_refresh")])
    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="menu_home")])

    await _edit_or_send(update, msg, InlineKeyboardMarkup(buttons))


@rate_limit
async def cb_show_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra corsi per un giorno — catalogo + API live per oggi+3."""
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    day = int(query.data.split("_")[-1])
    mode = context.user_data.get("corsi_mode", "view")

    # ── 1) CATALOGO: struttura base (tutti i corsi conosciuti per questo giorno) ──
    from course_catalog import get_day_courses
    catalog_courses = get_day_courses(day)

    if not catalog_courses:
        await query.edit_message_text(
            f"❌ Nessun corso per {DAY_NAMES[day]}.\n"
            "Prova ad aggiornare il calendario o torna più tardi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Aggiorna", callback_data="force_refresh")],
                [InlineKeyboardButton("🔙 Giorni", callback_data="corsi_back_days")],
            ])
        )
        return

    # ── 2) API LIVE: per giorni prenotabili, prendi posti e is_mine ──
    now_wd = datetime.now().weekday()
    bookable_days = {(now_wd + d) % 7 for d in range(4)}
    is_bookable = day in bookable_days

    live_index = {}
    if is_bookable:
        from course_catalog import next_date_for_weekday
        date_str = next_date_for_weekday(day)
        user = db.get_user(telegram_id)
        if user and user.get("auth_token"):
            live_items = await _fetch_live_schedule(
                telegram_id, user["auth_token"],
                user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
                date_str,
            )
            for item in live_items:
                key = (
                    item.get("IDServizio"),
                    item.get("StartTime", "")[11:16] if len(item.get("StartTime", "")) > 16 else item.get("StartTime", ""),
                    item.get("AdditionalInfo", ""),
                )
                live_index[key] = item

    # ── 3) COSTRUISCI DISPLAY: catalogo + overlay API live ──
    display = []
    green = 0
    orange = 0

    for cat in sorted(catalog_courses, key=lambda c: c["start_time"]):
        key = (cat["service_id"], cat["start_time"], cat.get("instructor", ""))
        match = live_index.get(key)

        if match:
            # 🟢 API live: ha posti e dati freschi
            avail = match.get("AvailablePlaces")
            total = match.get("MaxPrenotazioni")
            booked = match.get("IsUserPresent", False)
            places_str = f" ({avail}/{total})" if avail is not None else ""
            display.append({
                "service_id": cat["service_id"],
                "description": cat["description"],
                "start_time": cat["start_time"],
                "end_time": cat["end_time"],
                "instructor": cat.get("instructor", ""),
                "category": cat.get("category", ""),
                "is_mine": booked,
                "dot": "🟢",
                "live_avail": avail,
                "live_total": total,
                "live_booked": booked,
            })
            green += 1
        else:
            # 🟠 Solo catalogo
            display.append({
                "service_id": cat["service_id"],
                "description": cat["description"],
                "start_time": cat["start_time"],
                "end_time": cat["end_time"],
                "instructor": cat.get("instructor", ""),
                "category": cat.get("category", ""),
                "is_mine": False,
                "dot": "🟠",
            })
            orange += 1

    total = len(display)
    legenda_parts = []
    if green: legenda_parts.append(f"🟢{green}")
    if orange: legenda_parts.append(f"🟠{orange}")
    legenda = " · ".join(legenda_parts)

    msg = f"📅 *{DAY_NAMES[day]}* — {total} corsi ({legenda})\n\n"

    buttons = []
    for c in sorted(display, key=lambda x: x["start_time"]):
        ore = c["start_time"][:5]
        booked = " ✅" if c.get("is_mine") else ""

        if c["dot"] == "🟢":
            instr = f" 👤{c['instructor']}" if c.get("instructor") else ""
            spots = f" ({c['live_avail']}/{c['live_total']})" if c.get("live_avail") is not None and not c.get("is_mine") else ""
            btn_label = f"{c['dot']} {ore} {c['description']}{instr}{spots}{booked}"
        else:
            btn_label = f"{c['dot']} {ore} {c['description']}"

        if mode == "book":
            cb = f"book_pick_{c['service_id']}_{day}_{c['start_time']}|{c.get('instructor','')[:20]}"
            buttons.append([InlineKeyboardButton(btn_label, callback_data=cb)])

    msg += "*Tocca un corso per prenotarlo o attivare auto-booking.*"

    nav = [
        [InlineKeyboardButton("🔙 Giorni", callback_data="corsi_back_days"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu_home")],
    ]
    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons + nav))


async def cb_back_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Torna alla scelta giorni."""
    await _show_corsi(update, context, mode=context.user_data.get("corsi_mode", "view"))


# ═══════════════════════════════════════════════════════════
# PRENOTA UN CORSO (singola o auto)
# ═══════════════════════════════════════════════════════════

@rate_limit
async def cb_pick_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Utente ha scelto un corso → mostra posti live via API + scegli azione."""
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

    try:
        service_id = int(parts[0])
    except ValueError:
        await query.edit_message_text("❌ *Dati corso non validi.* Riprova.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")]
            ]))
        return
    try:
        day = int(parts[1])
    except ValueError:
        await query.edit_message_text("❌ *Dati giorno non validi.* Riprova.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")]
            ]))
        return
    rest = parts[2].split("|")
    start_time = rest[0]
    instructor = rest[1] if len(rest) > 1 else ""

    # Recupera info corso dal catalogo
    from course_catalog import get_day_courses
    desc = ""
    end_time = ""
    for cat in get_day_courses(day):
        if cat["service_id"] == service_id and cat["start_time"] == start_time:
            desc = cat["description"]
            end_time = cat.get("end_time", "")
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

    # Salva in context
    context.user_data["book_course"] = {
        "service_id": service_id,
        "day": day,
        "start_time": start_time,
        "end_time": end_time,
        "instructor": instructor,
        "description": desc,
    }

    # 🎯 LIVE FETCH: chiama API per vedere posti disponibili
    user = db.get_user(telegram_id)
    spots_text = ""
    can_book_now = False
    today = datetime.now()

    if user and user.get("auth_token"):
        from course_catalog import next_date_for_weekday
        date_str = next_date_for_weekday(day)

        success, lessons = wellteam.get_schedule(
            auth_token=user["auth_token"],
            app_token=config.WELLTEAM_APP_TOKEN,
            iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
            start_date=date_str,
            end_date=date_str,
        )
        if success and lessons:
            for les in lessons:
                if les.get("IDServizio") != service_id:
                    continue
                les_start = les.get("StartTime", "")[11:16] if len(les.get("StartTime", "")) > 16 else les.get("StartTime", "")
                if les_start != start_time:
                    continue
                if instructor and instructor.lower() not in les.get("AdditionalInfo", "").lower():
                    continue
                # Trovato!
                avail = les.get("AvailablePlaces", 0)
                total = les.get("MaxPrenotazioni", 0)
                already_booked = les.get("IsUserPresent", False)
                if avail > 0 and not already_booked:
                    spots_text = f"🎯 *{avail} posti disponibili* su {total}"
                    can_book_now = True
                elif already_booked:
                    spots_text = "✅ *Sei già prenotato* per questa data!"
                elif avail == 0:
                    spots_text = "⏳ *Posti esauriti* per questa data"
                else:
                    spots_text = f"📊 {avail}/{total} posti"
                break

    instr_text = f" 👤 {instructor}" if instructor else ""
    msg = (
        f"🏋️ *{desc}*\n"
        f"📅 {DAY_NAMES[day]} alle {start_time[:5]}{instr_text}\n\n"
    )
    if spots_text:
        msg += f"{spots_text}\n\n"

    # 🔍 Verifica se auto-booking già attivo per questo corso
    auto_active = db.check_auto_book_exists(
        telegram_id, service_id, day, start_time, instructor
    )

    if auto_active:
        msg += "✅ *Auto-booking già attivo* per questo corso!"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Gestisci auto-booking", callback_data="menu_autobook")],
            [InlineKeyboardButton("🔙 Indietro", callback_data=f"corsi_day_{day}")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu_home")],
        ])
    else:
        msg += "*Attiva auto-booking:* il bot prenoterà ogni settimana appena disponibile."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Attiva auto-booking", callback_data="book_do_auto")],
            [InlineKeyboardButton("🔙 Indietro", callback_data=f"corsi_day_{day}")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu_home")],
        ])

    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)


@rate_limit
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
    from course_catalog import next_date_for_weekday
    date_str = next_date_for_weekday(c["day"])

    # 3) Recupera il calendario per quella data
    user = db.get_user(telegram_id)
    if not user or not user.get("auth_token"):
        await _confirm_autobook(context, query, c, item_id, description)
        return

    success, lessons = await asyncio.to_thread(
        wellteam.get_schedule,
        auth_token=user["auth_token"],
        app_token=config.WELLTEAM_APP_TOKEN,
        iyes_url=user.get("iyes_url", "") or config.WELLTEAM_IYES_URL,
        start_date=date_str,
        end_date=date_str,
    )

    if not success or not lessons:
        await _confirm_autobook(context, query, c, item_id, description,
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
        await _confirm_autobook(context, query, c, item_id, description,
                                extra=f"\n\n📅 {date_str} — corso non trovato nel calendario, proverò al prossimo ciclo.")
        return

    # 5) Controlla stato prenotazione
    if lesson.get("IsUserPresent"):
        await _confirm_autobook(context, query, c, item_id, description,
                                extra=f"\n\n✅ Sei già prenotato per {date_str}!")
        return

    if lesson.get("AvailablePlaces", 1) == 0:
        await _confirm_autobook(context, query, c, item_id, description,
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


async def _confirm_autobook(context, query, c, item_id, description, extra=""):
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
        db.update_auto_book_last_booked(d["item_id"], d["lesson_id"], d["date"])
        # Salva nei reminder per attivare il check 3h/60min
        db.upsert_booking_reminder(
            query.from_user.id, d["lesson_id"], d["date"],
            d["start_time"][:5], d["description"], d.get("instructor", ""),
        )
        text = (
            f"✅ *Prenotato!*\n\n"
            f"🏋️ *{d['description']}*\n"
            f"📅 {d['date']} alle {d['start_time'][:5]}\n"
            f"{'👤 ' + d['instructor'] if d.get('instructor') else ''}\n\n"
            f"🎉 L'auto-booking prenoterà automaticamente le prossime settimane!"
        )
    else:
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


@rate_limit
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

    today = datetime.now()
    check_dates = [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(14)]

    found_lesson = None
    for date_str in check_dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.weekday() != c["day"]:
            continue

        success, items = await asyncio.to_thread(
            wellteam.get_schedule,
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

    lesson = found_lesson
    lesson_id = lesson.get("IDLesson") or 0
    date = (lesson.get("DateLesson") or "")[:10]
    if not date:
        st = lesson.get("StartTime", "")
        date = st[:10] if len(st) >= 10 else datetime.now().strftime("%Y-%m-%d")
    bs = lesson.get("StartTime", "")
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
        # Salva nei reminder per attivare il check 3h/60min
        db.upsert_booking_reminder(
            telegram_id, lesson_id, date,
            c["start_time"][:5], c["description"], c.get("instructor", ""),
        )
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
    success, books = await asyncio.to_thread(
        wellteam.get_my_books,
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
            context.user_data["cancel_bookings"][str(bid)] = {
                "lesson_id": lid,
                "start_time": b.get("StartTime", ""),
                "end_time": b.get("EndTime", ""),
                "desc": desc,
            }
            buttons.append([InlineKeyboardButton(f"❌ Cancella: {desc[:20]} {date}", callback_data=f"cancel_{bid}")])

    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="menu_home")])
    await _edit_or_send(update, msg[:4000], InlineKeyboardMarkup(buttons))


@rate_limit
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

    booking_id = int(query.data.split("_")[-1])
    cancel_data = context.user_data.get("cancel_bookings", {}).get(str(booking_id))

    if not cancel_data:
        await query.edit_message_text("❌ *Dati non trovati.* Ricarica le prenotazioni.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Ricarica", callback_data="menu_prenotazioni")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_home")],
            ]))
        return

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
            pass

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
        db.delete_booking_reminder_by_lesson(telegram_id, cancel_data["lesson_id"])
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
    app.add_handler(CallbackQueryHandler(cb_force_refresh, pattern="^force_refresh$"))

    app.add_handler(CallbackQueryHandler(cmd_lista_corsi, pattern="^menu_corsi$"))
    app.add_handler(CallbackQueryHandler(cmd_prenota, pattern="^menu_prenota$"))
    app.add_handler(CallbackQueryHandler(cmd_prenotazioni, pattern="^menu_prenotazioni$"))

    app.add_handler(CommandHandler("corsi", cmd_lista_corsi))
    app.add_handler(CommandHandler("prenota", cmd_prenota))
    app.add_handler(CommandHandler("prenotazioni", cmd_prenotazioni))

    logger.info("📋 Handler corsi/prenotazioni registrati")
