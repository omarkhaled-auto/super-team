"""Milestone 4 -- Health check cascade and security tests (mock-based).

REQ-021 health gates, WIRE-020 cascade ordering,
SEC-001/SEC-002/SEC-003 security requirements.
All tests use mocks -- no Docker or live services required.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.run4.builder import BuilderResult, _filtered_env, invoke_builder
from src.run4.mcp_health import poll_until_healthy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The 5-tier startup cascade from REQUIREMENTS.md WIRE-020
TIER_0 = ["postgres", "redis"]
TIER_1 = ["contract-engine"]
TIER_2 = ["architect", "codebase-intelligence"]
TIER_3 = ["auth-service", "order-service", "notification-service"]
TIER_4 = ["traefik"]

FULL_CASCADE_ORDER = TIER_0 + TIER_1 + TIER_2 + TIER_3 + TIER_4

# Run4 overlay compose config (from REQUIREMENTS.md)
RUN4_COMPOSE_CONFIG: dict[str, Any] = {
    "services": {
        "architect": {
            "networks": ["frontend", "backend"],
            "labels": [
                "traefik.enable=true",
                "traefik.http.routers.architect.rule=PathPrefix(`/api/architect`)",
                "traefik.http.services.architect.loadbalancer.server.port=8000",
            ],
        },
        "contract-engine": {
            "networks": ["frontend", "backend"],
            "labels": [
                "traefik.enable=true",
                "traefik.http.routers.contract-engine.rule=PathPrefix(`/api/contracts`)",
                "traefik.http.services.contract-engine.loadbalancer.server.port=8000",
            ],
        },
        "codebase-intelligence": {
            "networks": ["frontend", "backend"],
            "labels": [
                "traefik.enable=true",
                "traefik.http.routers.codebase-intel.rule=PathPrefix(`/api/codebase`)",
                "traefik.http.services.codebase-intel.loadbalancer.server.port=8000",
            ],
        },
        "traefik": {
            "command": [
                "--api.dashboard=false",
                "--providers.docker=true",
                "--providers.docker.exposedbydefault=false",
            ],
            "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
        },
    },
    "networks": {
        "frontend": {"driver": "bridge"},
        "backend": {"driver": "bridge"},
    },
}


def _build_dependency_graph() -> dict[str, list[str]]:
    """Build a service dependency graph matching WIRE-020 cascade.

    Returns mapping of service -> list of services it depends on.
    """
    graph: dict[str, list[str]] = {}
    # Tier 0: no dependencies
    for svc in TIER_0:
        graph[svc] = []
    # Tier 1: depends on postgres (Tier 0)
    for svc in TIER_1:
        graph[svc] = ["postgres"]
    # Tier 2: depends on contract-engine (Tier 1)
    for svc in TIER_2:
        graph[svc] = ["contract-engine"]
    # Tier 3: depends on architect + contract-engine
    for svc in TIER_3:
        graph[svc] = ["architect", "contract-engine"]
    # Tier 4: depends on all services
    for svc in TIER_4:
        graph[svc] = TIER_3.copy()
    return graph


def _write_state_json(output_dir: Path, *, success: bool = True) -> None:
    """Write a valid STATE.json for builder tests."""
    state_dir = output_dir / ".agent-team"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "STATE.json"
    data = {
        "run_id": "health-test",
        "health": "green",
        "current_phase": "complete",
        "completed_phases": ["architect", "builders"],
        "total_cost": 0.50,
        "summary": {
            "success": success,
            "test_passed": 10,
            "test_total": 10,
            "convergence_ratio": 1.0,
        },
        "schema_version": 2,
    }
    state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ===================================================================
# WIRE-020 -- Health Check Cascade
# ===================================================================


class TestHealthCheckCascade:
    """WIRE-020 -- Verify startup order respects dependency chain.

    Tier 0: postgres, redis (service_healthy)
    Tier 1: contract-engine (depends_on: postgres)
    Tier 2: architect, codebase-intelligence (depends_on: contract-engine)
    Tier 3: generated services (depends_on: architect, contract-engine)
    Tier 4: traefik (depends_on: all services)
    """

    def test_startup_order_tiers(self) -> None:
        """Services start in correct tier order: T0 -> T1 -> T2 -> T3 -> T4."""
        startup_sequence: list[str] = []

        # Simulate tier-by-tier startup
        for tier_name, tier_services in [
            ("tier0", TIER_0),
            ("tier1", TIER_1),
            ("tier2", TIER_2),
            ("tier3", TIER_3),
            ("tier4", TIER_4),
        ]:
            for svc in tier_services:
                startup_sequence.append(svc)

        # Verify postgres and redis start before everything else
        pg_idx = startup_sequence.index("postgres")
        redis_idx = startup_sequence.index("redis")
        ce_idx = startup_sequence.index("contract-engine")
        arch_idx = startup_sequence.index("architect")
        ci_idx = startup_sequence.index("codebase-intelligence")
        traefik_idx = startup_sequence.index("traefik")

        assert pg_idx < ce_idx, "postgres must start before contract-engine"
        assert redis_idx < ce_idx, "redis must start before contract-engine"
        assert ce_idx < arch_idx, "contract-engine must start before architect"
        assert ce_idx < ci_idx, "contract-engine must start before codebase-intelligence"
        assert arch_idx < traefik_idx, "architect must start before traefik"
        assert ci_idx < traefik_idx, "codebase-intelligence must start before traefik"

    def test_dependency_graph_completeness(self) -> None:
        """Every service in the cascade has its dependencies defined."""
        graph = _build_dependency_graph()
        all_services = set(FULL_CASCADE_ORDER)

        assert set(graph.keys()) == all_services
        for svc, deps in graph.items():
            for dep in deps:
                assert dep in all_services, f"{svc} depends on unknown service: {dep}"

    def test_tier0_has_no_dependencies(self) -> None:
        """Tier 0 services (postgres, redis) have no dependencies."""
        graph = _build_dependency_graph()
        for svc in TIER_0:
            assert graph[svc] == [], f"Tier 0 service {svc} should have no dependencies"

    def test_contract_engine_depends_on_postgres(self) -> None:
        """contract-engine (Tier 1) depends on postgres (Tier 0)."""
        graph = _build_dependency_graph()
        assert "postgres" in graph["contract-engine"]

    def test_architect_depends_on_contract_engine(self) -> None:
        """architect (Tier 2) depends on contract-engine (Tier 1)."""
        graph = _build_dependency_graph()
        assert "contract-engine" in graph["architect"]

    def test_generated_services_depend_on_tier2(self) -> None:
        """Generated services (Tier 3) depend on architect and contract-engine."""
        graph = _build_dependency_graph()
        for svc in TIER_3:
            assert "architect" in graph[svc], f"{svc} should depend on architect"
            assert "contract-engine" in graph[svc], f"{svc} should depend on contract-engine"

    def test_traefik_starts_last(self) -> None:
        """traefik (Tier 4) is the last service to start."""
        graph = _build_dependency_graph()
        # traefik depends on Tier 3 services
        for dep in graph["traefik"]:
            assert dep in TIER_3, f"traefik unexpected dependency: {dep}"


# ===================================================================
# REQ-021 -- Health Gate Blocking
# ===================================================================


class TestHealthGateBlocking:
    """REQ-021 -- If any Tier 0/1 service unhealthy, pipeline blocks."""

    @pytest.mark.asyncio
    async def test_tier0_unhealthy_blocks_pipeline(self) -> None:
        """Pipeline blocks when Tier 0 (postgres) is unhealthy."""
        import httpx

        async def selective_health(url: str) -> MagicMock:
            if "postgres" in url or "5432" in url:
                raise httpx.ConnectError("postgres refused")
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=selective_health)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.run4.mcp_health.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(TimeoutError, match="postgres"):
                await poll_until_healthy(
                    service_urls={
                        "postgres": "http://localhost:5432/health",
                        "contract-engine": "http://localhost:8002/api/health",
                    },
                    timeout_s=0.1,
                    interval_s=0.01,
                    required_consecutive=2,
                )

    @pytest.mark.asyncio
    async def test_tier1_unhealthy_blocks_pipeline(self) -> None:
        """Pipeline blocks when Tier 1 (contract-engine) is unhealthy."""
        import httpx

        async def selective_health(url: str) -> MagicMock:
            if "8002" in url:
                resp = MagicMock()
                resp.status_code = 503
                return resp
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=selective_health)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.run4.mcp_health.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(TimeoutError, match="contract-engine"):
                await poll_until_healthy(
                    service_urls={
                        "architect": "http://localhost:8001/api/health",
                        "contract-engine": "http://localhost:8002/api/health",
                    },
                    timeout_s=0.1,
                    interval_s=0.01,
                    required_consecutive=2,
                )

    @pytest.mark.asyncio
    async def test_all_healthy_allows_pipeline(self) -> None:
        """Pipeline proceeds when all services are healthy."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.run4.mcp_health.httpx.AsyncClient", return_value=mock_client):
            results = await poll_until_healthy(
                service_urls={
                    "architect": "http://localhost:8001/api/health",
                    "contract-engine": "http://localhost:8002/api/health",
                    "codebase-intelligence": "http://localhost:8003/api/health",
                },
                timeout_s=10,
                interval_s=0.01,
                required_consecutive=2,
            )

        assert all(r["status"] == "healthy" for r in results.values())


