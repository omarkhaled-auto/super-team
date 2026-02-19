"""Tests for DockerOrchestrator.

TEST-006: >= 10 test cases covering start/stop, health, URL, logs.
All Docker commands are mocked (no real Docker required).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integrator.docker_orchestrator import DockerOrchestrator


@pytest.fixture
def orchestrator(tmp_path: Path) -> DockerOrchestrator:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("version: '3.8'\nservices: {}", encoding="utf-8")
    return DockerOrchestrator(compose_file=compose, project_name="test-project")


class TestDockerOrchestrator:
    """Test Docker orchestration."""

    @pytest.mark.asyncio
    async def test_start_services_success(self, orchestrator) -> None:
        async def mock_run(*args):
            if "up" in args:
                return (0, "", "")
            if "ps" in args:
                return (0, "traefik\nauth-service\n", "")
            if "port" in args:
                return (0, "0.0.0.0:8080\n", "")
            return (0, "", "")

        orchestrator._run = mock_run
        result = await orchestrator.start_services()
        # start_services returns dict[str, ServiceInfo] on success
        assert isinstance(result, dict)
        assert "traefik" in result

    @pytest.mark.asyncio
    async def test_start_services_failure(self, orchestrator) -> None:
        async def mock_run(*args):
            return (1, "", "error: no space left")

        orchestrator._run = mock_run
        result = await orchestrator.start_services()
        # start_services returns empty dict on failure
        assert result == {}

    @pytest.mark.asyncio
    async def test_stop_services_success(self, orchestrator) -> None:
        async def mock_run(*args):
            return (0, "", "")

        orchestrator._run = mock_run
        result = await orchestrator.stop_services()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_stop_services_failure(self, orchestrator) -> None:
        async def mock_run(*args):
            return (1, "", "error")

        orchestrator._run = mock_run
        result = await orchestrator.stop_services()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_service_url(self, orchestrator) -> None:
        async def mock_run(*args):
            return (0, "0.0.0.0:32768\n", "")

        orchestrator._run = mock_run
        url = await orchestrator.get_service_url("auth-service", 8001)
        assert url == "http://localhost:32768"

    @pytest.mark.asyncio
    async def test_get_service_url_empty(self, orchestrator) -> None:
        async def mock_run(*args):
            return (0, "", "")

        orchestrator._run = mock_run
        url = await orchestrator.get_service_url("auth-service", 8001)
        assert url == "http://localhost:8001"

    @pytest.mark.asyncio
    async def test_get_service_logs(self, orchestrator) -> None:
        async def mock_run(*args):
            return (0, "INFO: Server started\nINFO: Healthy", "")

        orchestrator._run = mock_run
        logs = await orchestrator.get_service_logs("auth-service", tail=50)
        assert "Server started" in logs

    @pytest.mark.asyncio
    async def test_restart_service_success(self, orchestrator) -> None:
        async def mock_run(*args):
            return (0, "", "")

        orchestrator._run = mock_run
        result = await orchestrator.restart_service("auth-service")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_restart_service_failure(self, orchestrator) -> None:
        async def mock_run(*args):
            return (1, "", "container not found")

        orchestrator._run = mock_run
        result = await orchestrator.restart_service("nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_wait_for_healthy_already_healthy(self, orchestrator) -> None:
        # Mock discovery.check_health to always return True
        async def mock_check_health(service_name, url):
            return True

        orchestrator._discovery.check_health = mock_check_health
        services = {"auth": "http://localhost:8001/health"}
        result = await orchestrator.wait_for_healthy(
            services=services, timeout_seconds=5, poll_interval_seconds=1
        )
        assert result["all_healthy"] is True
