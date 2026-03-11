"""Tests for pre-deploy validation and requirements enrichment.

Verifies:
- _pre_deploy_validate catches missing files per stack
- _enrich_requirements_txt adds missing deps without duplicating existing
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.build3_shared.models import ServiceInfo
from src.super_orchestrator.pipeline import (
    _enrich_requirements_txt,
    _pre_deploy_validate,
)


class TestPreDeployValidation:
    """Test _pre_deploy_validate catches deployment issues."""

    def test_catches_missing_dockerfile(self, tmp_path: Path):
        """Validation catches service with no Dockerfile."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        # Create requirements.txt and main.py but NO Dockerfile
        (service_dir / "requirements.txt").write_text("fastapi\nuvicorn\nsqlalchemy\n")
        (service_dir / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")

        services = [
            ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        assert any("Dockerfile" in issue for issue in issues)

    def test_catches_missing_requirements_txt(self, tmp_path: Path):
        """Validation catches Python service with no requirements.txt."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        (service_dir / "Dockerfile").write_text("FROM python:3.12-slim\n")
        (service_dir / "main.py").write_text("app = None\n")

        services = [
            ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        assert any("requirements.txt" in issue for issue in issues)

    def test_catches_missing_package_json(self, tmp_path: Path):
        """Validation catches Node service with no package.json."""
        service_dir = tmp_path / "accounts-service"
        service_dir.mkdir()
        (service_dir / "Dockerfile").write_text("FROM node:20-slim\n")
        (service_dir / "tsconfig.json").write_text("{}\n")

        services = [
            ServiceInfo(
                service_id="accounts-service",
                domain="accounts",
                stack={"language": "typescript", "framework": "nestjs"},
                port=8080,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        assert any("package.json" in issue for issue in issues)

    def test_catches_missing_build_script(self, tmp_path: Path):
        """Validation catches package.json without build script."""
        service_dir = tmp_path / "accounts-service"
        service_dir.mkdir()
        (service_dir / "Dockerfile").write_text("FROM node:20-slim\n")
        (service_dir / "tsconfig.json").write_text("{}\n")
        (service_dir / "package.json").write_text(json.dumps({
            "name": "accounts-service",
            "scripts": {"start": "node dist/main.js"},
        }))

        services = [
            ServiceInfo(
                service_id="accounts-service",
                domain="accounts",
                stack={"language": "typescript", "framework": "nestjs"},
                port=8080,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        assert any("build" in issue for issue in issues)

    def test_catches_missing_main_py(self, tmp_path: Path):
        """Validation catches Python service with no main.py."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        (service_dir / "Dockerfile").write_text("FROM python:3.12-slim\n")
        (service_dir / "requirements.txt").write_text("fastapi\nuvicorn\nsqlalchemy\n")

        services = [
            ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        assert any("main.py" in issue for issue in issues)

    def test_catches_missing_tsconfig(self, tmp_path: Path):
        """Validation catches TypeScript service with no tsconfig.json."""
        service_dir = tmp_path / "accounts-service"
        service_dir.mkdir()
        (service_dir / "Dockerfile").write_text("FROM node:20-slim\n")
        (service_dir / "package.json").write_text(json.dumps({
            "name": "accounts-service",
            "scripts": {"build": "nest build"},
        }))

        services = [
            ServiceInfo(
                service_id="accounts-service",
                domain="accounts",
                stack={"language": "typescript", "framework": "nestjs"},
                port=8080,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        assert any("tsconfig.json" in issue for issue in issues)

    def test_nonexistent_service_dir(self, tmp_path: Path):
        """Validation catches service directory that doesn't exist."""
        services = [
            ServiceInfo(
                service_id="missing-service",
                domain="missing",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        assert any("does not exist" in issue for issue in issues)

    def test_valid_python_service_no_issues(self, tmp_path: Path):
        """Fully valid Python service produces no issues."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        (service_dir / "Dockerfile").write_text("FROM python:3.12-slim\n")
        (service_dir / "requirements.txt").write_text("fastapi\nuvicorn\nsqlalchemy\n")
        (service_dir / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")

        services = [
            ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        assert issues == []

    def test_valid_typescript_service_no_issues(self, tmp_path: Path):
        """Fully valid TypeScript service produces no issues."""
        service_dir = tmp_path / "accounts-service"
        service_dir.mkdir()
        (service_dir / "Dockerfile").write_text("FROM node:20-slim\n")
        (service_dir / "tsconfig.json").write_text("{}\n")
        (service_dir / "package.json").write_text(json.dumps({
            "name": "accounts-service",
            "scripts": {"build": "nest build", "start": "node dist/main.js"},
        }))

        services = [
            ServiceInfo(
                service_id="accounts-service",
                domain="accounts",
                stack={"language": "typescript", "framework": "nestjs"},
                port=8080,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        assert issues == []

    def test_catches_requirements_missing_core_deps(self, tmp_path: Path):
        """Validation catches requirements.txt missing core dependencies."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        (service_dir / "Dockerfile").write_text("FROM python:3.12-slim\n")
        (service_dir / "requirements.txt").write_text("flask\n")  # Missing fastapi, uvicorn, sqlalchemy
        (service_dir / "main.py").write_text("app = None\n")

        services = [
            ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        ]

        issues = _pre_deploy_validate(tmp_path, services)
        # Should catch missing fastapi, uvicorn, sqlalchemy
        assert any("fastapi" in issue for issue in issues)
        assert any("uvicorn" in issue for issue in issues)
        assert any("sqlalchemy" in issue for issue in issues)


class TestEnrichRequirementsTxt:
    """Test _enrich_requirements_txt adds missing deps."""

    def test_adds_missing_deps(self, tmp_path: Path):
        """_enrich_requirements_txt adds missing packages."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        req_file = service_dir / "requirements.txt"
        req_file.write_text("flask\n")

        _enrich_requirements_txt(service_dir, "auth-service")

        content = req_file.read_text(encoding="utf-8")
        assert "fastapi" in content
        assert "uvicorn" in content
        assert "sqlalchemy" in content
        assert "asyncpg" in content

    def test_preserves_existing(self, tmp_path: Path):
        """_enrich_requirements_txt doesn't duplicate existing packages."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        req_file = service_dir / "requirements.txt"
        req_file.write_text("fastapi>=0.100.0\nuvicorn[standard]>=0.23.0\n")

        _enrich_requirements_txt(service_dir, "auth-service")

        content = req_file.read_text(encoding="utf-8")
        # Count occurrences of fastapi — should be exactly 1
        assert content.lower().count("fastapi") == 1
        assert content.lower().count("uvicorn") == 1

    def test_does_nothing_if_no_requirements_file(self, tmp_path: Path):
        """_enrich_requirements_txt does nothing if file doesn't exist."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()

        # Should not raise
        _enrich_requirements_txt(service_dir, "auth-service")

        # No file created
        assert not (service_dir / "requirements.txt").exists()

    def test_adds_alembic(self, tmp_path: Path):
        """_enrich_requirements_txt adds alembic."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        req_file = service_dir / "requirements.txt"
        req_file.write_text("fastapi\nuvicorn\nsqlalchemy\nasyncpg\npydantic\nemail-validator\n")

        _enrich_requirements_txt(service_dir, "auth-service")

        content = req_file.read_text(encoding="utf-8")
        assert "alembic" in content

    def test_handles_version_specifiers(self, tmp_path: Path):
        """_enrich_requirements_txt recognizes packages with version specifiers."""
        service_dir = tmp_path / "svc"
        service_dir.mkdir()
        req_file = service_dir / "requirements.txt"
        req_file.write_text("fastapi==0.104.1\nuvicorn[standard]==0.24.0\nsqlalchemy[asyncio]==2.0.23\n")

        _enrich_requirements_txt(service_dir, "svc")

        content = req_file.read_text(encoding="utf-8")
        # Should not add duplicates
        lines = [l for l in content.strip().split("\n") if l.strip() and not l.startswith("#")]
        fastapi_lines = [l for l in lines if "fastapi" in l.lower()]
        assert len(fastapi_lines) == 1