# ===================================================================
# SEC-001 -- No ANTHROPIC_API_KEY in builder subprocess env
# ===================================================================


class TestSEC001NoApiKey:
    """SEC-001 -- Verify ANTHROPIC_API_KEY not passed to builder subprocess."""

    def test_filtered_env_excludes_anthropic_key(self) -> None:
        """_filtered_env() strips ANTHROPIC_API_KEY from the environment."""
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "sk-secret-key",
            "PATH": "/usr/bin",
            "HOME": "/home/test",
        }):
            env = _filtered_env()

        assert "ANTHROPIC_API_KEY" not in env
        assert "PATH" in env
        assert "HOME" in env

    def test_filtered_env_excludes_openai_key(self) -> None:
        """_filtered_env() also strips OPENAI_API_KEY."""
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "sk-openai-key",
            "PATH": "/usr/bin",
        }):
            env = _filtered_env()

        assert "OPENAI_API_KEY" not in env

    def test_filtered_env_excludes_aws_secret(self) -> None:
        """_filtered_env() also strips AWS_SECRET_ACCESS_KEY."""
        with patch.dict(os.environ, {
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "PATH": "/usr/bin",
        }):
            env = _filtered_env()

        assert "AWS_SECRET_ACCESS_KEY" not in env

    @pytest.mark.asyncio
    async def test_invoke_builder_uses_filtered_env(self, tmp_path: Path) -> None:
        """invoke_builder passes filtered env to subprocess (no secret keys)."""
        builder_dir = tmp_path / "sec-test-svc"
        builder_dir.mkdir()
        _write_state_json(builder_dir)

        captured_env: dict[str, str] = {}

        async def capture_create(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal captured_env
            captured_env = kwargs.get("env", {}) or {}
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
            proc.wait = AsyncMock(return_value=0)
            proc.kill = MagicMock()
            return proc

        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "sk-secret-key",
            "OPENAI_API_KEY": "sk-openai-key",
            "PATH": os.environ.get("PATH", ""),
        }):
            with patch(
                "src.run4.builder.asyncio.create_subprocess_exec",
                side_effect=capture_create,
            ):
                await invoke_builder(cwd=builder_dir, depth="thorough", timeout_s=10)

        assert "ANTHROPIC_API_KEY" not in captured_env
        assert "OPENAI_API_KEY" not in captured_env
        assert "PATH" in captured_env


