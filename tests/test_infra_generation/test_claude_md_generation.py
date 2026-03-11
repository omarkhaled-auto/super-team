"""Tests for CLAUDE.md generation (_write_builder_claude_md).

Verifies that builder CLAUDE.md files contain framework-specific
instructions for Python, NestJS, and frontend services.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.super_orchestrator.pipeline import (
    _STACK_INSTRUCTIONS,
    _detect_stack_category,
    _write_builder_claude_md,
)


class TestDetectStackCategory:
    """Test _detect_stack_category function."""

    def test_python_fastapi(self):
        assert _detect_stack_category({"language": "python", "framework": "fastapi"}) == "python"

    def test_typescript_nestjs(self):
        assert _detect_stack_category({"language": "typescript", "framework": "nestjs"}) == "typescript"

    def test_angular_is_frontend(self):
        assert _detect_stack_category({"language": "typescript", "framework": "angular"}) == "frontend"

    def test_react_is_frontend(self):
        assert _detect_stack_category({"language": "typescript", "framework": "react"}) == "frontend"

    def test_none_defaults_to_python(self):
        assert _detect_stack_category(None) == "python"

    def test_empty_dict_defaults_to_python(self):
        assert _detect_stack_category({}) == "python"

    def test_string_defaults_to_python(self):
        assert _detect_stack_category("python") == "python"


class TestStackInstructions:
    """Test _STACK_INSTRUCTIONS dict content."""

    def test_python_instructions_mention_asyncpg(self):
        """Python instructions mention postgresql+asyncpg://."""
        assert "asyncpg" in _STACK_INSTRUCTIONS["python"]

    def test_python_instructions_mention_alembic_ini(self):
        """Python instructions mention creating alembic.ini."""
        assert "alembic.ini" in _STACK_INSTRUCTIONS["python"]

    def test_python_instructions_list_requirements(self):
        """Python instructions list all required pip packages."""
        python_inst = _STACK_INSTRUCTIONS["python"]
        for pkg in ["fastapi", "uvicorn", "sqlalchemy", "asyncpg", "alembic", "pydantic"]:
            assert pkg in python_inst, f"Missing {pkg} in Python instructions"

    def test_nestjs_instructions_mention_auth_module_di(self):
        """NestJS instructions mention AuthModule import for JwtAuthGuard."""
        ts_inst = _STACK_INSTRUCTIONS["typescript"]
        assert "AuthModule" in ts_inst
        assert "JwtAuthGuard" in ts_inst

    def test_nestjs_instructions_mention_port_8080(self):
        """NestJS instructions specify port 8080, not 3000."""
        ts_inst = _STACK_INSTRUCTIONS["typescript"]
        assert "8080" in ts_inst

    def test_nestjs_instructions_mention_individual_db_vars(self):
        """NestJS instructions mention DB_HOST, DB_PORT, etc."""
        ts_inst = _STACK_INSTRUCTIONS["typescript"]
        assert "DB_HOST" in ts_inst
        assert "DB_PORT" in ts_inst

    def test_frontend_instructions_mention_dockerfile(self):
        """Frontend instructions mandate Dockerfile creation."""
        fe_inst = _STACK_INSTRUCTIONS["frontend"]
        assert "Dockerfile" in fe_inst


