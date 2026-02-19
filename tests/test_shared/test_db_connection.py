"""Tests for the SQLite ConnectionPool."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from src.shared.db.connection import ConnectionPool


class TestConnectionPool:
    def test_get_returns_connection(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db")
        conn = pool.get()
        assert isinstance(conn, sqlite3.Connection)
        pool.close()

    def test_wal_mode_enabled(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db")
        conn = pool.get()
        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"
        pool.close()

    def test_busy_timeout_set(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db")
        conn = pool.get()
        result = conn.execute("PRAGMA busy_timeout").fetchone()
        assert result[0] == 30000
        pool.close()

    def test_foreign_keys_enabled(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db")
        conn = pool.get()
        result = conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1
        pool.close()

    def test_row_factory_set(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db")
        conn = pool.get()
        assert conn.row_factory == sqlite3.Row
        pool.close()

    def test_connection_reuse_same_thread(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db")
        conn1 = pool.get()
        conn2 = pool.get()
        assert conn1 is conn2
        pool.close()

    def test_thread_local_isolation(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db")
        main_conn = pool.get()
        thread_conn = [None]

        def get_conn():
            thread_conn[0] = pool.get()

        t = threading.Thread(target=get_conn)
        t.start()
        t.join()

        assert thread_conn[0] is not None
        assert thread_conn[0] is not main_conn
        pool.close()

    def test_close_clears_connections(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db")
        pool.get()
        pool.close()
        assert len(pool._connections) == 0

    def test_db_path_property(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        pool = ConnectionPool(db_path)
        assert pool.db_path == db_path
        pool.close()

    def test_parent_directory_created(self, tmp_path: Path):
        nested_path = tmp_path / "nested" / "dir" / "test.db"
        pool = ConnectionPool(nested_path)
        assert nested_path.parent.exists()
        pool.close()

    def test_custom_timeout(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db", timeout=60.0)
        conn = pool.get()
        assert isinstance(conn, sqlite3.Connection)
        pool.close()

    def test_foreign_key_enforcement(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "test.db")
        conn = pool.get()
        conn.execute("CREATE TABLE parent (id TEXT PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE child (id TEXT PRIMARY KEY, parent_id TEXT REFERENCES parent(id))"
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO child VALUES ('c1', 'nonexistent')")
            conn.commit()
        pool.close()
