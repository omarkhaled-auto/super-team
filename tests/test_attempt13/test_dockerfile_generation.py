"""Tests for frontend Dockerfile generation (Fix 5) and pre-integration check (Fix 8).

Verifies that _ensure_frontend_dockerfile generates correct nginx-based
Dockerfiles and that _verify_dockerfiles_exist catches missing Dockerfiles.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.build3_shared.models import ServiceInfo
from src.super_orchestrator.pipeline import (
    _ensure_frontend_dockerfile,
    _is_frontend_service,
    _verify_dockerfiles_exist,
)


class TestEnsureFrontendDockerfile:
    """Test _ensure_frontend_dockerfile generation."""

    def test_generates_dockerfile_when_missing(self, tmp_path: Path):
        """Frontend service gets a Dockerfile if builder didn't create one."""
        service_dir = tmp_path / "frontend"
        service_dir.mkdir()

        svc = ServiceInfo(
            service_id="frontend",
            domain="ui",
            stack={"language": "typescript", "framework": "react"},
            port=3000,
        )

        _ensure_frontend_dockerfile(service_dir, svc)

        dockerfile = service_dir / "Dockerfile"
        assert dockerfile.exists()
        content = dockerfile.read_text()
        assert "nginx" in content.lower()
        assert "HEALTHCHECK" in content
        assert "try_files" in content  # SPA routing

    def test_does_not_overwrite_existing_dockerfile(self, tmp_path: Path):
        """Existing Dockerfile is not replaced by template (but HEALTHCHECK may be appended)."""
        service_dir = tmp_path / "frontend"
        service_dir.mkdir()
        (service_dir / "Dockerfile").write_text("FROM custom:latest\nHEALTHCHECK CMD true\n")

        svc = ServiceInfo(
            service_id="frontend",
            domain="ui",
            stack={"language": "typescript", "framework": "react"},
            port=3000,
        )

        _ensure_frontend_dockerfile(service_dir, svc)

        assert (service_dir / "Dockerfile").read_text() == "FROM custom:latest\nHEALTHCHECK CMD true\n"

    def test_multi_stage_build_without_dist(self, tmp_path: Path):
        """Without pre-compiled output, generates multi-stage build."""
        service_dir = tmp_path / "frontend"
        service_dir.mkdir()

        svc = ServiceInfo(
            service_id="frontend",
            domain="ui",
            stack={"language": "typescript", "framework": "react"},
            port=3000,
        )

        _ensure_frontend_dockerfile(service_dir, svc)

        content = (service_dir / "Dockerfile").read_text()
        assert "node:20-slim" in content  # Build stage
        assert "npm ci" in content
        assert "npm run build" in content
        assert "nginx:stable-alpine" in content

    def test_simple_serve_with_dist(self, tmp_path: Path):
        """With pre-compiled output, generates simple nginx serve."""
        service_dir = tmp_path / "frontend"
        service_dir.mkdir()
        (service_dir / "dist" / "ledgerpro").mkdir(parents=True)

        svc = ServiceInfo(
            service_id="frontend",
            domain="ui",
            stack={"language": "typescript", "framework": "angular"},
            port=3000,
        )

        _ensure_frontend_dockerfile(service_dir, svc)

        content = (service_dir / "Dockerfile").read_text()
        assert "nginx:stable-alpine" in content
        # Should NOT have multi-stage build directives
        assert "npm ci" not in content
        assert "COPY dist/" in content or "COPY --from=build" not in content

    def test_exposes_port_80(self, tmp_path: Path):
        """Generated Dockerfile exposes port 80."""
        service_dir = tmp_path / "frontend"
        service_dir.mkdir()

        svc = ServiceInfo(
            service_id="frontend",
            domain="ui",
            stack={"language": "typescript", "framework": "vue"},
            port=3000,
        )

        _ensure_frontend_dockerfile(service_dir, svc)

        content = (service_dir / "Dockerfile").read_text()
        assert "EXPOSE 80" in content


class TestIsFrontendService:
    """Test _is_frontend_service detection."""

    @pytest.mark.parametrize(
        "framework",
        ["angular", "react", "vue", "next", "nextjs", "nuxt", "svelte"],
    )
    def test_frontend_frameworks(self, framework: str):
        """Known frontend frameworks are detected."""
        svc = ServiceInfo(
            service_id="frontend",
            domain="ui",
            stack={"language": "typescript", "framework": framework},
            port=3000,
        )
        assert _is_frontend_service(svc) is True

    def test_backend_not_frontend(self):
        """Backend frameworks are not detected as frontend."""
        svc = ServiceInfo(
            service_id="auth-service",
            domain="auth",
            stack={"language": "python", "framework": "fastapi"},
            port=8001,
        )
        assert _is_frontend_service(svc) is False

    def test_non_dict_stack(self):
        """Non-dict stack returns False."""
        svc = ServiceInfo(
            service_id="test",
            domain="test",
            stack="python",  # type: ignore[arg-type]
            port=8000,
        )
        assert _is_frontend_service(svc) is False


class TestVerifyDockerfilesExist:
    """Test _verify_dockerfiles_exist pre-integration check."""

    def test_all_have_dockerfiles(self, tmp_path: Path):
        """No missing services when all have Dockerfiles."""
        for name in ("auth-service", "accounts-service"):
            svc_dir = tmp_path / name
            svc_dir.mkdir()
            (svc_dir / "Dockerfile").write_text("FROM python:3.12")

        services = [
            ServiceInfo(
                service_id="auth-service", domain="auth",
                stack={"language": "python", "framework": "fastapi"}, port=8001,
            ),
            ServiceInfo(
                service_id="accounts-service", domain="accounts",
                stack={"language": "typescript", "framework": "express"}, port=8002,
            ),
        ]

        missing = _verify_dockerfiles_exist(tmp_path, services)
        assert missing == []

    def test_missing_backend_dockerfile_auto_generated(self, tmp_path: Path):
        """Backend service without Dockerfile gets one auto-generated."""
        svc_dir = tmp_path / "auth-service"
        svc_dir.mkdir()
        # No Dockerfile created

        services = [
            ServiceInfo(
                service_id="auth-service", domain="auth",
                stack={"language": "python", "framework": "fastapi"}, port=8001,
            ),
        ]

        missing = _verify_dockerfiles_exist(tmp_path, services)
        # _verify_dockerfiles_exist now auto-generates fallback Dockerfiles
        assert missing == []
        assert (svc_dir / "Dockerfile").exists()

    def test_frontend_auto_generated(self, tmp_path: Path):
        """Frontend service gets Dockerfile auto-generated, not reported as missing."""
        svc_dir = tmp_path / "frontend"
        svc_dir.mkdir()
        # No Dockerfile, but it's a frontend service

        services = [
            ServiceInfo(
                service_id="frontend", domain="ui",
                stack={"language": "typescript", "framework": "react"}, port=3000,
            ),
        ]

        missing = _verify_dockerfiles_exist(tmp_path, services)
        assert missing == []
        assert (tmp_path / "frontend" / "Dockerfile").exists()