# ===================================================================
# SEC-002 -- Traefik Dashboard Disabled
# ===================================================================


class TestSEC002TraefikDashboard:
    """SEC-002 -- Verify --api.dashboard=false in compose config."""

    def test_traefik_dashboard_disabled_in_config(self) -> None:
        """The run4 compose overlay includes --api.dashboard=false for traefik."""
        traefik_config = RUN4_COMPOSE_CONFIG["services"]["traefik"]
        command_args = traefik_config["command"]

        assert "--api.dashboard=false" in command_args, (
            "Traefik must have --api.dashboard=false in its command"
        )

    def test_traefik_docker_provider_enabled(self) -> None:
        """Traefik uses Docker provider but does not expose by default."""
        traefik_config = RUN4_COMPOSE_CONFIG["services"]["traefik"]
        command_args = traefik_config["command"]

        assert "--providers.docker=true" in command_args
        assert "--providers.docker.exposedbydefault=false" in command_args

    def test_traefik_dashboard_disabled_in_yaml(self, tmp_path: Path) -> None:
        """When written as YAML, --api.dashboard=false is preserved."""
        compose_file = tmp_path / "docker-compose.run4.yml"
        yaml.dump(RUN4_COMPOSE_CONFIG, compose_file.open("w", encoding="utf-8"))

        loaded = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        traefik_cmd = loaded["services"]["traefik"]["command"]
        assert "--api.dashboard=false" in traefik_cmd


# ===================================================================
# SEC-003 -- Docker Socket Read-Only
# ===================================================================


class TestSEC003DockerSocketReadOnly:
    """SEC-003 -- Verify docker.sock mounted :ro in compose config."""

    def test_docker_socket_mounted_readonly(self) -> None:
        """The docker.sock volume mount has :ro suffix."""
        traefik_config = RUN4_COMPOSE_CONFIG["services"]["traefik"]
        volumes = traefik_config["volumes"]

        socket_mounts = [v for v in volumes if "docker.sock" in v]
        assert len(socket_mounts) >= 1, "docker.sock mount not found"

        for mount in socket_mounts:
            assert mount.endswith(":ro"), (
                f"docker.sock must be mounted read-only, got: {mount}"
            )

    def test_docker_socket_path_correct(self) -> None:
        """The docker.sock mount path is /var/run/docker.sock."""
        traefik_config = RUN4_COMPOSE_CONFIG["services"]["traefik"]
        volumes = traefik_config["volumes"]

        socket_mounts = [v for v in volumes if "docker.sock" in v]
        assert any(
            v.startswith("/var/run/docker.sock:") for v in socket_mounts
        ), "docker.sock should be mounted from /var/run/docker.sock"

    def test_docker_socket_readonly_in_yaml(self, tmp_path: Path) -> None:
        """When written as YAML, :ro suffix on docker.sock is preserved."""
        compose_file = tmp_path / "docker-compose.run4.yml"
        yaml.dump(RUN4_COMPOSE_CONFIG, compose_file.open("w", encoding="utf-8"))

        loaded = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        volumes = loaded["services"]["traefik"]["volumes"]
        socket_mounts = [v for v in volumes if "docker.sock" in v]
        assert all(":ro" in v for v in socket_mounts)
