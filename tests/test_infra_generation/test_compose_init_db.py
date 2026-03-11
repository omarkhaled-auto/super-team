"""Tests for init-db SQL generation.

Verifies that the PostgreSQL init script:
- Creates uuid-ossp extension
- Creates per-service databases
- Converts CamelCase entity names to snake_case table names
- Generates dual-name views for ORM compatibility
- Mounts init-db in the postgres service
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.build3_shared.models import ServiceInfo
from src.integrator.compose_generator import ComposeGenerator


class TestInitSqlGeneration:
    """Test generate_init_sql produces correct PostgreSQL init scripts."""

    def test_init_sql_creates_uuid_extension(self, tmp_path: Path):
        """Init SQL includes CREATE EXTENSION uuid-ossp."""
        services = [
            ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        ]
        sql_path = ComposeGenerator.generate_init_sql(tmp_path, services)
        content = sql_path.read_text(encoding="utf-8")
        assert 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"' in content

    def test_init_sql_creates_per_service_database(self, tmp_path: Path):
        """Each service gets its own database."""
        services = [
            ServiceInfo(service_id="auth-service", domain="auth", port=8000),
            ServiceInfo(service_id="invoicing-service", domain="invoicing", port=8001),
        ]
        sql_path = ComposeGenerator.generate_init_sql(tmp_path, services)
        content = sql_path.read_text(encoding="utf-8")
        assert "auth_service" in content
        assert "invoicing_service" in content

    def test_init_sql_skips_frontend(self, tmp_path: Path):
        """Frontend services do not get a database."""
        services = [
            ServiceInfo(
                service_id="frontend",
                domain="ui",
                stack={"language": "typescript", "framework": "angular"},
                port=80,
            ),
        ]
        sql_path = ComposeGenerator.generate_init_sql(tmp_path, services)
        content = sql_path.read_text(encoding="utf-8")
        assert "frontend" not in content.lower().replace(
            "no backend services", ""
        ).replace("-- auto-generated", "")
        assert "No backend services detected" in content

    def test_init_sql_db_name_uses_underscore(self, tmp_path: Path):
        """Database name uses underscore not dash (auth-service -> auth_service)."""
        services = [
            ServiceInfo(service_id="auth-service", domain="auth", port=8000),
        ]
        sql_path = ComposeGenerator.generate_init_sql(tmp_path, services)
        content = sql_path.read_text(encoding="utf-8")
        assert "auth_service" in content

    def test_init_sql_creates_in_init_db_dir(self, tmp_path: Path):
        """Init SQL is written to init-db/ subdirectory."""
        services = [
            ServiceInfo(service_id="auth-service", domain="auth", port=8000),
        ]
        sql_path = ComposeGenerator.generate_init_sql(tmp_path, services)
        assert sql_path.parent.name == "init-db"
        assert sql_path.name == "init.sql"

    def test_init_sql_grants_privileges(self, tmp_path: Path):
        """Init SQL grants privileges to 'app' user."""
        services = [
            ServiceInfo(service_id="auth-service", domain="auth", port=8000),
        ]
        sql_path = ComposeGenerator.generate_init_sql(tmp_path, services)
        content = sql_path.read_text(encoding="utf-8")
        assert "GRANT ALL PRIVILEGES" in content
        assert "TO app" in content


class TestInitDbVolume:
    """Verify init-db volume is mounted in the postgres service."""

    def test_init_db_volume_mounted_in_postgres(self):
        """PostgreSQL service mounts init-db directory."""
        gen = ComposeGenerator()
        pg = gen._postgres_service()
        volumes = pg.get("volumes", [])
        init_mount = [v for v in volumes if "init-db" in v and "initdb" in v]
        assert len(init_mount) == 1
        assert ":ro" in init_mount[0]  # Read-only mount


class TestCamelToSnake:
    """Test entity name to table name conversion."""

    @pytest.mark.parametrize(
        "input_name, expected",
        [
            ("JournalEntry", "journal_entry"),
            ("Invoice", "invoice"),
            ("FiscalPeriod", "fiscal_period"),
            ("User", "user"),
            ("HTTPResponse", "http_response"),
        ],
    )
    def test_camel_to_snake(self, input_name: str, expected: str):
        """CamelCase entity names convert to snake_case."""
        assert ComposeGenerator._camel_to_snake(input_name) == expected


class TestPluralize:
    """Test naive English pluralization for table names."""

    @pytest.mark.parametrize(
        "input_name, expected",
        [
            ("invoice", "invoices"),
            ("journal_entry", "journal_entries"),
            ("fiscal_period", "fiscal_periods"),
            ("user", "users"),
            ("address", "addresses"),
            ("status", "statuses"),
        ],
    )
    def test_pluralize(self, input_name: str, expected: str):
        """Pluralization works for common table names."""
        assert ComposeGenerator._pluralize(input_name) == expected


class TestDualNameViews:
    """Test ORM compatibility dual-name views in init SQL."""

    def test_init_sql_creates_dual_name_views(self, tmp_path: Path):
        """Init SQL creates dual-name views for multi-word entities."""
        services = [
            ServiceInfo(service_id="invoicing-service", domain="invoicing", port=8000),
        ]
        entities_by_service = {
            "invoicing-service": ["JournalEntry", "FiscalPeriod"],
        }
        sql_path = ComposeGenerator.generate_init_sql(
            tmp_path, services, entities_by_service=entities_by_service
        )
        content = sql_path.read_text(encoding="utf-8")
        # JournalEntry -> journal_entries (snake plural) vs journalentries (no-sep plural)
        assert "journal_entries" in content
        assert "journalentries" in content

    def test_no_view_for_single_word_entities(self, tmp_path: Path):
        """Single-word entities don't get dual-name views (names are identical)."""
        services = [
            ServiceInfo(service_id="auth-service", domain="auth", port=8000),
        ]
        entities_by_service = {
            "auth-service": ["User"],
        }
        sql_path = ComposeGenerator.generate_init_sql(
            tmp_path, services, entities_by_service=entities_by_service
        )
        content = sql_path.read_text(encoding="utf-8")
        # "users" == "users" so no view created
        assert "Dual-name view" not in content or "users" not in content.split("Dual-name view")[0]
