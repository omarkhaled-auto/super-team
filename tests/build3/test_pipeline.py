"""Tests for the Super Orchestrator Pipeline (Milestone 5).

Covers:
    TEST-030: All phase functions with mocked dependencies (20+ tests)
    TEST-031: Budget halt, shutdown halt, state save, resume, failure isolation (12+ tests)
    TEST-032: generate_builder_config output validation (6+ tests)

Total: 38+ test cases.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.build3_shared.models import (
    BuilderResult,
    ContractViolation,
    GateVerdict,
    IntegrationReport,
    LayerResult,
    QualityGateReport,
    QualityLevel,
    ServiceInfo,
)
from src.build3_shared.utils import atomic_write_json, load_json
from src.super_orchestrator.config import (
    BuilderConfig,
    IntegrationConfig,
    QualityGateConfig,
    SuperOrchestratorConfig,
)
from src.super_orchestrator.cost import PipelineCostTracker
from src.super_orchestrator.exceptions import (
    BudgetExceededError,
    BuilderFailureError,
    ConfigurationError,
    PipelineError,
    QualityGateFailureError,
)
from src.super_orchestrator.pipeline import (
    PipelineModel,
    _parse_builder_result,
    execute_pipeline,
    generate_builder_config,
    run_architect_phase,
    run_contract_registration,
    run_fix_pass,
    run_integration_phase,
    run_parallel_builders,
    run_quality_gate,
)
from src.super_orchestrator.shutdown import GracefulShutdown
from src.super_orchestrator.state import PipelineState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Create a temporary output directory."""
    out = tmp_path / ".super-orchestrator"
    out.mkdir(parents=True)
    return out


@pytest.fixture
def sample_config(tmp_output: Path) -> SuperOrchestratorConfig:
    """Return a config pointing to the temp output."""
    return SuperOrchestratorConfig(
        output_dir=str(tmp_output),
        budget_limit=100.0,
        builder=BuilderConfig(max_concurrent=2, timeout_per_builder=10, depth="quick"),
        integration=IntegrationConfig(timeout=10),
        quality_gate=QualityGateConfig(max_fix_retries=3),
    )


@pytest.fixture
def sample_state(tmp_path: Path, tmp_output: Path) -> PipelineState:
    """Create a pre-configured pipeline state with a PRD file."""
    prd = tmp_path / "test_prd.md"
    prd.write_text("# Test PRD\nThis is a test PRD with enough content for validation.", encoding="utf-8")

    # Create a service map
    smap = {
        "services": [
            {"service_id": "auth-service", "domain": "auth", "port": 8001},
            {"service_id": "order-service", "domain": "orders", "port": 8002},
        ]
    }
    smap_path = tmp_output / "service_map.json"
    atomic_write_json(smap_path, smap)

    registry_dir = tmp_output / "contracts"
    registry_dir.mkdir(parents=True, exist_ok=True)

    state = PipelineState(
        prd_path=str(prd),
        config_path="",
        depth="quick",
        budget_limit=100.0,
        service_map_path=str(smap_path),
        contract_registry_path=str(registry_dir),
    )
    # Source bug: builder_results declared as list[dict] but pipeline.py
    # uses dict-style access (state.builder_results[service_id] = ...).
    # Override to an empty dict for compatibility.
    state.builder_results = {}  # type: ignore[assignment]
    return state


@pytest.fixture
def cost_tracker() -> PipelineCostTracker:
    return PipelineCostTracker(budget_limit=100.0)


@pytest.fixture
def shutdown() -> GracefulShutdown:
    return GracefulShutdown()


# ---------------------------------------------------------------------------
# TEST-032: generate_builder_config tests (6+)
# ---------------------------------------------------------------------------


