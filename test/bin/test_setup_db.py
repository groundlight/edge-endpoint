"""Tests for database-prep sqlite initialization."""

import sqlite3
from pathlib import Path

from app.runtime.setup_db import ensure_database


def test_creates_wal_database(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SQLITE_DIR", str(tmp_path))
    ensure_database()
    db = tmp_path / "sqlite.db"
    assert db.is_file()
    assert db.stat().st_size > 0
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA journal_mode;").fetchone()[0] == "wal"
    ensure_database()
    assert db.is_file()
