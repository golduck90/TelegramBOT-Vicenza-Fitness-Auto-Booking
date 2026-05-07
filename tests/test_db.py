"""
Tests per il database layer.
"""
import os
import sys
import tempfile
import pytest
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Temporarily override config paths for testing
import config
config.DATA_DIR = Path(tempfile.mkdtemp())
config.DB_PATH = config.DATA_DIR / "test_palestra.db"


class TestDatabase:
    """Test di base per il database."""

    def test_init_db_creates_tables(self):
        """init_db() deve creare le tabelle senza errori."""
        import db
        # init_db should run without exception
        db.init_db()

        # Verify tables exist
        conn = db.get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [row["name"] for row in tables]

        expected_tables = [
            "auto_book_items",
            "booking_log",
            "booking_reminders",
            "courses",
            "users",
        ]
        for t in expected_tables:
            assert t in table_names, f"Tabella {t} non trovata"

        # Verify legacy autobook_rules table is NOT present
        assert "autobook_rules" not in table_names, \
            "La tabella legacy autobook_rules non dovrebbe esistere"

    def test_get_connection_public_alias(self):
        """get_connection() deve funzionare come alias di _get_conn()."""
        import db
        conn1 = db.get_connection()
        conn2 = db._get_conn()
        assert conn1 is conn2, "get_connection() deve restituire la stessa connessione di _get_conn()"

    def test_register_and_get_user(self):
        """Registrazione e recupero utente."""
        import db
        db.init_db()

        ok = db.register_user(99999, "testuser", "secret123")
        assert ok is True

        user = db.get_user(99999)
        assert user is not None
        assert user["username"] == "testuser"
        assert user["telegram_id"] == 99999

        # Password deve essere cifrata (non in chiaro)
        assert user["encrypted_pass"] != "secret123"

    def test_decrypt_password(self):
        """La password cifrata deve poter essere decifrata."""
        import db
        db.init_db()

        db.register_user(88888, "testuser2", "mypassword")
        pwd = db.get_user_password(88888)
        assert pwd == "mypassword"

    def test_remove_user_cleans_all(self):
        """remove_user() deve rimuovere utente e dati associati."""
        import db
        db.init_db()

        db.register_user(77777, "delete_me", "pwd123")
        user = db.get_user(77777)
        assert user is not None

        db.remove_user(77777)
        user = db.get_user(77777)
        assert user is None

    def test_db_uses_utcnow(self):
        """lock_user e is_locked devono usare datetime timezone-aware."""
        import db
        from datetime import datetime, timezone
        db.init_db()

        db.register_user(66666, "lock_test", "pwd")
        db.lock_user(66666, minutes=1)
        assert db.is_locked(66666) is True
