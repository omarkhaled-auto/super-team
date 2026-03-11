"""Conftest for infrastructure generation tests.

Shared fixtures for compose health checks, env vars, Dockerfile templates,
CLAUDE.md generation, and pre-deploy validation tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.build3_shared.models import ServiceInfo
from src.integrator.compose_generator import ComposeGenerator


# ---------------------------------------------------------------------------
# Patch state machine on_enter callbacks (same pattern as test_attempt13)
# ---------------------------------------------------------------------------
_PATCHED_STATES: list[str] = [
    "init",
    "architect_running",
    "architect_review",
    "contracts_registering",
    "builders_running",
    "builders_complete",
    "integrating",
    "quality_gate",
    "fix_pass",
    "complete",
    "failed",
]


@pytest.fixture(autouse=True)
def _patch_state_machine_states():
    """Remove on_enter callbacks from state machine states globally for tests."""
    with patch("src.super_orchestrator.state_machine.STATES", _PATCHED_STATES):
        yield


@pytest.fixture(autouse=True)
def _ensure_cost_tracker_shims():
    """Add backward-compatible shim methods to PipelineCostTracker."""
    from src.super_orchestrator.cost import PipelineCostTracker

    _current_phase: dict[int, str] = {}

    if not hasattr(PipelineCostTracker, "start_phase"):
        def _start_phase(self, phase: str) -> None:
            _current_phase[id(self)] = phase
            self.add_phase_cost(phase, 0.0)
        PipelineCostTracker.start_phase = _start_phase  # type: ignore[attr-defined]

    if not hasattr(PipelineCostTracker, "end_phase"):
        def _end_phase(self, cost: float) -> None:
            phase = _current_phase.pop(id(self), None)
            if phase:
                self.add_phase_cost(phase, cost)
        PipelineCostTracker.end_phase = _end_phase  # type: ignore[attr-defined]

    if not hasattr(PipelineCostTracker, "phase_costs"):
        @property  # type: ignore[misc]
        def _phase_costs(self) -> dict[str, float]:
            return {name: p.cost_usd for name, p in self.phases.items()}
        PipelineCostTracker.phase_costs = _phase_costs  # type: ignore[attr-defined]

    yield


@pytest.fixture(autouse=True)
def _patch_builder_config_compat():
    """Add backward-compatible 'timeout' alias to BuilderConfig."""
    from src.super_orchestrator.config import BuilderConfig

    if not hasattr(BuilderConfig, "timeout"):
        @property  # type: ignore[misc]
        def _timeout(self) -> int:
            return self.timeout_per_builder
        BuilderConfig.timeout = _timeout  # type: ignore[attr-defined]

    yield

    if hasattr(BuilderConfig, "timeout"):
        try:
            delattr(BuilderConfig, "timeout")
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# Service fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def generator() -> ComposeGenerator:
    """Create a default ComposeGenerator."""
    return ComposeGenerator()


@pytest.fixture
def python_service() -> ServiceInfo:
    """Mock service info for a Python/FastAPI backend."""
    return ServiceInfo(
        service_id="auth-service",
        domain="authentication",
        stack={"language": "python", "framework": "fastapi"},
        port=8000,
        health_endpoint="/api/auth-service/health",
    )


@pytest.fixture
def nestjs_service() -> ServiceInfo:
    """Mock service info for a NestJS/TypeScript backend."""
    return ServiceInfo(
        service_id="accounts-service",
        domain="accounts",
        stack={"language": "typescript", "framework": "nestjs"},
        port=8080,
        health_endpoint="/api/accounts-service/health",
    )


@pytest.fixture
def frontend_service() -> ServiceInfo:
    """Mock service info for an Angular frontend."""
    return ServiceInfo(
        service_id="frontend",
        domain="ui",
        stack={"language": "typescript", "framework": "angular"},
        port=80,
        health_endpoint="/",
    )


@pytest.fixture
def express_service() -> ServiceInfo:
    """Mock service info for an Express.js backend."""
    return ServiceInfo(
        service_id="notification-service",
        domain="notifications",
        stack={"language": "typescript", "framework": "express"},
        port=3000,
        health_endpoint="/api/notification-service/health",
    )


@pytest.fixture
def all_services(
    python_service: ServiceInfo,
    nestjs_service: ServiceInfo,
    frontend_service: ServiceInfo,
) -> list[ServiceInfo]:
    """All three service types for multi-service tests."""
    return [python_service, nestjs_service, frontend_service]