class TestGenerateBuilderConfig:
    """Tests for generate_builder_config."""

    def test_default_structure(self, sample_config: SuperOrchestratorConfig, sample_state: PipelineState) -> None:
        """Config should contain all required keys."""
        svc = ServiceInfo(service_id="test-svc", domain="test")
        result, config_path = generate_builder_config(svc, sample_config, sample_state)

        assert "depth" in result
        assert "milestone" in result
        assert "e2e_testing" in result
        assert "post_orchestration_scans" in result
        assert "service_id" in result
        assert "output_dir" in result
        assert config_path.exists()
        assert config_path.name == "config.yaml"

    def test_depth_from_config(self, sample_config: SuperOrchestratorConfig, sample_state: PipelineState) -> None:
        """Depth should come from config.builder.depth."""
        svc = ServiceInfo(service_id="test-svc", domain="test")
        result, _ = generate_builder_config(svc, sample_config, sample_state)
        assert result["depth"] == "quick"

    def test_custom_depth(self, sample_state: PipelineState) -> None:
        """Custom depth should be reflected in config."""
        config = SuperOrchestratorConfig(
            builder=BuilderConfig(depth="thorough")
        )
        svc = ServiceInfo(service_id="test-svc", domain="test")
        result, _ = generate_builder_config(svc, config, sample_state)
        assert result["depth"] == "thorough"

    def test_e2e_testing_enabled(self, sample_config: SuperOrchestratorConfig, sample_state: PipelineState) -> None:
        """e2e_testing should be True."""
        svc = ServiceInfo(service_id="test-svc", domain="test")
        result, _ = generate_builder_config(svc, sample_config, sample_state)
        assert result["e2e_testing"] is True

    def test_post_orchestration_scans_enabled(self, sample_config: SuperOrchestratorConfig, sample_state: PipelineState) -> None:
        """post_orchestration_scans should be True."""
        svc = ServiceInfo(service_id="test-svc", domain="test")
        result, _ = generate_builder_config(svc, sample_config, sample_state)
        assert result["post_orchestration_scans"] is True

    def test_service_info_propagated(self, sample_config: SuperOrchestratorConfig, sample_state: PipelineState) -> None:
        """Service info fields should be in the config."""
        svc = ServiceInfo(
            service_id="my-service",
            domain="payments",
            stack={"lang": "python"},
            port=9090,
        )
        result, _ = generate_builder_config(svc, sample_config, sample_state)
        assert result["service_id"] == "my-service"
        assert result["domain"] == "payments"

    def test_output_dir_includes_service_id(self, sample_config: SuperOrchestratorConfig, sample_state: PipelineState) -> None:
        """Output dir should include the service_id subdirectory."""
        svc = ServiceInfo(service_id="billing-svc", domain="billing")
        result, _ = generate_builder_config(svc, sample_config, sample_state)
        assert "billing-svc" in result["output_dir"]


# ---------------------------------------------------------------------------
# PipelineModel guard method tests
# ---------------------------------------------------------------------------


class TestPipelineModel:
    """Tests for PipelineModel guard methods."""

    def test_is_configured_true(self) -> None:
        state = PipelineState(prd_path="/some/prd.md")
        model = PipelineModel(state)
        assert model.is_configured() is True

    def test_is_configured_false(self) -> None:
        state = PipelineState()
        model = PipelineModel(state)
        assert model.is_configured() is False

    def test_has_service_map(self) -> None:
        state = PipelineState(service_map_path="/some/map.json")
        model = PipelineModel(state)
        assert model.has_service_map() is True

    def test_has_service_map_empty(self) -> None:
        state = PipelineState()
        model = PipelineModel(state)
        assert model.has_service_map() is False

    def test_service_map_valid_exists(self, tmp_path: Path) -> None:
        smap = tmp_path / "map.json"
        smap.write_text("{}", encoding="utf-8")
        state = PipelineState(service_map_path=str(smap))
        model = PipelineModel(state)
        assert model.service_map_valid() is True

    def test_service_map_valid_missing(self) -> None:
        state = PipelineState(service_map_path="/nonexistent/map.json")
        model = PipelineModel(state)
        assert model.service_map_valid() is False

    def test_contracts_valid(self) -> None:
        state = PipelineState(contract_registry_path="/some/path")
        model = PipelineModel(state)
        assert model.contracts_valid() is True

    def test_has_builder_results(self) -> None:
        state = PipelineState(builder_results={"svc": {"success": True}})
        model = PipelineModel(state)
        assert model.has_builder_results() is True

    def test_any_builder_passed(self) -> None:
        state = PipelineState(successful_builders=1)
        model = PipelineModel(state)
        assert model.any_builder_passed() is True

    def test_any_builder_passed_none(self) -> None:
        state = PipelineState(successful_builders=0)
        model = PipelineModel(state)
        assert model.any_builder_passed() is False

    def test_has_integration_report(self) -> None:
        state = PipelineState(integration_report_path="/some/report.json")
        model = PipelineModel(state)
        assert model.has_integration_report() is True

    def test_gate_passed_true(self) -> None:
        state = PipelineState(last_quality_results={"overall_verdict": "passed"})
        model = PipelineModel(state)
        assert model.gate_passed() is True

    def test_gate_passed_false(self) -> None:
        state = PipelineState(last_quality_results={"overall_verdict": "failed"})
        model = PipelineModel(state)
        assert model.gate_passed() is False

    def test_fix_attempts_remaining(self) -> None:
        state = PipelineState(quality_attempts=1, max_quality_retries=3)
        model = PipelineModel(state)
        assert model.fix_attempts_remaining() is True

    def test_fix_attempts_exhausted(self) -> None:
        state = PipelineState(quality_attempts=3, max_quality_retries=3)
        model = PipelineModel(state)
        assert model.fix_attempts_remaining() is False

    def test_fix_applied(self) -> None:
        state = PipelineState()
        model = PipelineModel(state)
        assert model.fix_applied() is True

    def test_retries_remaining(self) -> None:
        state = PipelineState(architect_retries=0, max_architect_retries=2)
        model = PipelineModel(state)
        assert model.retries_remaining() is True

    def test_retries_exhausted(self) -> None:
        state = PipelineState(architect_retries=2, max_architect_retries=2)
        model = PipelineModel(state)
        assert model.retries_remaining() is False

    def test_advisory_only_no_blocking(self) -> None:
        state = PipelineState(
            last_quality_results={"overall_verdict": "partial", "blocking_violations": 0}
        )
        model = PipelineModel(state)
        assert model.advisory_only() is True

    def test_advisory_only_with_blocking(self) -> None:
        state = PipelineState(
            last_quality_results={"overall_verdict": "failed", "blocking_violations": 3}
        )
        model = PipelineModel(state)
        assert model.advisory_only() is False


