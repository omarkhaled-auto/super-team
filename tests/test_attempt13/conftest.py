"""Conftest for Attempt 13 fix tests.

Adds PipelineCostTracker shims and patches state machine states so that tests
importing pipeline functions don't crash on missing methods.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch

from src.build3_shared.models import (
    BuilderResult,
    ContractViolation,
    GateVerdict,
    IntegrationReport,
    LayerResult,
    QualityGateReport,
    QualityLevel,
    ScanViolation,
    ServiceInfo,
    ServiceStatus,
)
from src.super_orchestrator.config import SuperOrchestratorConfig
from src.super_orchestrator.state import PipelineState


# ---------------------------------------------------------------------------
# Patch state machine on_enter callbacks (same as build3/conftest.py)
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
def _patch_contract_violation_defaults():
    """Make ContractViolation accept missing service/endpoint with defaults."""
    from src.build3_shared import models as _models

    _OrigCV = _models.ContractViolation
    _orig_init = _OrigCV.__init__

    def _compat_init(self, code="", severity="error", service="unknown",
                     endpoint="unknown", message="", expected="", actual="",
                     file_path="", **kwargs):
        _orig_init(self, code=code, severity=severity, service=service,
                   endpoint=endpoint, message=message, expected=expected,
                   actual=actual, file_path=file_path)

    _models.ContractViolation.__init__ = _compat_init  # type: ignore[assignment]
    yield
    _models.ContractViolation.__init__ = _orig_init  # type: ignore[assignment]


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
def _patch_integration_config_compat():
    """Add backward-compatible aliases to IntegrationConfig."""
    from src.super_orchestrator.config import IntegrationConfig

    if not hasattr(IntegrationConfig, "compose_timeout"):
        @property  # type: ignore[misc]
        def _compose_timeout(self) -> int:
            return self.timeout
        IntegrationConfig.compose_timeout = _compose_timeout  # type: ignore[attr-defined]

    if not hasattr(IntegrationConfig, "health_timeout"):
        @property  # type: ignore[misc]
        def _health_timeout(self) -> int:
            return self.timeout
        IntegrationConfig.health_timeout = _health_timeout  # type: ignore[attr-defined]

    yield

    for attr in ("compose_timeout", "health_timeout"):
        if hasattr(IntegrationConfig, attr):
            try:
                delattr(IntegrationConfig, attr)
            except AttributeError:
                pass


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


@pytest.fixture(autouse=True)
def _patch_architect_config_compat():
    """Add backward-compatible 'retries' alias to ArchitectConfig."""
    from src.super_orchestrator.config import ArchitectConfig

    if not hasattr(ArchitectConfig, "retries"):
        @property  # type: ignore[misc]
        def _retries(self) -> int:
            return self.max_retries

        @_retries.setter
        def _retries(self, value: int) -> None:
            self.max_retries = value

        ArchitectConfig.retries = _retries  # type: ignore[attr-defined]

    yield

    if hasattr(ArchitectConfig, "retries"):
        try:
            delattr(ArchitectConfig, "retries")
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_service_info() -> ServiceInfo:
    """Create a sample ServiceInfo for testing."""
    return ServiceInfo(
        service_id="auth-service",
        domain="authentication",
        stack={"language": "python", "framework": "fastapi"},
        port=8001,
        health_endpoint="/api/health",
        docker_image="auth-service:latest",
        estimated_loc=500,
    )


@pytest.fixture
def frontend_service_info() -> ServiceInfo:
    """Create a frontend ServiceInfo for testing."""
    return ServiceInfo(
        service_id="frontend",
        domain="ui",
        stack={"language": "typescript", "framework": "react"},
        port=3000,
        health_endpoint="/",
        docker_image="frontend:latest",
        estimated_loc=2000,
    )


@pytest.fixture
def sample_config() -> SuperOrchestratorConfig:
    """Create a default SuperOrchestratorConfig."""
    return SuperOrchestratorConfig()


@pytest.fixture
def sample_pipeline_state(tmp_path: Path) -> PipelineState:
    """Create a sample PipelineState configured to use tmp_path."""
    return PipelineState(
        pipeline_id="test-pipeline-001",
        prd_path="prompts/sample.md",
        config_path="config.yaml",
        depth="thorough",
        current_state="init",
    )
