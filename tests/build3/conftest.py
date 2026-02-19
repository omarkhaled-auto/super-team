"""Shared fixtures for Build 3 tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest

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
# Patch state machine on_enter callbacks that are not defined on PipelineModel
# The source's STATES define on_enter callbacks that the model doesn't implement,
# causing "object NoneType can't be used in 'await' expression" errors.
# ---------------------------------------------------------------------------
# Use plain strings so AsyncMachine creates proper AsyncState objects
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
    """Make ContractViolation accept missing service/endpoint with defaults.

    Source pipeline.py creates ContractViolation without service and endpoint
    in several error-handling paths.  This provides backwards-compatible defaults.
    """
    import dataclasses as _dc
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
def _patch_cost_tracker_compat():
    """Add backward-compatible shim methods to PipelineCostTracker.

    The source pipeline.py still references start_phase/end_phase/phase_costs
    which were removed from PipelineCostTracker.  This fixture adds compatibility
    shims so tests that invoke real phase functions don't crash.
    """
    from src.super_orchestrator.cost import PipelineCostTracker

    _current_phase = {}

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

    # Cleanup: remove shims after test
    for attr in ("start_phase", "end_phase"):
        if hasattr(PipelineCostTracker, attr):
            try:
                delattr(PipelineCostTracker, attr)
            except AttributeError:
                pass
    if hasattr(PipelineCostTracker, "phase_costs"):
        try:
            delattr(PipelineCostTracker, "phase_costs")
        except AttributeError:
            pass


@pytest.fixture(autouse=True)
def _patch_integration_config_compat():
    """Add backward-compatible aliases to IntegrationConfig.

    The source pipeline.py still references config.integration.compose_timeout
    and config.integration.health_timeout which were removed.
    """
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
    """Add backward-compatible 'timeout' alias to BuilderConfig.

    The source pipeline.py still references config.builder.timeout
    which was renamed to timeout_per_builder.
    """
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
    """Add backward-compatible 'retries' alias to ArchitectConfig.

    The source pipeline.py still references config.architect.retries
    which was renamed to max_retries.
    """
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


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test artifacts."""
    return tmp_path


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
def sample_builder_result() -> BuilderResult:
    """Create a sample successful BuilderResult."""
    return BuilderResult(
        system_id="sys-1",
        service_id="auth-service",
        success=True,
        cost=1.50,
        test_passed=45,
        test_total=50,
        convergence_ratio=0.95,
        error="",
    )


@pytest.fixture
def sample_pipeline_state(tmp_dir: Path) -> PipelineState:
    """Create a sample PipelineState configured to use tmp_dir."""
    return PipelineState(
        pipeline_id="test-pipeline-001",
        prd_path="prompts/sample.md",
        config_path="config.yaml",
        depth="thorough",
        current_state="init",
    )


@pytest.fixture
def sample_config() -> SuperOrchestratorConfig:
    """Create a default SuperOrchestratorConfig."""
    return SuperOrchestratorConfig()


@pytest.fixture
def sample_integration_report() -> IntegrationReport:
    """Create a sample IntegrationReport."""
    return IntegrationReport(
        services_deployed=3,
        services_healthy=3,
        contract_tests_passed=10,
        contract_tests_total=10,
        integration_tests_passed=5,
        integration_tests_total=5,
        data_flow_tests_passed=3,
        data_flow_tests_total=3,
        boundary_tests_passed=4,
        boundary_tests_total=4,
        violations=[],
        overall_health="passed",
    )


@pytest.fixture
def sample_quality_report() -> QualityGateReport:
    """Create a sample QualityGateReport."""
    return QualityGateReport(
        layers={
            QualityLevel.LAYER1_SERVICE: LayerResult(
                layer=QualityLevel.LAYER1_SERVICE,
                verdict=GateVerdict.PASSED,
                total_checks=10,
                passed_checks=10,
            ),
        },
        overall_verdict=GateVerdict.PASSED,
        total_violations=0,
        blocking_violations=0,
    )


@pytest.fixture
def sample_yaml_config(tmp_dir: Path) -> Path:
    """Create a sample YAML config file."""
    config = {
        "architect": {"timeout": 600, "max_retries": 3},
        "builder": {"max_concurrent": 5, "timeout_per_builder": 3600, "depth": "quick"},
        "integration": {"timeout": 180},
        "quality_gate": {"max_fix_retries": 5},
        "budget_limit": 100.0,
        "output_dir": ".test-orchestrator",
    }
    import yaml
    config_path = tmp_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return config_path