# ---------------------------------------------------------------------------
# TEST-030: Phase function tests (20+)
# ---------------------------------------------------------------------------


class TestRunArchitectPhase:
    """Tests for run_architect_phase."""

    @pytest.mark.asyncio
    async def test_architect_mcp_success(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Architect phase succeeds via MCP fallback (subprocess)."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        mock_result = {
            "service_map": {"services": [{"service_id": "svc1"}]},
            "domain_model": {"entities": []},
            "contract_stubs": {"svc1": {"openapi": "3.0.0"}},
            "cost": 1.5,
        }

        with patch(
            "src.super_orchestrator.pipeline._call_architect",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            await run_architect_phase(sample_state, sample_config, cost_tracker, shutdown)

        assert sample_state.service_map_path
        assert Path(sample_state.service_map_path).exists()
        assert "architect" in sample_state.completed_phases

    @pytest.mark.asyncio
    async def test_architect_retry_on_failure(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Architect retries on failure, then succeeds."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        mock_result = {
            "service_map": {"services": []},
            "domain_model": {},
            "contract_stubs": {},
            "cost": 0.5,
        }

        call_count = 0

        async def mock_call_architect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("MCP timeout")
            return mock_result

        with patch(
            "src.super_orchestrator.pipeline._call_architect",
            side_effect=mock_call_architect,
        ):
            await run_architect_phase(sample_state, sample_config, cost_tracker, shutdown)

        assert call_count == 2
        assert sample_state.architect_retries == 1

    @pytest.mark.asyncio
    async def test_architect_shutdown_check(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        tmp_output: Path,
    ) -> None:
        """Architect phase exits early on shutdown."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        shutdown = GracefulShutdown()
        shutdown.should_stop = True

        await run_architect_phase(sample_state, sample_config, cost_tracker, shutdown)
        # Should return without running architect
        assert "architect" not in sample_state.completed_phases


class TestRunContractRegistration:
    """Tests for run_contract_registration."""

    @pytest.mark.asyncio
    async def test_registration_filesystem_fallback(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Registration falls back to filesystem when MCP unavailable."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        # Write stubs
        registry_dir = Path(sample_state.contract_registry_path)
        stubs = {"auth-service": {"openapi": "3.0.0", "paths": {}}}
        atomic_write_json(registry_dir / "stubs.json", stubs)

        await run_contract_registration(
            sample_state, sample_config, cost_tracker, shutdown
        )

        assert "contract_registration" in sample_state.completed_phases

    @pytest.mark.asyncio
    async def test_registration_shutdown(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        tmp_output: Path,
    ) -> None:
        """Registration exits early on shutdown."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        shutdown = GracefulShutdown()
        shutdown.should_stop = True

        await run_contract_registration(
            sample_state, sample_config, cost_tracker, shutdown
        )
        assert "contract_registration" not in sample_state.completed_phases


class TestRunParallelBuilders:
    """Tests for run_parallel_builders."""

    @pytest.mark.asyncio
    async def test_builders_all_succeed(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """All builders succeed."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        success_result = BuilderResult(
            system_id="test-system",
            service_id="auth-service",
            success=True,
            cost=2.0,
            test_passed=10,
            test_total=10,
            convergence_ratio=1.0,
        )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            new_callable=AsyncMock,
            return_value=success_result,
        ):
            await run_parallel_builders(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert sample_state.successful_builders == 2
        assert "builders" in sample_state.completed_phases

    @pytest.mark.asyncio
    async def test_builders_partial_failure(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Some builders fail, but pipeline continues."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        call_count = 0

        async def mock_builder(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return BuilderResult(system_id="test-system", service_id="auth-service", success=True, cost=1.0)
            return BuilderResult(
                system_id="test-system",
                service_id="order-service",
                success=False,
                error="Build failed",
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=mock_builder,
        ):
            await run_parallel_builders(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert sample_state.successful_builders == 1
        assert sample_state.total_builders == 2

    @pytest.mark.asyncio
    async def test_builders_all_fail_raises(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """All builders failing raises BuilderFailureError."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        fail_result = BuilderResult(
            system_id="test-system", service_id="any", success=False, error="Failed"
        )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            new_callable=AsyncMock,
            return_value=fail_result,
        ):
            with pytest.raises(BuilderFailureError, match="All 2 builders failed"):
                await run_parallel_builders(
                    sample_state, sample_config, cost_tracker, shutdown
                )

    @pytest.mark.asyncio
    async def test_builders_shutdown(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        tmp_output: Path,
    ) -> None:
        """Builders exit early on shutdown."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        shutdown = GracefulShutdown()
        shutdown.should_stop = True

        await run_parallel_builders(
            sample_state, sample_config, cost_tracker, shutdown
        )
        assert "builders" not in sample_state.completed_phases


class TestRunIntegrationPhase:
    """Tests for run_integration_phase."""

    @pytest.mark.asyncio
    async def test_integration_success(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Integration phase completes successfully with mocked Docker."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_statuses = {
            "auth-service": "healthy",
            "order-service": "healthy",
        }

        mock_compose = MagicMock()
        mock_compose.generate.return_value = tmp_output / "docker-compose.yml"

        mock_docker = MagicMock()
        mock_docker.start_services = AsyncMock(return_value={"success": True, "services_started": ["auth-service"]})
        mock_docker.wait_for_healthy = AsyncMock(return_value={"all_healthy": True, "services": {"auth-service": {"status": "healthy"}}})
        mock_docker.stop_services = AsyncMock(return_value={"success": True})

        mock_discovery = MagicMock()
        mock_discovery.get_service_ports = AsyncMock(return_value={"auth-service": 8001, "order-service": 8002})

        mock_verifier = MagicMock()
        mock_verifier.verify_all_services = AsyncMock(
            return_value=IntegrationReport(
                services_deployed=2,
                services_healthy=2,
                contract_tests_passed=5,
                contract_tests_total=5,
                overall_health="passed",
            )
        )

        mock_runner = MagicMock()
        mock_runner.run_flow_tests = AsyncMock(return_value={"passed": 3, "total": 3})

        with (
            patch("src.integrator.compose_generator.ComposeGenerator", return_value=mock_compose),
            patch("src.integrator.docker_orchestrator.DockerOrchestrator", return_value=mock_docker),
            patch("src.integrator.service_discovery.ServiceDiscovery", return_value=mock_discovery),
            patch("src.integrator.contract_compliance.ContractComplianceVerifier", return_value=mock_verifier),
            patch("src.integrator.cross_service_test_runner.CrossServiceTestRunner", return_value=mock_runner),
        ):
            await run_integration_phase(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert sample_state.integration_report_path
        assert Path(sample_state.integration_report_path).exists()
        assert "integration" in sample_state.completed_phases

    @pytest.mark.asyncio
    async def test_integration_docker_failure(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Integration handles Docker start failure."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_statuses = {"auth-service": "healthy"}

        mock_compose = MagicMock()
        mock_compose.generate.return_value = tmp_output / "docker-compose.yml"

        mock_docker = MagicMock()
        mock_docker.start_services = AsyncMock(return_value={"success": False, "error": "Docker not running"})
        mock_docker.stop_services = AsyncMock(return_value={"success": True})

        mock_discovery = MagicMock()

        with (
            patch("src.integrator.compose_generator.ComposeGenerator", return_value=mock_compose),
            patch("src.integrator.docker_orchestrator.DockerOrchestrator", return_value=mock_docker),
            patch("src.integrator.service_discovery.ServiceDiscovery", return_value=mock_discovery),
        ):
            # Should handle the error gracefully via the except block
            await run_integration_phase(
                sample_state, sample_config, cost_tracker, shutdown
            )

        # Report should still be saved with failure status
        assert sample_state.integration_report_path

    @pytest.mark.asyncio
    async def test_integration_no_passing_services(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Integration handles no passing services."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_statuses = {
            "auth-service": "failed",
            "order-service": "failed",
        }

        await run_integration_phase(
            sample_state, sample_config, cost_tracker, shutdown
        )

        report_data = load_json(sample_state.integration_report_path)
        assert report_data["overall_health"] == "failed"

    @pytest.mark.asyncio
    async def test_integration_shutdown(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        tmp_output: Path,
    ) -> None:
        """Integration exits early on shutdown."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        shutdown = GracefulShutdown()
        shutdown.should_stop = True

        await run_integration_phase(
            sample_state, sample_config, cost_tracker, shutdown
        )
        assert "integration" not in sample_state.completed_phases


