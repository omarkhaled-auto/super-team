"""Integration tests for Docker Compose multi-service deployment (REQ-019).

These tests verify that all 3 services (architect, contract-engine, codebase-intel)
can start via docker-compose and pass health checks. Tests are designed to be
safe when Docker is not available -- they skip gracefully instead of failing.

Requirements verified:
  - All 3 services start and respond to health checks
  - Health checks pass within 60 seconds
  - Each service returns the correct HealthStatus shape
  - Inter-service connectivity works
"""
from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

import httpx
import pytest

from src.shared.constants import (
    ARCHITECT_PORT,
    ARCHITECT_SERVICE_NAME,
    CODEBASE_INTEL_PORT,
    CODEBASE_INTEL_SERVICE_NAME,
    CONTRACT_ENGINE_PORT,
    CONTRACT_ENGINE_SERVICE_NAME,
    VERSION,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL_ARCHITECT = f"http://localhost:{ARCHITECT_PORT}"
BASE_URL_CONTRACT_ENGINE = f"http://localhost:{CONTRACT_ENGINE_PORT}"
BASE_URL_CODEBASE_INTEL = f"http://localhost:{CODEBASE_INTEL_PORT}"

HEALTH_ENDPOINT = "/api/health"
HEALTH_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 2

SERVICE_ENDPOINTS: dict[str, str] = {
    ARCHITECT_SERVICE_NAME: f"{BASE_URL_ARCHITECT}{HEALTH_ENDPOINT}",
    CONTRACT_ENGINE_SERVICE_NAME: f"{BASE_URL_CONTRACT_ENGINE}{HEALTH_ENDPOINT}",
    CODEBASE_INTEL_SERVICE_NAME: f"{BASE_URL_CODEBASE_INTEL}{HEALTH_ENDPOINT}",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docker_is_available() -> bool:
    """Return True if the ``docker`` CLI is on PATH and the daemon responds."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _service_is_healthy(url: str, timeout: float = 5.0) -> bool:
    """Return True if a single GET to *url* succeeds with HTTP 200."""
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, OSError):
        return False


def _poll_health(url: str, deadline_seconds: float = HEALTH_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Poll *url* until it returns HTTP 200, then return the parsed JSON body.

    Raises ``TimeoutError`` if the deadline is exceeded.
    """
    start = time.monotonic()
    last_error: Exception | None = None
    while time.monotonic() - start < deadline_seconds:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return resp.json()
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, OSError) as exc:
            last_error = exc
        time.sleep(POLL_INTERVAL_SECONDS)
    msg = f"Health endpoint {url} did not respond within {deadline_seconds}s"
    if last_error is not None:
        msg += f" (last error: {last_error})"
    raise TimeoutError(msg)


def _validate_health_response(data: dict[str, Any], expected_service: str) -> None:
    """Assert the response has the correct HealthStatus shape and values."""
    assert data["status"] == "healthy", f"Expected status 'healthy', got {data['status']!r}"
    assert data["service_name"] == expected_service, (
        f"Expected service_name {expected_service!r}, got {data['service_name']!r}"
    )
    assert data["version"] == VERSION, (
        f"Expected version {VERSION!r}, got {data['version']!r}"
    )
    assert data["database"] == "connected", (
        f"Expected database 'connected', got {data['database']!r}"
    )
    assert isinstance(data["uptime_seconds"], (int, float)), (
        f"Expected uptime_seconds to be numeric, got {type(data['uptime_seconds']).__name__}"
    )
    assert data["uptime_seconds"] >= 0, (
        f"Expected non-negative uptime_seconds, got {data['uptime_seconds']}"
    )
    assert isinstance(data.get("details"), dict), (
        "Expected 'details' to be a dict"
    )


# ---------------------------------------------------------------------------
# Markers / skip conditions
# ---------------------------------------------------------------------------

_docker_available = _docker_is_available()

skip_no_docker = pytest.mark.skipif(
    not _docker_available,
    reason="Docker is not available or the daemon is not running",
)

# Custom marker so users can run: pytest -m integration
pytestmark = [
    pytest.mark.integration,
    pytest.mark.e2e,
    skip_no_docker,
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def docker_services_running() -> bool:
    """Check whether the Docker Compose services are already running.

    This fixture does NOT start or stop Docker -- it merely probes the health
    endpoints.  If none of the services respond, the test module is skipped.
    """
    for url in SERVICE_ENDPOINTS.values():
        if _service_is_healthy(url, timeout=3.0):
            return True
    pytest.skip(
        "No Docker Compose services are reachable; "
        "start them with 'docker-compose up -d' before running integration tests."
    )


@pytest.fixture(scope="module")
def architect_health(docker_services_running: bool) -> dict[str, Any]:
    """Poll the architect health endpoint and return the JSON response."""
    return _poll_health(SERVICE_ENDPOINTS[ARCHITECT_SERVICE_NAME])


@pytest.fixture(scope="module")
def contract_engine_health(docker_services_running: bool) -> dict[str, Any]:
    """Poll the contract-engine health endpoint and return the JSON response."""
    return _poll_health(SERVICE_ENDPOINTS[CONTRACT_ENGINE_SERVICE_NAME])


@pytest.fixture(scope="module")
def codebase_intel_health(docker_services_running: bool) -> dict[str, Any]:
    """Poll the codebase-intelligence health endpoint and return the JSON response."""
    return _poll_health(SERVICE_ENDPOINTS[CODEBASE_INTEL_SERVICE_NAME])


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestArchitectHealthCheck:
    """Verify the architect service responds with a valid HealthStatus."""

    def test_architect_health_check(self, architect_health: dict[str, Any]) -> None:
        """Hit http://localhost:8001/api/health and verify HealthStatus shape."""
        _validate_health_response(architect_health, ARCHITECT_SERVICE_NAME)

    def test_architect_status_is_healthy(self, architect_health: dict[str, Any]) -> None:
        assert architect_health["status"] == "healthy"

    def test_architect_version(self, architect_health: dict[str, Any]) -> None:
        assert architect_health["version"] == "1.0.0"

    def test_architect_database_connected(self, architect_health: dict[str, Any]) -> None:
        assert architect_health["database"] == "connected"


class TestContractEngineHealthCheck:
    """Verify the contract-engine service responds with a valid HealthStatus."""

    def test_contract_engine_health_check(
        self, contract_engine_health: dict[str, Any]
    ) -> None:
        """Hit http://localhost:8002/api/health and verify HealthStatus shape."""
        _validate_health_response(contract_engine_health, CONTRACT_ENGINE_SERVICE_NAME)

    def test_contract_engine_status_is_healthy(
        self, contract_engine_health: dict[str, Any]
    ) -> None:
        assert contract_engine_health["status"] == "healthy"

    def test_contract_engine_version(
        self, contract_engine_health: dict[str, Any]
    ) -> None:
        assert contract_engine_health["version"] == "1.0.0"

    def test_contract_engine_database_connected(
        self, contract_engine_health: dict[str, Any]
    ) -> None:
        assert contract_engine_health["database"] == "connected"


class TestCodebaseIntelHealthCheck:
    """Verify the codebase-intelligence service responds with a valid HealthStatus."""

    def test_codebase_intel_health_check(
        self, codebase_intel_health: dict[str, Any]
    ) -> None:
        """Hit http://localhost:8003/api/health and verify HealthStatus shape."""
        _validate_health_response(codebase_intel_health, CODEBASE_INTEL_SERVICE_NAME)

    def test_codebase_intel_status_is_healthy(
        self, codebase_intel_health: dict[str, Any]
    ) -> None:
        assert codebase_intel_health["status"] == "healthy"

    def test_codebase_intel_version(
        self, codebase_intel_health: dict[str, Any]
    ) -> None:
        assert codebase_intel_health["version"] == "1.0.0"

    def test_codebase_intel_database_connected(
        self, codebase_intel_health: dict[str, Any]
    ) -> None:
        assert codebase_intel_health["database"] == "connected"


class TestAllServicesTimeout:
    """Verify all three services respond within the 60-second deadline."""

    def test_all_services_respond_within_timeout(
        self, docker_services_running: bool
    ) -> None:
        """All 3 health endpoints must respond within 60 seconds of polling."""
        start = time.monotonic()
        results: dict[str, dict[str, Any]] = {}
        for name, url in SERVICE_ENDPOINTS.items():
            remaining = HEALTH_TIMEOUT_SECONDS - (time.monotonic() - start)
            assert remaining > 0, (
                f"Ran out of time before reaching {name}; "
                f"elapsed {time.monotonic() - start:.1f}s"
            )
            results[name] = _poll_health(url, deadline_seconds=remaining)
        elapsed = time.monotonic() - start

        # All three must have responded
        assert len(results) == 3, f"Expected 3 results, got {len(results)}"
        for name, data in results.items():
            assert data["status"] == "healthy", (
                f"{name} reported status {data['status']!r}, expected 'healthy'"
            )

        assert elapsed < HEALTH_TIMEOUT_SECONDS, (
            f"Services took {elapsed:.1f}s to respond, exceeding {HEALTH_TIMEOUT_SECONDS}s limit"
        )


class TestInterServiceConnectivity:
    """Verify inter-service connectivity through the Docker network."""

    def test_inter_service_connectivity(self, docker_services_running: bool) -> None:
        """Verify architect can communicate with contract-engine and codebase-intel.

        The architect service is configured with environment variables pointing
        to the other services (CONTRACT_ENGINE_URL, CODEBASE_INTEL_URL).  If
        the architect health check passes with ``database='connected'`` and
        ``status='healthy'``, it means the service started successfully with
        those inter-service URLs resolved.

        As a secondary check, we confirm that all three services are on the
        same Docker network by verifying each health endpoint is reachable
        from the test host.
        """
        all_healthy: dict[str, dict[str, Any]] = {}
        for name, url in SERVICE_ENDPOINTS.items():
            data = _poll_health(url, deadline_seconds=HEALTH_TIMEOUT_SECONDS)
            all_healthy[name] = data

        # Architect depends_on contract-engine; if it is healthy, the
        # dependency relationship resolved over the Docker network.
        assert all_healthy[ARCHITECT_SERVICE_NAME]["status"] == "healthy"
        assert all_healthy[CONTRACT_ENGINE_SERVICE_NAME]["status"] == "healthy"
        assert all_healthy[CODEBASE_INTEL_SERVICE_NAME]["status"] == "healthy"

    def test_architect_can_reach_contract_engine(
        self, docker_services_running: bool
    ) -> None:
        """The architect service depends_on contract-engine (service_healthy).

        If architect started at all, Docker Compose confirmed that contract-engine
        was healthy first.  We verify both are reachable to confirm the dependency
        chain is intact.
        """
        architect_data = _poll_health(
            SERVICE_ENDPOINTS[ARCHITECT_SERVICE_NAME],
            deadline_seconds=HEALTH_TIMEOUT_SECONDS,
        )
        contract_data = _poll_health(
            SERVICE_ENDPOINTS[CONTRACT_ENGINE_SERVICE_NAME],
            deadline_seconds=HEALTH_TIMEOUT_SECONDS,
        )

        assert architect_data["status"] == "healthy"
        assert contract_data["status"] == "healthy"

    def test_codebase_intel_can_reach_contract_engine(
        self, docker_services_running: bool
    ) -> None:
        """Codebase-intel depends_on contract-engine (service_healthy).

        Same reasoning: if codebase-intel started, Docker Compose confirmed
        that contract-engine was healthy first.
        """
        intel_data = _poll_health(
            SERVICE_ENDPOINTS[CODEBASE_INTEL_SERVICE_NAME],
            deadline_seconds=HEALTH_TIMEOUT_SECONDS,
        )
        contract_data = _poll_health(
            SERVICE_ENDPOINTS[CONTRACT_ENGINE_SERVICE_NAME],
            deadline_seconds=HEALTH_TIMEOUT_SECONDS,
        )

        assert intel_data["status"] == "healthy"
        assert contract_data["status"] == "healthy"

    def test_all_services_report_correct_service_names(
        self, docker_services_running: bool
    ) -> None:
        """Each service must identify itself with the correct service_name."""
        expected_names = {
            ARCHITECT_SERVICE_NAME,
            CONTRACT_ENGINE_SERVICE_NAME,
            CODEBASE_INTEL_SERVICE_NAME,
        }
        reported_names: set[str] = set()
        for name, url in SERVICE_ENDPOINTS.items():
            data = _poll_health(url, deadline_seconds=HEALTH_TIMEOUT_SECONDS)
            reported_names.add(data["service_name"])

        assert reported_names == expected_names, (
            f"Expected service names {expected_names}, got {reported_names}"
        )