class TestWriteBuilderClaudeMd:
    """Test _write_builder_claude_md output."""

    def test_python_backend_claude_md(self, tmp_path: Path):
        """Python backend CLAUDE.md contains correct instructions."""
        builder_config = {
            "service_id": "auth-service",
            "domain": "authentication",
            "stack": {"language": "python", "framework": "fastapi", "database": "PostgreSQL"},
            "port": 8000,
        }
        md_path = _write_builder_claude_md(tmp_path, builder_config)

        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "auth-service" in content
        assert "python" in content.lower()
        assert "Dockerfile" in content

    def test_nestjs_backend_claude_md(self, tmp_path: Path):
        """NestJS backend CLAUDE.md contains correct instructions."""
        builder_config = {
            "service_id": "accounts-service",
            "domain": "accounts",
            "stack": {"language": "typescript", "framework": "nestjs", "database": "PostgreSQL"},
            "port": 8080,
        }
        md_path = _write_builder_claude_md(tmp_path, builder_config)

        content = md_path.read_text(encoding="utf-8")
        assert "accounts-service" in content
        assert "NestJS" in content or "nestjs" in content.lower()
        assert "DB_HOST" in content

    def test_frontend_claude_md(self, tmp_path: Path):
        """Frontend CLAUDE.md contains frontend-specific instructions."""
        builder_config = {
            "service_id": "frontend",
            "domain": "ui",
            "stack": {"language": "typescript", "framework": "angular"},
            "port": 80,
            "is_frontend": True,
        }
        md_path = _write_builder_claude_md(tmp_path, builder_config)

        content = md_path.read_text(encoding="utf-8")
        assert "FRONTEND" in content
        assert "Dockerfile" in content
        assert "database" not in content.lower() or "NOT create database" in content

    def test_universal_requirements_include_dockerfile(self, tmp_path: Path):
        """Universal mandatory deliverables include Dockerfile."""
        builder_config = {
            "service_id": "auth-service",
            "domain": "auth",
            "stack": {"language": "python", "framework": "fastapi"},
            "port": 8000,
        }
        md_path = _write_builder_claude_md(tmp_path, builder_config)
        content = md_path.read_text(encoding="utf-8")
        assert "Dockerfile" in content
        assert "Mandatory Deliverables" in content

    def test_universal_requirements_include_health_endpoint(self, tmp_path: Path):
        """Universal deliverables include health endpoint."""
        builder_config = {
            "service_id": "auth-service",
            "domain": "auth",
            "stack": {"language": "python", "framework": "fastapi"},
            "port": 8000,
        }
        md_path = _write_builder_claude_md(tmp_path, builder_config)
        content = md_path.read_text(encoding="utf-8")
        assert "Health endpoint" in content or "health" in content.lower()

    def test_universal_requirements_include_dockerignore(self, tmp_path: Path):
        """Universal deliverables include .dockerignore."""
        builder_config = {
            "service_id": "auth-service",
            "domain": "auth",
            "stack": {"language": "python", "framework": "fastapi"},
            "port": 8000,
        }
        md_path = _write_builder_claude_md(tmp_path, builder_config)
        content = md_path.read_text(encoding="utf-8")
        assert ".dockerignore" in content

    def test_entities_included_in_claude_md(self, tmp_path: Path):
        """Owned entities appear in CLAUDE.md."""
        builder_config = {
            "service_id": "invoicing-service",
            "domain": "invoicing",
            "stack": {"language": "python", "framework": "fastapi"},
            "port": 8000,
            "entities": [
                {"name": "Invoice", "description": "An invoice", "fields": [
                    {"name": "id", "type": "uuid", "required": True},
                    {"name": "amount", "type": "decimal", "required": True},
                ]},
            ],
        }
        md_path = _write_builder_claude_md(tmp_path, builder_config)
        content = md_path.read_text(encoding="utf-8")
        assert "Invoice" in content
        assert "amount" in content

    def test_state_machines_included_in_claude_md(self, tmp_path: Path):
        """State machines appear in CLAUDE.md."""
        builder_config = {
            "service_id": "invoicing-service",
            "domain": "invoicing",
            "stack": {"language": "python", "framework": "fastapi"},
            "port": 8000,
            "state_machines": [
                {
                    "entity": "Invoice",
                    "states": ["draft", "sent", "paid"],
                    "initial_state": "draft",
                    "transitions": [
                        {"from_state": "draft", "to_state": "sent", "trigger": "send"},
                    ],
                },
            ],
        }
        md_path = _write_builder_claude_md(tmp_path, builder_config)
        content = md_path.read_text(encoding="utf-8")
        assert "State Machine" in content
        assert "draft" in content
        assert "sent" in content

    def test_claude_md_written_to_dot_claude_dir(self, tmp_path: Path):
        """CLAUDE.md is written inside .claude/ subdirectory."""
        builder_config = {
            "service_id": "auth-service",
            "domain": "auth",
            "stack": {"language": "python", "framework": "fastapi"},
            "port": 8000,
        }
        md_path = _write_builder_claude_md(tmp_path, builder_config)
        assert ".claude" in str(md_path)
        assert md_path.name == "CLAUDE.md"
