"""SQLite connection pool with thread-local storage and WAL mode."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from src.shared.constants import DB_BUSY_TIMEOUT_MS


class ConnectionPool:
    """Thread-local SQLite connection pool with WAL mode.

    Each thread gets its own connection. Connections are configured with:
    - WAL journal mode for concurrent read/write
    - busy_timeout=30000 (30 seconds)
    - foreign_keys=ON
    - Row factory for dict-like access
    """

    def __init__(self, db_path: str | Path, timeout: float = 30.0) -> None:
        self._db_path = Path(db_path)
        self._timeout = timeout
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: list[sqlite3.Connection] = []

        # Ensure parent directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def get(self) -> sqlite3.Connection:
        """Get a thread-local database connection.

        Returns the existing connection for the current thread,
        or creates a new one if none exists.
        """
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            return conn

        conn = sqlite3.connect(
            str(self._db_path),
            timeout=self._timeout,
        )
        # Configure WAL mode and pragmas
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

        self._local.connection = conn

        with self._lock:
            self._connections.append(conn)

        return conn

    def close(self) -> None:
        """Close all connections in the pool."""
        with self._lock:
            for conn in self._connections:
                try:
                    conn.close()
                except (sqlite3.Error, OSError):
                    pass
            self._connections.clear()
        # Clear thread-local
        self._local.connection = None

    @property
    def db_path(self) -> Path:
        """Return the database file path."""
        return self._db_path