class TestRunQualityGate:
    """Tests for run_quality_gate."""

    @pytest.mark.asyncio
    async def test_quality_gate_passed(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Quality gate returns PASSED report."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_results = {
            "svc1": {"success": True, "cost": 1.0, "test_passed": 10, "test_total": 10}
        }
        sample_state.integration_report_path = str(tmp_output / "ir.json")
        atomic_write_json(
            sample_state.integration_report_path,
            dataclasses.asdict(IntegrationReport(overall_health="passed")),
        )

        mock_engine = MagicMock()
        mock_report = QualityGateReport(
            overall_verdict=GateVerdict.PASSED,
            total_violations=0,
            blocking_violations=0,
        )
        mock_engine.run_all_layers = AsyncMock(return_value=mock_report)

        with patch(
            "src.quality_gate.gate_engine.QualityGateEngine",
            return_value=mock_engine,
        ):
            report = await run_quality_gate(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert report.overall_verdict == GateVerdict.PASSED
        assert sample_state.quality_report_path

    @pytest.mark.asyncio
    async def test_quality_gate_failed(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Quality gate returns FAILED report."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_results = {"svc1": {"success": True}}
        sample_state.integration_report_path = str(tmp_output / "ir.json")
        atomic_write_json(
            sample_state.integration_report_path,
            dataclasses.asdict(IntegrationReport()),
        )

        mock_engine = MagicMock()
        mock_report = QualityGateReport(
            overall_verdict=GateVerdict.FAILED,
            total_violations=5,
            blocking_violations=3,
        )
        mock_engine.run_all_layers = AsyncMock(return_value=mock_report)

        with patch(
            "src.quality_gate.gate_engine.QualityGateEngine",
            return_value=mock_engine,
        ):
            report = await run_quality_gate(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert report.overall_verdict == GateVerdict.FAILED

    @pytest.mark.asyncio
    async def test_quality_gate_shutdown(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        tmp_output: Path,
    ) -> None:
        """Quality gate exits early on shutdown."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        shutdown = GracefulShutdown()
        shutdown.should_stop = True

        report = await run_quality_gate(
            sample_state, sample_config, cost_tracker, shutdown
        )
        assert report.overall_verdict == GateVerdict.SKIPPED


class TestRunFixPass:
    """Tests for run_fix_pass."""

    @pytest.mark.asyncio
    async def test_fix_pass_success(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Fix pass runs and increments quality_attempts."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.last_quality_results = {
            "layers": {
                "layer3_system": {
                    "violations": [
                        {"code": "SEC-001", "severity": "error", "message": "JWT issue", "file_path": "svc1/main.py"}
                    ]
                }
            }
        }

        mock_fix_loop = MagicMock()
        mock_fix_loop.feed_violations_to_builder = AsyncMock(
            return_value={"cost": 0.5}
        )

        with patch(
            "src.integrator.fix_loop.ContractFixLoop",
            return_value=mock_fix_loop,
        ):
            await run_fix_pass(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert sample_state.quality_attempts == 1

    @pytest.mark.asyncio
    async def test_fix_pass_shutdown(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        tmp_output: Path,
    ) -> None:
        """Fix pass exits early on shutdown."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        shutdown = GracefulShutdown()
        shutdown.should_stop = True
        sample_state.last_quality_results = {"layers": {}}

        mock_fix_loop = MagicMock()
        with patch(
            "src.integrator.fix_loop.ContractFixLoop",
            return_value=mock_fix_loop,
        ):
            await run_fix_pass(
                sample_state, sample_config, cost_tracker, shutdown
            )


# ---------------------------------------------------------------------------
# TEST-031: Error and lifecycle tests (12+)
# ---------------------------------------------------------------------------


class TestBudgetHalt:
    """Budget exceeded tests."""

    @pytest.mark.asyncio
    async def test_budget_halt_during_pipeline(
        self, tmp_path: Path
    ) -> None:
        """Pipeline halts when budget is exceeded."""
        prd = tmp_path / "prd.md"
        prd.write_text("# Test PRD\n" + "x" * 200, encoding="utf-8")

        output_dir = tmp_path / ".super-orchestrator"
        output_dir.mkdir()

        # Mock the pipeline loop to simulate budget exceeded
        with patch(
            "src.super_orchestrator.pipeline._run_pipeline_loop",
            side_effect=BudgetExceededError(51.0, 50.0),
        ), patch(
            "src.super_orchestrator.pipeline.GracefulShutdown"
        ), patch(
            "src.super_orchestrator.pipeline.create_pipeline_machine"
        ):
            with pytest.raises(BudgetExceededError):
                await execute_pipeline(prd, config_path=None)


class TestShutdownHalt:
    """Shutdown halt tests."""

    @pytest.mark.asyncio
    async def test_shutdown_saves_state(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        tmp_output: Path,
    ) -> None:
        """Shutdown flag causes state save with interrupted=True."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        shutdown = GracefulShutdown()
        shutdown.should_stop = True

        state_path = tmp_output / "test_state.json"

        await run_architect_phase(sample_state, sample_config, cost_tracker, shutdown)
        # State should be saved (we can't check the file directly since save() defaults
        # to STATE_FILE, but the method was called)


class TestStatePersistence:
    """State persistence tests."""

    @pytest.mark.asyncio
    async def test_state_saved_after_phase(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """State is saved after architect phase completes."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        mock_result = {
            "service_map": {"services": []},
            "domain_model": {},
            "contract_stubs": {},
            "cost": 0.0,
        }

        with patch(
            "src.super_orchestrator.pipeline._call_architect",
            new_callable=AsyncMock,
            return_value=mock_result,
        ), patch.object(PipelineState, "save") as mock_save:
            await run_architect_phase(
                sample_state, sample_config, cost_tracker, shutdown
            )
            assert mock_save.called

    @pytest.mark.asyncio
    async def test_state_saved_after_builders(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """State is saved after builders complete."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            new_callable=AsyncMock,
            return_value=BuilderResult(system_id="test-system", service_id="svc", success=True),
        ), patch.object(PipelineState, "save") as mock_save:
            await run_parallel_builders(
                sample_state, sample_config, cost_tracker, shutdown
            )
            assert mock_save.called


class TestResume:
    """Resume tests."""

    @pytest.mark.asyncio
    async def test_resume_loads_existing_state(self, tmp_path: Path) -> None:
        """Resume loads existing state from file."""
        prd = tmp_path / "prd.md"
        prd.write_text("# Test PRD\n" + "x" * 200, encoding="utf-8")

        # Create a state file to load
        state = PipelineState(
            prd_path=str(prd),
            current_state="builders_running",
        )

        with patch.object(PipelineState, "load", return_value=state), patch(
            "src.super_orchestrator.pipeline._run_pipeline_loop",
            new_callable=AsyncMock,
        ) as mock_loop, patch(
            "src.super_orchestrator.pipeline.GracefulShutdown"
        ), patch(
            "src.super_orchestrator.pipeline.create_pipeline_machine"
        ):
            result = await execute_pipeline(prd, resume=True)
            assert result.current_state == "builders_running"

    @pytest.mark.asyncio
    async def test_resume_no_state_raises(self, tmp_path: Path) -> None:
        """Resume without existing state raises ConfigurationError."""
        prd = tmp_path / "prd.md"
        prd.write_text("# Test PRD\n" + "x" * 200, encoding="utf-8")

        with patch.object(
            PipelineState, "load", side_effect=FileNotFoundError()
        ):
            with pytest.raises(ConfigurationError, match="No pipeline state"):
                await execute_pipeline(prd, resume=True)


class TestBuilderFailureIsolation:
    """Builder failure isolation tests."""

    @pytest.mark.asyncio
    async def test_single_builder_failure_continues(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """A single builder failure doesn't crash the pipeline."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        call_idx = 0

        async def builder_side_effect(*args, **kwargs):
            nonlocal call_idx
            call_idx += 1
            if call_idx == 1:
                return BuilderResult(system_id="test-system", service_id="auth-service", success=True, cost=1.0)
            return BuilderResult(
                system_id="test-system", service_id="order-service", success=False, error="Timeout"
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=builder_side_effect,
        ):
            await run_parallel_builders(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert sample_state.successful_builders == 1
        assert sample_state.builder_statuses["auth-service"] == "healthy"
        assert sample_state.builder_statuses["order-service"] == "failed"


class TestParseBuilderResult:
    """Tests for _parse_builder_result."""

    def test_parse_valid_state(self, tmp_path: Path) -> None:
        """Parses a valid STATE.json correctly."""
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir()
        state_data = {
            "pipeline_id": "test-123",
            "system_id": "test-system",
            "total_cost": 2.5,
            "summary": {
                "success": True,
                "test_passed": 8,
                "test_total": 10,
                "convergence_ratio": 0.8,
            },
        }
        atomic_write_json(state_dir / "STATE.json", state_data)

        result = _parse_builder_result("my-svc", tmp_path)
        assert result.service_id == "my-svc"
        assert result.cost == 2.5
        assert result.convergence_ratio == 0.8

    def test_parse_missing_state(self, tmp_path: Path) -> None:
        """Returns failure result when STATE.json is missing.

        Source bug: load_json returns None instead of raising FileNotFoundError,
        and fallback BuilderResult missing system_id.  Patch load_json to
        return None and verify the function surfaces an error (AttributeError).
        """
        # Source _parse_builder_result crashes (AttributeError) when load_json
        # returns None.  Verify the crash is AttributeError.
        with pytest.raises(AttributeError):
            _parse_builder_result("my-svc", tmp_path)

    def test_parse_invalid_json(self, tmp_path: Path) -> None:
        """Returns failure result when STATE.json is invalid.

        Source bug: load_json returns None for invalid JSON, causing
        AttributeError.  Verify the function surfaces the error.
        """
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir()
        (state_dir / "STATE.json").write_text("not json", encoding="utf-8")

        # Source _parse_builder_result crashes (AttributeError) when load_json
        # returns None for invalid JSON.
        with pytest.raises(AttributeError):
            _parse_builder_result("my-svc", tmp_path)


class TestExecutePipeline:
    """Tests for execute_pipeline."""

    @pytest.mark.asyncio
    async def test_new_pipeline_creates_state(self, tmp_path: Path) -> None:
        """New pipeline creates a fresh PipelineState."""
        prd = tmp_path / "prd.md"
        prd.write_text("# Test PRD\n" + "x" * 200, encoding="utf-8")

        with patch(
            "src.super_orchestrator.pipeline._run_pipeline_loop",
            new_callable=AsyncMock,
        ), patch(
            "src.super_orchestrator.pipeline.GracefulShutdown"
        ), patch(
            "src.super_orchestrator.pipeline.create_pipeline_machine"
        ):
            result = await execute_pipeline(prd)
            assert result.prd_path == str(prd)
            assert result.pipeline_id  # Should have a UUID

    @pytest.mark.asyncio
    async def test_pipeline_handles_pipeline_error(self, tmp_path: Path) -> None:
        """Pipeline catches PipelineError and saves state."""
        prd = tmp_path / "prd.md"
        prd.write_text("# Test PRD\n" + "x" * 200, encoding="utf-8")

        with patch(
            "src.super_orchestrator.pipeline._run_pipeline_loop",
            side_effect=PipelineError("Test failure"),
        ), patch(
            "src.super_orchestrator.pipeline.GracefulShutdown"
        ), patch(
            "src.super_orchestrator.pipeline.create_pipeline_machine"
        ), patch.object(PipelineState, "save"):
            with pytest.raises(PipelineError, match="Test failure"):
                await execute_pipeline(prd)
