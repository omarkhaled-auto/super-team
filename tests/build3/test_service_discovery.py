"""Tests for ServiceDiscovery.

TEST-009: >= 6 test cases covering ports, health, timeout.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integrator.service_discovery import ServiceDiscovery


@pytest.fixture
def discovery(tmp_path: Path) -> ServiceDiscovery:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("version: '3.8'\nservices: {}", encoding="utf-8")
    return ServiceDiscovery(compose_file=compose, project_name="test")


class TestServiceDiscovery:
    """Test service discovery."""

    def test_get_service_ports(self, discovery) -> None:
        """get_service_ports is synchronous (uses subprocess.run)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="auth:0.0.0.0:32768->8001/tcp\norder:0.0.0.0:32769->8002/tcp\n"
            )
            ports = discovery.get_service_ports()
        assert ports["auth"] == 32768
        assert ports["order"] == 32769

    def test_get_service_ports_empty(self, discovery) -> None:
        """get_service_ports returns empty dict when no ports."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            ports = discovery.get_service_ports()
        assert ports == {}

    @pytest.mark.asyncio
    async def test_check_health_success(self, discovery) -> None:
        with patch("httpx.AsyncClient") as MockClient:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "healthy"}
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            # check_health now takes (service_name, url) and returns bool
            result = await discovery.check_health("auth-service", "http://localhost:8001/health")
            assert result is True

    @pytest.mark.asyncio
    async def test_check_health_failure(self, discovery) -> None:
        with patch("httpx.AsyncClient") as MockClient:
            mock_resp = MagicMock()
            mock_resp.status_code = 503
            mock_resp.text = "Service Unavailable"
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            # check_health now returns bool (False for 503)
            result = await discovery.check_health("auth-service", "http://localhost:8001/health")
            assert result is False

    @pytest.mark.asyncio
    async def test_check_health_connection_error(self, discovery) -> None:
        import httpx
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            # check_health returns False on connection error
            result = await discovery.check_health("auth-service", "http://localhost:8001/health")
            assert result is False

    @pytest.mark.asyncio
    async def test_wait_all_healthy_success(self, discovery) -> None:
        check_count = 0

        async def mock_check(service_name, url):
            nonlocal check_count
            check_count += 1
            return True

        discovery.check_health = mock_check
        services = {"auth": "http://localhost:8001/health"}
        result = await discovery.wait_all_healthy(
            services, timeout_seconds=5, poll_interval=1
        )
        assert result["all_healthy"] is True

    @pytest.mark.asyncio
    async def test_wait_all_healthy_timeout(self, discovery) -> None:
        async def mock_check(service_name, url):
            return False

        discovery.check_health = mock_check
        services = {"auth": "http://localhost:8001/health"}
        result = await discovery.wait_all_healthy(
            services, timeout_seconds=2, poll_interval=1
        )
        assert result["all_healthy"] is False
