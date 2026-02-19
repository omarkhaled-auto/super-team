"""Tests for database schema initialization."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_architect_db, init_contracts_db, init_symbols_db


def get_tables(conn) -> list[str]:
    """Get all table names from a database connection."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def get_indexes(conn) -> list[str]:
    """Get all index names from a database connection."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


class TestInitArchitectDb:
    def test_creates_service_maps_table(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "architect.db")
        init_architect_db(pool)
        tables = get_tables(pool.get())
        assert "service_maps" in tables
        pool.close()

    def test_creates_domain_models_table(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "architect.db")
        init_architect_db(pool)
        tables = get_tables(pool.get())
        assert "domain_models" in tables
        pool.close()

    def test_creates_decomposition_runs_table(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "architect.db")
        init_architect_db(pool)
        tables = get_tables(pool.get())
        assert "decomposition_runs" in tables
        pool.close()

    def test_creates_indexes(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "architect.db")
        init_architect_db(pool)
        indexes = get_indexes(pool.get())
        assert "idx_smap_project" in indexes
        assert "idx_smap_prd" in indexes
        assert "idx_dmodel_project" in indexes
        pool.close()

    def test_status_check_constraint(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "architect.db")
        init_architect_db(pool)
        conn = pool.get()
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO decomposition_runs (id, prd_content_hash, status) VALUES (?, ?, ?)",
                ("id1", "hash1", "invalid_status"),
            )
            conn.commit()
        pool.close()

    def test_idempotent(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "architect.db")
        init_architect_db(pool)
        init_architect_db(pool)  # Should not raise
        tables = get_tables(pool.get())
        assert "service_maps" in tables
        pool.close()


class TestInitContractsDb:
    def test_creates_all_tables(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "contracts.db")
        init_contracts_db(pool)
        tables = get_tables(pool.get())
        expected = [
            "build_cycles", "contracts", "contract_versions",
            "breaking_changes", "implementations", "test_suites",
            "shared_schemas", "schema_consumers",
        ]
        for table in expected:
            assert table in tables, f"Missing table: {table}"
        pool.close()

    def test_creates_indexes(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "contracts.db")
        init_contracts_db(pool)
        indexes = get_indexes(pool.get())
        expected_indexes = [
            "idx_build_cycles_status",
            "idx_contracts_service",
            "idx_contracts_type",
            "idx_contracts_status",
            "idx_contracts_build",
            "idx_contracts_hash",
            "idx_versions_contract",
            "idx_versions_build",
            "idx_breaking_version",
            "idx_impl_contract",
            "idx_impl_service",
            "idx_impl_status",
            "idx_tests_contract",
        ]
        for idx in expected_indexes:
            assert idx in indexes, f"Missing index: {idx}"
        pool.close()

    def test_contract_type_check_constraint(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "contracts.db")
        init_contracts_db(pool)
        conn = pool.get()
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO contracts (id, type, version, service_name, spec_json, spec_hash) VALUES (?, ?, ?, ?, ?, ?)",
                ("id1", "graphql", "1.0.0", "svc", "{}", "hash"),
            )
            conn.commit()
        pool.close()

    def test_unique_service_type_version(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "contracts.db")
        init_contracts_db(pool)
        conn = pool.get()
        conn.execute(
            "INSERT INTO contracts (id, type, version, service_name, spec_json, spec_hash) VALUES (?, ?, ?, ?, ?, ?)",
            ("id1", "openapi", "1.0.0", "svc", "{}", "hash1"),
        )
        conn.commit()
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO contracts (id, type, version, service_name, spec_json, spec_hash) VALUES (?, ?, ?, ?, ?, ?)",
                ("id2", "openapi", "1.0.0", "svc", "{}", "hash2"),
            )
            conn.commit()
        pool.close()

    def test_idempotent(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "contracts.db")
        init_contracts_db(pool)
        init_contracts_db(pool)
        tables = get_tables(pool.get())
        assert "contracts" in tables
        pool.close()


class TestInitSymbolsDb:
    def test_creates_all_tables(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "symbols.db")
        init_symbols_db(pool)
        tables = get_tables(pool.get())
        expected = [
            "indexed_files", "symbols", "dependency_edges",
            "import_references", "graph_snapshots",
        ]
        for table in expected:
            assert table in tables, f"Missing table: {table}"
        pool.close()

    def test_creates_indexes(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "symbols.db")
        init_symbols_db(pool)
        indexes = get_indexes(pool.get())
        expected_indexes = [
            "idx_files_service",
            "idx_files_language",
            "idx_files_hash",
            "idx_symbols_file",
            "idx_symbols_name",
            "idx_symbols_kind",
            "idx_symbols_service",
            "idx_symbols_language",
            "idx_symbols_parent",
            "idx_deps_source",
            "idx_deps_target",
            "idx_deps_source_file",
            "idx_deps_target_file",
            "idx_deps_relation",
            "idx_imports_source",
            "idx_imports_target",
        ]
        for idx in expected_indexes:
            assert idx in indexes, f"Missing index: {idx}"
        pool.close()

    def test_language_check_constraint(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "symbols.db")
        init_symbols_db(pool)
        conn = pool.get()
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO indexed_files (file_path, language, file_hash) VALUES (?, ?, ?)",
                ("test.rb", "ruby", "hash1"),
            )
            conn.commit()
        pool.close()

    def test_symbol_kind_check_constraint(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "symbols.db")
        init_symbols_db(pool)
        conn = pool.get()
        # First insert an indexed_file so foreign key is satisfied
        conn.execute(
            "INSERT INTO indexed_files (file_path, language, file_hash) VALUES (?, ?, ?)",
            ("test.py", "python", "hash1"),
        )
        conn.commit()
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO symbols (id, file_path, symbol_name, kind, language, line_start, line_end) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("id1", "test.py", "func", "invalid_kind", "python", 1, 10),
            )
            conn.commit()
        pool.close()

    def test_idempotent(self, tmp_path: Path):
        pool = ConnectionPool(tmp_path / "symbols.db")
        init_symbols_db(pool)
        init_symbols_db(pool)
        tables = get_tables(pool.get())
        assert "symbols" in tables
        pool.close()
