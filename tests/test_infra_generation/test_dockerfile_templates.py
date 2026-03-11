"""Tests for Dockerfile template generation.

Verifies:
- FastAPI template: HEALTHCHECK with urllib, system deps (gcc, libpq-dev)
- NestJS template: multi-stage build, port 8080, HEALTHCHECK with node
- Angular template: nginx:stable-alpine, dist/browser/ path, SPA routing
- _ensure_backend_dockerfile: generates for missing, patches existing
- _verify_dockerfiles_exist: generates fallbacks
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.build3_shared.models import ServiceInfo
from src.integrator.compose_generator import ComposeGenerator
from src.super_orchestrator.pipeline import (
    _FASTAPI_DOCKERFILE_TEMPLATE,
    _NESTJS_DOCKERFILE_TEMPLATE,
    _GENERIC_DOCKERFILE_TEMPLATE,
    _ensure_backend_dockerfile,
    _ensure_frontend_dockerfile,
    _verify_dockerfiles_exist,
)


class TestComposeGeneratorDockerfileTemplates:
    """Test _dockerfile_content_for_stack in ComposeGenerator."""

    def test_fastapi_template_has_healthcheck(self):
        """FastAPI Dockerfile template includes HEALTHCHECK."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8000,
            service_info=ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        )
        assert "HEALTHCHECK" in content

    def test_fastapi_template_uses_127_0_0_1(self):
        """FastAPI template health check uses 127.0.0.1."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8000,
            service_info=ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        )
        assert "127.0.0.1" in content
        assert "localhost" not in content

    def test_fastapi_template_installs_system_deps(self):
        """FastAPI template installs gcc and libpq-dev."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8000,
            service_info=ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        )
        assert "gcc" in content
        assert "libpq-dev" in content

    def test_fastapi_template_uses_python_slim(self):
        """FastAPI template uses python:3.12-slim-bookworm base."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8000,
            service_info=ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        )
        assert "python:3.12-slim" in content

    def test_nestjs_template_is_multistage(self):
        """NestJS template uses multi-stage build."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8080,
            service_info=ServiceInfo(
                service_id="accounts-service",
                domain="accounts",
                stack={"language": "typescript", "framework": "nestjs"},
                port=8080,
            ),
        )
        assert "AS build" in content
        assert "FROM node:20-slim" in content

    def test_nestjs_template_exposes_correct_port(self):
        """NestJS template exposes the given port."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=8080,
            service_info=ServiceInfo(
                service_id="accounts-service",
                domain="accounts",
                stack={"language": "typescript", "framework": "nestjs"},
                port=8080,
            ),
        )
        assert "EXPOSE 8080" in content

    def test_angular_template_uses_nginx(self):
        """Angular template serves via nginx:stable-alpine."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=80,
            service_info=ServiceInfo(
                service_id="frontend",
                domain="ui",
                stack={"language": "typescript", "framework": "angular"},
                port=80,
            ),
        )
        assert "nginx:stable-alpine" in content

    def test_angular_template_handles_dist_browser(self):
        """Angular template handles dist/*/browser/ path."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=80,
            service_info=ServiceInfo(
                service_id="frontend",
                domain="ui",
                stack={"language": "typescript", "framework": "angular"},
                port=80,
            ),
        )
        assert "browser" in content

    def test_angular_template_has_spa_routing(self):
        """Angular template has try_files for SPA routing."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=80,
            service_info=ServiceInfo(
                service_id="frontend",
                domain="ui",
                stack={"language": "typescript", "framework": "angular"},
                port=80,
            ),
        )
        assert "try_files" in content

    def test_angular_template_port_80(self):
        """Angular template exposes port 80."""
        content = ComposeGenerator._dockerfile_content_for_stack(
            port=80,
            service_info=ServiceInfo(
                service_id="frontend",
                domain="ui",
                stack={"language": "typescript", "framework": "angular"},
                port=80,
            ),
        )
        assert "EXPOSE 80" in content


