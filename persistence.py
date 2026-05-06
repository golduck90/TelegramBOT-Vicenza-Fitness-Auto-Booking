"""
SQLite-based persistence for python-telegram-bot.

Stores user_data, chat_data, callback_data, bot_data, and conversations
in a single SQLite table `bot_persistence` inside the main `palestra.db`.

Replaces PicklePersistence with the same serialization format (pickle),
but backed by SQLite instead of a file.
"""
import pickle
import logging
from typing import Optional, Dict, Any
from telegram.ext import BasePersistence, PersistenceInput

import db

logger = logging.getLogger("bot")


class SqlitePersistence(BasePersistence):
    """
    Persistence backend that stores bot/user/chat/callback data in SQLite.

    Uses the same `_get_conn()` from db.py for thread-safe access.
    Data types are stored as single rows in `bot_persistence` table:
      key="user_data"      → value=<pickled dict of user_id → data>
      key="chat_data"      → value=<pickled dict of chat_id → data>
      key="callback_data"  → value=<pickled callback data dict>
      key="bot_data"       → value=<pickled bot data dict>
      key="conversations:{name}" → value=<pickled conversation dict>
    """

    def __init__(self, store_data: Optional[PersistenceInput] = None,
                 update_interval: int = 60):
        super().__init__(store_data=store_data or PersistenceInput(
            user_data=True, chat_data=True, bot_data=False, callback_data=True
        ))
        self._update_interval = update_interval

    @property
    def update_interval(self) -> int:
        return self._update_interval

    def get_connection(self):
        """Get a database connection from db module."""
        return db._get_conn()

    def _load_blob(self, key: str):
        """Load a pickled blob from the bot_persistence table, return unpickled value or empty dict."""
        conn = self.get_connection()
        row = conn.execute(
            "SELECT value FROM bot_persistence WHERE key = ?", (key,)
        ).fetchone()
        if row:
            try:
                return pickle.loads(row["value"])
            except Exception as e:
                logger.warning(f"Errore unpickling {key}: {e}")
                return {}
        return {}

    def _save_blob(self, key: str, data: dict):
        """Save a dict as pickled blob to the bot_persistence table."""
        conn = self.get_connection()
        blob = pickle.dumps(data)
        conn.execute(
            "INSERT OR REPLACE INTO bot_persistence (key, value) VALUES (?, ?)",
            (key, blob)
        )
        conn.commit()

    # ── Getter methods (load from DB) ──────────────────────────────

    async def get_user_data(self) -> Dict[int, Any]:
        """Load user_data from DB. Returns dict with int keys."""
        return self._load_blob("user_data")

    async def get_chat_data(self) -> Dict[int, Any]:
        """Load chat_data from DB. Returns dict with int keys."""
        return self._load_blob("chat_data")

    async def get_bot_data(self) -> Dict[int, Any]:
        """Load bot_data from DB."""
        return self._load_blob("bot_data")

    async def get_callback_data(self) -> Dict[int, Any]:
        """Load callback_data from DB."""
        return self._load_blob("callback_data")

    async def get_conversations(self, name: str) -> Dict:
        """Load conversations for a given handler name."""
        return self._load_blob(f"conversations:{name}")

    # ── Updater methods (save to DB) ─────────────────────────────

    async def update_user_data(self, user_id: int, data: dict) -> None:
        """Update user_data for a specific user."""
        user_data = self._load_blob("user_data")
        user_data[user_id] = data
        self._save_blob("user_data", user_data)

    async def update_chat_data(self, chat_id: int, data: dict) -> None:
        """Update chat_data for a specific chat."""
        chat_data = self._load_blob("chat_data")
        chat_data[chat_id] = data
        self._save_blob("chat_data", chat_data)

    async def update_bot_data(self, data: dict) -> None:
        """Update bot_data."""
        self._save_blob("bot_data", data)

    async def update_callback_data(self, data: dict) -> None:
        """Update callback_data."""
        self._save_blob("callback_data", data)

    async def update_conversation(self, name: str, key: tuple, new_state: object) -> None:
        """Update conversation state for a handler."""
        conv = self._load_blob(f"conversations:{name}")
        conv[key] = new_state
        self._save_blob(f"conversations:{name}", conv)

    # ── Refresh methods (no-op, data always up to date in DB) ────
    # PTB v20.7+ calls these with keyword args (full dicts)

    async def refresh_user_data(self, user_id: int, user_data: dict) -> None:
        """No-op: data is always up to date in DB."""
        pass

    async def refresh_chat_data(self, chat_id: int, chat_data: dict) -> None:
        """No-op: data is always up to date in DB."""
        pass

    async def refresh_bot_data(self, bot_data: dict) -> None:
        """No-op: data is always up to date in DB."""
        pass

    async def drop_user_data(self, user_id: int) -> None:
        """Remove a user's data from the persistence store."""
        user_data = self._load_blob("user_data")
        user_data.pop(user_id, None)
        self._save_blob("user_data", user_data)

    async def drop_chat_data(self, chat_id: int) -> None:
        """Remove a chat's data from the persistence store."""
        chat_data = self._load_blob("chat_data")
        chat_data.pop(chat_id, None)
        self._save_blob("chat_data", chat_data)

    async def flush(self) -> None:
        """No-op: data is persisted on every update."""
        pass
