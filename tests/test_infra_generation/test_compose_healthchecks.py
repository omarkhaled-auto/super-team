"""Tests for compose health check generation.

Verifies that health checks use the correct tools for each stack:
- Python (python:3.12-slim): python -c urllib (NOT curl)
- NestJS (node:20-slim): node -e http module
- Frontend (nginx:stable-alpine): wget
- All use 127.0.0.1, never localhost (IPv6 fix)
"""

from __future__ import annotations

import pytest

from src.build3_shared.models import ServiceInfo
from src.integrator.compose_generator import ComposeGenerator


class TestPythonHealthCheck:
    """Python services must use python -c urllib (curl not in python:3.12-slim)."""

    def test_python_healthcheck_uses_urllib(self, generator: ComposeGenerator, python_service: ServiceInfo):
        """Python health check uses python -c 'import urllib...' command."""
        hc = generator._generate_healthcheck(
            service_id=python_service.service_id,
            stack="python",
            internal_port=8000,
            health_endpoint="/api/auth-service/health",
        )
        cmd = hc["test"][-1]
        assert "urllib" in cmd
        assert "python -c" in cmd

    def test_python_healthcheck_uses_127_0_0_1(self, generator: ComposeGenerator, python_service: ServiceInfo):
        """Python health check uses 127.0.0.1 (not localhost — IPv6 fix)."""
        hc = generator._generate_healthcheck(
            service_id=python_service.service_id,
            stack="python",
            internal_port=8000,
            health_endpoint="/health",
        )
        cmd = hc["test"][-1]
        assert "127.0.0.1" in cmd
        assert "localhost" not in cmd

    def test_python_healthcheck_includes_port(self, generator: ComposeGenerator):
        """Python health check targets the correct internal port."""
        hc = generator._generate_healthcheck(
            service_id="my-svc",
            stack="python",
            internal_port=8000,
            health_endpoint="/health",
        )
        assert "8000" in hc["test"][-1]

    def test_python_healthcheck_includes_endpoint(self, generator: ComposeGenerator):
        """Python health check includes the health endpoint path."""
        hc = generator._generate_healthcheck(
            service_id="my-svc",
            stack="python",
            internal_port=8000,
            health_endpoint="/api/my-svc/health",
        )
        assert "/api/my-svc/health" in hc["test"][-1]

    def test_python_healthcheck_no_curl(self, generator: ComposeGenerator):
        """Python health check must NOT use curl (not in python:3.12-slim)."""
        hc = generator._generate_healthcheck(
            service_id="my-svc",
            stack="python",
            internal_port=8000,
            health_endpoint="/health",
        )
        cmd = hc["test"][-1]
        assert "curl" not in cmd


class TestNestJSHealthCheck:
    """NestJS services must use node -e http module."""

    def test_nestjs_healthcheck_uses_node(self, generator: ComposeGenerator, nestjs_service: ServiceInfo):
        """NestJS health check uses node -e with http module."""
        hc = generator._generate_healthcheck(
            service_id=nestjs_service.service_id,
            stack="typescript",
            internal_port=8080,
            health_endpoint="/api/accounts-service/health",
        )
        cmd = hc["test"][-1]
        assert "node -e" in cmd
        assert "http" in cmd

    def test_nestjs_healthcheck_uses_127_0_0_1(self, generator: ComposeGenerator):
        """NestJS health check uses 127.0.0.1."""
        hc = generator._generate_healthcheck(
            service_id="accounts-service",
            stack="typescript",
            internal_port=8080,
            health_endpoint="/health",
        )
        cmd = hc["test"][-1]
        assert "127.0.0.1" in cmd
        assert "localhost" not in cmd

    def test_nestjs_healthcheck_includes_port(self, generator: ComposeGenerator):
        """NestJS health check targets port 8080."""
        hc = generator._generate_healthcheck(
            service_id="svc",
            stack="typescript",
            internal_port=8080,
            health_endpoint="/health",
        )
        assert "8080" in hc["test"][-1]


class TestFrontendHealthCheck:
    """Frontend services use wget (available in nginx:stable-alpine)."""

    def test_frontend_healthcheck_uses_wget(self, generator: ComposeGenerator):
        """Frontend health check uses wget."""
        hc = generator._generate_healthcheck(
            service_id="frontend",
            stack="frontend",
            internal_port=80,
            health_endpoint="/",
        )
        cmd = hc["test"][-1]
        assert "wget" in cmd

    def test_frontend_healthcheck_port_80(self, generator: ComposeGenerator):
        """Frontend health check targets port 80."""
        hc = generator._generate_healthcheck(
            service_id="frontend",
            stack="frontend",
            internal_port=80,
            health_endpoint="/",
        )
        cmd = hc["test"][-1]
        assert ":80" in cmd

    def test_frontend_healthcheck_uses_127_0_0_1(self, generator: ComposeGenerator):
        """Frontend health check uses 127.0.0.1."""
        hc = generator._generate_healthcheck(
            service_id="frontend",
            stack="frontend",
            internal_port=80,
            health_endpoint="/",
        )
        cmd = hc["test"][-1]
        assert "127.0.0.1" in cmd
        assert "localhost" not in cmd


class TestHealthCheckGeneral:
    """General health check properties across all stacks."""

    def test_unknown_stack_falls_back_to_wget(self, generator: ComposeGenerator):
        """Unknown stacks get wget-based health check."""
        hc = generator._generate_healthcheck(
            service_id="mystery",
            stack="unknown",
            internal_port=9000,
            health_endpoint="/health",
        )
        cmd = hc["test"][-1]
        assert "wget" in cmd
        assert "127.0.0.1" in cmd

    def test_healthcheck_has_correct_interval(self, generator: ComposeGenerator):
        """Health check interval, timeout, retries are set."""
        hc = generator._generate_healthcheck(
            service_id="svc",
            stack="python",
            internal_port=8000,
            health_endpoint="/health",
        )
        assert hc["interval"] == "15s"
        assert hc["timeout"] == "5s"
        assert hc["retries"] == 5
        assert hc["start_period"] == "90s"

    def test_healthcheck_uses_cmd_shell(self, generator: ComposeGenerator):
        """All health checks use CMD-SHELL format."""
        for stack in ("python", "typescript", "frontend", "unknown"):
            hc = generator._generate_healthcheck(
                service_id="svc",
                stack=stack,
                internal_port=8000,
                health_endpoint="/health",
            )
            assert hc["test"][0] == "CMD-SHELL"

    @pytest.mark.parametrize("stack", ["python", "typescript", "frontend", "unknown"])
    def test_no_curl_in_any_healthcheck(self, generator: ComposeGenerator, stack: str):
        """No health check uses curl (not available in slim images)."""
        hc = generator._generate_healthcheck(
            service_id="svc",
            stack=stack,
            internal_port=8000,
            health_endpoint="/health",
        )
        cmd = hc["test"][-1]
        assert "curl" not in cmd

    @pytest.mark.parametrize("stack", ["python", "typescript", "frontend", "unknown"])
    def test_no_localhost_in_any_healthcheck(self, generator: ComposeGenerator, stack: str):
        """No health check uses localhost (IPv6 issue)."""
        hc = generator._generate_healthcheck(
            service_id="svc",
            stack=stack,
            internal_port=8000,
            health_endpoint="/health",
        )
        cmd = hc["test"][-1]
        assert "localhost" not in cmd