class TestPipelineDockerfileTemplates:
    """Test pipeline-level Dockerfile template constants."""

    def test_fastapi_template_constant_has_healthcheck(self):
        """Pipeline FastAPI template has HEALTHCHECK."""
        assert "HEALTHCHECK" in _FASTAPI_DOCKERFILE_TEMPLATE
        assert "127.0.0.1" in _FASTAPI_DOCKERFILE_TEMPLATE

    def test_fastapi_template_constant_has_format_placeholder(self):
        """Pipeline FastAPI template has {service_id} placeholder."""
        assert "{service_id}" in _FASTAPI_DOCKERFILE_TEMPLATE

    def test_nestjs_template_constant_is_multistage(self):
        """Pipeline NestJS template is multi-stage."""
        assert "AS build" in _NESTJS_DOCKERFILE_TEMPLATE
        assert "EXPOSE 8080" in _NESTJS_DOCKERFILE_TEMPLATE

    def test_nestjs_template_constant_has_healthcheck(self):
        """Pipeline NestJS template has HEALTHCHECK with node."""
        assert "HEALTHCHECK" in _NESTJS_DOCKERFILE_TEMPLATE
        assert "node -e" in _NESTJS_DOCKERFILE_TEMPLATE
        assert "127.0.0.1" in _NESTJS_DOCKERFILE_TEMPLATE

    def test_generic_template_constant_has_healthcheck(self):
        """Pipeline generic template has HEALTHCHECK with wget."""
        assert "HEALTHCHECK" in _GENERIC_DOCKERFILE_TEMPLATE
        assert "wget" in _GENERIC_DOCKERFILE_TEMPLATE
        assert "127.0.0.1" in _GENERIC_DOCKERFILE_TEMPLATE


class TestEnsureBackendDockerfile:
    """Test _ensure_backend_dockerfile generation and patching."""

    def test_generates_for_missing_python(self, tmp_path: Path):
        """_ensure_backend_dockerfile creates Python Dockerfile when missing."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()

        _ensure_backend_dockerfile(service_dir, "auth-service", "python")

        dockerfile = service_dir / "Dockerfile"
        assert dockerfile.exists()
        content = dockerfile.read_text(encoding="utf-8")
        assert "python:3.12-slim" in content
        assert "HEALTHCHECK" in content

    def test_generates_for_missing_typescript(self, tmp_path: Path):
        """_ensure_backend_dockerfile creates NestJS Dockerfile when missing."""
        service_dir = tmp_path / "accounts-service"
        service_dir.mkdir()

        _ensure_backend_dockerfile(service_dir, "accounts-service", "typescript")

        dockerfile = service_dir / "Dockerfile"
        assert dockerfile.exists()
        content = dockerfile.read_text(encoding="utf-8")
        assert "node:20-slim" in content
        assert "HEALTHCHECK" in content

    def test_patches_existing_without_healthcheck(self, tmp_path: Path):
        """_ensure_backend_dockerfile adds HEALTHCHECK to existing file."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        dockerfile = service_dir / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN pip install fastapi\n")

        _ensure_backend_dockerfile(service_dir, "auth-service", "python")

        content = dockerfile.read_text(encoding="utf-8")
        assert "HEALTHCHECK" in content
        assert "127.0.0.1" in content

    def test_does_not_modify_existing_with_healthcheck(self, tmp_path: Path):
        """_ensure_backend_dockerfile does not modify file that already has HEALTHCHECK."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()
        dockerfile = service_dir / "Dockerfile"
        original = "FROM python:3.12-slim\nHEALTHCHECK CMD true\n"
        dockerfile.write_text(original)

        _ensure_backend_dockerfile(service_dir, "auth-service", "python")

        assert dockerfile.read_text(encoding="utf-8") == original

    def test_creates_service_dir_if_missing(self, tmp_path: Path):
        """_ensure_backend_dockerfile creates service directory if it doesn't exist."""
        service_dir = tmp_path / "new-service"
        # Don't create the dir

        _ensure_backend_dockerfile(service_dir, "new-service", "python")

        assert service_dir.exists()
        assert (service_dir / "Dockerfile").exists()


class TestVerifyDockerfilesExist:
    """Test _verify_dockerfiles_exist pre-integration check."""

    def test_generates_fallback_for_missing_backend(self, tmp_path: Path):
        """_verify_dockerfiles_exist generates fallback for missing backend Dockerfile."""
        service_dir = tmp_path / "auth-service"
        service_dir.mkdir()

        services = [
            ServiceInfo(
                service_id="auth-service",
                domain="auth",
                stack={"language": "python", "framework": "fastapi"},
                port=8000,
            ),
        ]

        missing = _verify_dockerfiles_exist(tmp_path, services)
        # Should auto-generate, so no missing services
        assert missing == []
        assert (service_dir / "Dockerfile").exists()

    def test_generates_fallback_for_missing_frontend(self, tmp_path: Path):
        """_verify_dockerfiles_exist generates fallback for missing frontend Dockerfile."""
        service_dir = tmp_path / "frontend"
        service_dir.mkdir()

        services = [
            ServiceInfo(
                service_id="frontend",
                domain="ui",
                stack={"language": "typescript", "framework": "angular"},
                port=80,
            ),
        ]

        missing = _verify_dockerfiles_exist(tmp_path, services)
        assert missing == []
        assert (service_dir / "Dockerfile").exists()
