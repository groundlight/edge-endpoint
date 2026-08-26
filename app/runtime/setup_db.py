"""Create the edge sqlite file if missing, and enable WAL."""

import os
import sqlite3
import sys
from pathlib import Path


def _database_paths() -> tuple[Path, Path]:
    """Return (directory, sqlite.db path), honoring SQLITE_DIR."""
    directory = Path(os.environ.get("SQLITE_DIR", "/opt/groundlight/edge/sqlite"))
    return directory, directory / "sqlite.db"


def ensure_database() -> None:
    """Create sqlite.db with WAL journaling when the file does not already exist.

    Raises if SQLite does not actually switch to WAL.
    """
    database_directory, database_path = _database_paths()
    if database_path.is_file():
        print("SQLite database file exists and is mounted correctly.")
        return

    print("SQLite database file doesn't exist or wasn't mounted correctly. Creating it now...")
    database_directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS test_table (id INTEGER);")
        connection.execute("DROP TABLE IF EXISTS test_table;")
        mode = connection.execute("PRAGMA journal_mode=WAL;").fetchone()
        if not mode or mode[0].lower() != "wal":
            raise RuntimeError(f"failed to enable WAL journaling (got {mode!r})")
        connection.commit()
    finally:
        connection.close()


def main() -> int:
    """Initialize the edge sqlite database for the database-prep init container."""
    ensure_database()
    return 0


if __name__ == "__main__":
    sys.exit(main())
