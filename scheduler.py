"""
Scheduler — Esecuzione auto-booking ogni notte alle 00:10 (ora Roma).

Logica:
1. Per ogni item attivo, cerca la prossima occorrenza del corso
2. Se non è già prenotato e ha posti → prenota
3. Se il token è scaduto → re-login automatico con password cifrata
4. Segna come prenotato per evitare duplicati
"""
import logging
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import db
import wellteam
import config

logger = logging.getLogger("scheduler")

# Ora Roma: UTC+1 (CET) inverno, UTC+2 (CEST) estate
ROME_OFFSET = timezone(timedelta(hours=2))  # Maggio → CEST (+2)

TARGET_HOUR = 0      # 00:10
TARGET_MINUTE = 10

TOKEN_REFRESH_COOLDOWN = 300  # 5 min tra tentativi di refresh


class AutoBookScheduler:
    """
    Scheduler che esegue l'auto-booking ogni notte alle 00:10 ora Roma.
    """

    def __init__(self, interval_minutes: int = 30):
        self.interval = interval_minutes  # Usato solo per il delay tra i check
        self._running = False
        self._thread: threading.Thread = None
        self._last_run_day = -1
        self._last_token_refresh: Dict[int, float] = {}  # telegram_id → timestamp

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"✅ Scheduler avviato (esecuzione notturna 00:10 ora Roma)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)

    def _rome_now(self) -> datetime:
        return datetime.now(ROME_OFFSET)

    def _loop(self):
        while self._running:
            try:
                now = self._rome_now()
                # Esegue ogni giorno alle 00:10
                if now.hour == TARGET_HOUR and now.minute >= TARGET_MINUTE and self._last_run_day != now.day:
                    self._last_run_day = now.day
                    logger.info(f"🌙 Esecuzione auto-booking notturna ({now.strftime('%Y-%m-%d %H:%M')} Roma)")
                    self._execute_all()
                else:
                    # Forza esecuzione se appena avviato (primo ciclo)
                    if self._last_run_day == -1:
                        self._last_run_day = now.day
                        logger.info(f"🚀 Esecuzione auto-booking iniziale ({now.strftime('%Y-%m-%d %H:%M')} Roma)")
                        self._execute_all()
            except Exception as e:
                logger.error(f"Errore scheduler: {e}", exc_info=True)
            time.sleep(60)  # Check ogni minuto

    def _execute_all(self):
        """Esegue tutte le prenotazioni automatiche."""
        items = db.get_all_enabled_auto_book_items()
        if not items:
            logger.info("Nessun item auto-booking attivo")
            return

        logger.info(f"Processo {len(items)} item auto-booking")
        now_rome = self._rome_now()

        for item in items:
            try:
                self._process_item(item, now_rome)
            except Exception as e:
                logger.error(f"Errore processando item {item.get('id')}: {e}")

        logger.info("✅ Auto-booking notturno completato")

    def _refresh_token(self, item: Dict) -> Optional[str]:
        """
        Tenta di rinnovare il token WellTeam usando la password cifrata.
        Restituisce il nuovo auth_token o None se fallisce.
        Rispetta un cooldown per evitare refresh continui sullo stesso utente.
        """
        telegram_id = item["telegram_id"]
        now = time.time()

        # Cooldown: evita spam di refresh
        last_refresh = self._last_token_refresh.get(telegram_id, 0)
        if now - last_refresh < TOKEN_REFRESH_COOLDOWN:
            logger.debug(f"User {telegram_id}: refresh token in cooldown ({int(now - last_refresh)}s)")
            return None

        username = item.get("username", "")
        if not username:
            logger.error(f"User {telegram_id}: username mancante, impossibile refresh token")
            return None

        password = db.get_user_password(telegram_id)
        if not password:
            logger.error(f"User {telegram_id}: nessuna password salvata, impossibile refresh token")
            return None

        logger.info(f"🔄 User {telegram_id}: tentativo refresh token...")
        result = wellteam.authenticate(username, password)

        if not result:
            logger.warning(f"❌ User {telegram_id}: refresh token fallito (password errata?)")
            return None

        new_token = result["auth_token"]
        db.update_tokens(telegram_id, auth_token=new_token, app_token=config.WELLTEAM_APP_TOKEN)
        self._last_token_refresh[telegram_id] = now
        logger.info(f"✅ User {telegram_id}: token rinnovato con successo")
        return new_token

    def _process_item(self, item: Dict, now_rome: datetime):
        """
        Processa un singolo item: cerca la prossima lezione e prenota.
        Cerca nei prossimi 14 giorni (2 settimane).
        Se il token è scaduto, tenta refresh automatico e retry.
        """
        telegram_id = item["telegram_id"]
        item_id = item["id"]
        service_id = item["service_id"]
        start_time = item["start_time"][:5]
        instructor = item.get("instructor") or ""
        auth_token = item["auth_token"]
        iyes_url = item.get("iyes_url", "") or config.WELLTEAM_IYES_URL
        company_id = item.get("company_id", 2)

        # Prossimi 14 giorni
        today = now_rome.replace(hour=0, minute=0, second=0, microsecond=0)
        target_lesson = None
        target_date = None

        for day_offset in range(14):
            check_date = today + timedelta(days=day_offset)
            # Deve corrispondere al giorno della settimana
            if check_date.weekday() != item["day_of_week"]:
                continue

            date_str = check_date.strftime("%Y-%m-%d")

            # Già prenotato per questa data?
            if item.get("last_booked_date") == date_str:
                logger.debug(f"Item #{item_id}: già prenotato per {date_str}")
                continue

            # Non prenotare per oggi se è già passato l'orario
            if check_date.date() == today.date():
                try:
                    h, m = map(int, start_time.split(":"))
                    lesson_dt = today.replace(hour=h, minute=m)
                    if now_rome > lesson_dt + timedelta(minutes=5):
                        continue
                except ValueError:
                    pass

            # Recupera la schedule (con retry su token scaduto)
            success, items = self._get_schedule_with_refresh(
                auth_token, item, date_str, date_str, company_id
            )

            if not success or not items:
                continue

            # Cerca la lezione
            for lesson in items:
                if lesson.get("IDServizio") != service_id:
                    continue
                les_start = lesson.get("StartTime", "")[11:16] if len(lesson.get("StartTime", "")) > 16 else lesson.get("StartTime", "")
                if les_start != start_time:
                    continue
                if instructor and instructor.lower() not in lesson.get("AdditionalInfo", "").lower():
                    continue

                # Trovata!
                if lesson.get("IsUserPresent"):
                    # Già prenotato
                    db.update_auto_book_last_booked(item_id, lesson.get("IDLesson"), date_str)
                    logger.info(f"Item #{item_id}: già prenotato per {date_str}")
                    return  # Fatto per questa settimana

                if lesson.get("AvailablePlaces", 1) == 0:
                    logger.info(f"Item #{item_id}: {date_str} — posti esauriti")
                    continue

                target_lesson = lesson
                target_date = date_str
                break

            if target_lesson:
                break

        if not target_lesson:
            logger.debug(f"Item #{item_id}: nessuna lezione trovata nei prossimi 14 giorni")
            return

        # PRENOTA!
        lesson = target_lesson
        lesson_id = lesson["IDLesson"]
        date = lesson["DateLesson"][:10]
        bs = lesson["StartTime"]
        bs = bs[:19] if len(bs) > 19 else f"{date}T{bs}:00"
        be = lesson["EndTime"]
        be = be[:19] if len(be) > 19 else f"{date}T{be}:00"

        ok, msg = self._book_with_refresh(
            auth_token, item, lesson_id, service_id, bs, be
        )

        if ok:
            logger.info(f"✅ AUTO-BOOK #{item_id}: {item['description']} il {date} alle {start_time}")
            db.update_auto_book_last_booked(item_id, lesson_id, date)
            db.log_booking(telegram_id, item["description"], lesson_id, bs, "autobook", True, msg)
        else:
            logger.warning(f"❌ AUTO-BOOK #{item_id} FALLITO: {item['description']}: {msg}")
            db.log_booking(telegram_id, item["description"], lesson_id, bs, "autobook", False, msg)

    def _get_schedule_with_refresh(self, auth_token: str, item: Dict,
                                    start_date: str, end_date: str,
                                    company_id: int) -> tuple:
        """
        Chiama get_schedule con retry se il token è scaduto.
        """
        iyes_url = item.get("iyes_url", "") or config.WELLTEAM_IYES_URL

        success, result = wellteam.get_schedule(
            auth_token=auth_token,
            app_token=config.WELLTEAM_APP_TOKEN,
            iyes_url=iyes_url,
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
        )

        if success:
            return success, result

        # Fallimento — potrebbe essere token scaduto
        logger.info(f"Item #{item['id']}: get_schedule fallito, tentativo refresh token...")
        new_token = self._refresh_token(item)
        if new_token:
            # Retry con token nuovo
            return wellteam.get_schedule(
                auth_token=new_token,
                app_token=config.WELLTEAM_APP_TOKEN,
                iyes_url=iyes_url,
                start_date=start_date,
                end_date=end_date,
                company_id=company_id,
            )

        return False, result

    def _book_with_refresh(self, auth_token: str, item: Dict,
                            lesson_id: int, service_id: int,
                            start_time: str, end_time: str) -> tuple:
        """
        Chiama book_course con retry se il token è scaduto.
        """
        iyes_url = item.get("iyes_url", "") or config.WELLTEAM_IYES_URL

        ok, msg = wellteam.book_course(
            auth_token=auth_token,
            app_token=config.WELLTEAM_APP_TOKEN,
            iyes_url=iyes_url,
            lesson_id=lesson_id,
            service_id=service_id,
            start_time=start_time,
            end_time=end_time,
        )

        if ok:
            return ok, msg

        # Fallimento — potrebbe essere token scaduto
        logger.info(f"Item #{item['id']}: book_course fallito, tentativo refresh token...")
        new_token = self._refresh_token(item)
        if new_token:
            # Retry con token nuovo
            return wellteam.book_course(
                auth_token=new_token,
                app_token=config.WELLTEAM_APP_TOKEN,
                iyes_url=iyes_url,
                lesson_id=lesson_id,
                service_id=service_id,
                start_time=start_time,
                end_time=end_time,
            )

        return False, msg
