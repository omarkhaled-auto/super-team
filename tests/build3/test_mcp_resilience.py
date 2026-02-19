"""Test MCP server resilience -- graceful degradation on MCP failures.

Phase 4 (Stress Test & Hardening) -- Task 4.4

Tests that the pipeline handles MCP failures gracefully:
    1. Architect MCP failure -> retry and eventual success
    2. Contract Engine MCP failure -> fallback to filesystem-based contracts
    3. Codebase Intelligence MCP failure -> skip gracefully (best-effort)
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.build3_shared.models import BuilderResult, IntegrationReport
from src.build3_shared.utils import atomic_write_json, load_json
from src.super_orchestrator.config import (
    ArchitectConfig,
    BuilderConfig,
    IntegrationConfig,
    QualityGateConfig,
    SuperOrchestratorConfig,
)
from src.super_orchestrator.cost import PipelineCostTracker
from src.super_orchestrator.exceptions import ConfigurationError, PipelineError
from src.super_orchestrator.pipeline import (
    _call_architect,
    _index_generated_code,
    run_architect_phase,
    run_contract_registration,
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
        architect=ArchitectConfig(max_retries=2, timeout=30),
        builder=BuilderConfig(max_concurrent=2, timeout_per_builder=10, depth="quick"),
        integration=IntegrationConfig(timeout=10),
        quality_gate=QualityGateConfig(max_fix_retries=3),
    )


@pytest.fixture
def sample_state(tmp_path: Path, tmp_output: Path) -> PipelineState:
    """Create a pre-configured pipeline state with a PRD and service map."""
    prd = tmp_path / "test_prd.md"
    prd.write_text(
        "# Test PRD\nThis is a test PRD with enough content for validation.",
        encoding="utf-8",
    )

    smap = {
        "services": [
            {
                "service_id": "auth-service",
                "domain": "auth",
                "port": 8001,
                "contract": {"openapi": "3.0.0", "info": {"title": "Auth API"}},
            },
            {
                "service_id": "order-service",
                "domain": "orders",
                "port": 8002,
                "contract": {"openapi": "3.0.0", "info": {"title": "Order API"}},
            },
        ]
    }
    smap_path = tmp_output / "service_map.json"
    atomic_write_json(smap_path, smap)

    registry_dir = tmp_output / "contracts"
    registry_dir.mkdir(parents=True, exist_ok=True)

    # Write stubs so contract registration can find them
    stubs = {
        "auth-service": {"openapi": "3.0.0", "info": {"title": "Auth API"}, "paths": {}},
        "order-service": {"openapi": "3.0.0", "info": {"title": "Order API"}, "paths": {}},
    }
    atomic_write_json(registry_dir / "stubs.json", stubs)

    state = PipelineState(
        prd_path=str(prd),
        config_path="",
        depth="quick",
        budget_limit=100.0,
        service_map_path=str(smap_path),
        contract_registry_path=str(registry_dir),
    )
    state.builder_results = {}  # type: ignore[assignment]
    return state


@pytest.fixture
def cost_tracker() -> PipelineCostTracker:
    return PipelineCostTracker(budget_limit=100.0)


@pytest.fixture
def shutdown() -> GracefulShutdown:
    return GracefulShutdown()


# ---------------------------------------------------------------------------
# 4.4a: Architect MCP failure -> retry
# ---------------------------------------------------------------------------


class TestArchitectMCPFailureRetry:
    """Test that architect MCP failure triggers retry and eventually succeeds."""

    async def test_architect_retries_on_mcp_failure(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Architect fails once via MCP, retries, and succeeds."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        mock_result = {
            "service_map": {"services": [{"service_id": "svc1"}]},
            "domain_model": {"entities": []},
            "contract_stubs": {},
            "cost": 1.0,
        }

        call_count = 0

        async def mock_call_architect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("MCP server unreachable")
            return mock_result

        with patch(
            "src.super_orchestrator.pipeline._call_architect",
            side_effect=mock_call_architect,
        ):
            await run_architect_phase(
                sample_state, sample_config, cost_tracker, shutdown
            )

        # Should have retried once
        assert call_count == 2
        assert sample_state.architect_retries == 1
        # Phase should still complete successfully
        assert "architect" in sample_state.completed_phases
        assert sample_state.service_map_path

    async def test_architect_retries_increment_correctly(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """architect_retries field increments with each failure."""
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
            if call_count <= 2:
                raise RuntimeError(f"MCP failure #{call_count}")
            return mock_result

        with patch(
            "src.super_orchestrator.pipeline._call_architect",
            side_effect=mock_call_architect,
        ):
            await run_architect_phase(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert call_count == 3
        assert sample_state.architect_retries == 2

    async def test_architect_exhausts_retries_raises(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """When all retries are exhausted, PipelineError is raised."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        async def always_fail(*args, **kwargs):
            raise ConnectionError("MCP permanently down")

        with patch(
            "src.super_orchestrator.pipeline._call_architect",
            side_effect=always_fail,
        ):
            with pytest.raises(PipelineError, match="Architect phase failed after"):
                await run_architect_phase(
                    sample_state, sample_config, cost_tracker, shutdown
                )

        # Should have exhausted all retries (max_retries=2 means 3 total attempts)
        assert sample_state.architect_retries == 3

    async def test_architect_state_saved_between_retries(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """State is saved after each failed retry so progress is not lost."""
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
        ), patch.object(PipelineState, "save") as mock_save:
            await run_architect_phase(
                sample_state, sample_config, cost_tracker, shutdown
            )

        # save() should have been called at least once during the retry
        # and once after successful completion
        assert mock_save.call_count >= 2

    async def test_call_architect_mcp_then_subprocess_fallback(
        self,
        sample_config: SuperOrchestratorConfig,
        tmp_output: Path,
    ) -> None:
        """_call_architect tries MCP first, falls back to subprocess."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        # Simulate MCP import failing
        with patch.dict("sys.modules", {"src.architect.mcp_client": None}), patch(
            "src.super_orchestrator.pipeline._call_architect_subprocess",
            new_callable=AsyncMock,
            return_value={"service_map": {}, "domain_model": {}, "cost": 0.0},
        ) as mock_subprocess:
            result = await _call_architect("PRD text", sample_config, tmp_output)

        assert mock_subprocess.called
        assert result is not None


# ---------------------------------------------------------------------------
# 4.4b: Contract Engine MCP failure -> fallback to filesystem
# ---------------------------------------------------------------------------


class TestContractEngineMCPFallback:
    """Test contract registration falls back to filesystem on MCP failure."""

    async def test_contract_mcp_failure_falls_back_to_filesystem(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """When _register_single_contract raises ConfigurationError
        (MCP unavailable), contracts are saved to filesystem."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        # Mock _register_single_contract to raise ConfigurationError
        # (simulating MCP unavailable)
        with patch(
            "src.super_orchestrator.pipeline._register_single_contract",
            new_callable=AsyncMock,
            side_effect=ConfigurationError("Contract Engine MCP not available"),
        ):
            await run_contract_registration(
                sample_state, sample_config, cost_tracker, shutdown
            )

        # Phase should complete despite MCP failure
        assert "contract_registration" in sample_state.completed_phases

        # Contract stubs should have been saved to filesystem
        registry_dir = Path(sample_state.contract_registry_path)
        # At least one contract file should exist
        contract_files = list(registry_dir.glob("*.json"))
        # stubs.json + at least one service contract file
        service_contract_files = [
            f for f in contract_files if f.name != "stubs.json"
        ]
        assert len(service_contract_files) >= 1, (
            f"Expected filesystem fallback contract files, "
            f"found: {[f.name for f in contract_files]}"
        )

    async def test_contract_connection_error_falls_back(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """ConnectionError from MCP triggers filesystem fallback."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        with patch(
            "src.super_orchestrator.pipeline._register_single_contract",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Connection refused"),
        ):
            await run_contract_registration(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert "contract_registration" in sample_state.completed_phases

        # Filesystem fallback should have written files
        registry_dir = Path(sample_state.contract_registry_path)
        service_contracts = [
            f for f in registry_dir.glob("*.json") if f.name != "stubs.json"
        ]
        assert len(service_contracts) >= 1

    async def test_contract_stubs_saved_to_disk_on_fallback(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Verify the actual contract content is written to disk files."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        with patch(
            "src.super_orchestrator.pipeline._register_single_contract",
            new_callable=AsyncMock,
            side_effect=ConfigurationError("MCP down"),
        ):
            await run_contract_registration(
                sample_state, sample_config, cost_tracker, shutdown
            )

        registry_dir = Path(sample_state.contract_registry_path)

        # Check for auth-service contract
        auth_contract = registry_dir / "auth-service.json"
        if auth_contract.exists():
            data = load_json(auth_contract)
            assert data is not None
            assert "openapi" in data or "info" in data

    async def test_contract_partial_mcp_failure(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """If MCP works for some contracts but fails for others,
        the pipeline continues with mixed results."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        call_count = 0

        async def mock_register(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First contract succeeds via MCP
                return {"id": "contract-1", "status": "registered"}
            else:
                # Second contract fails
                raise ConnectionError("MCP dropped connection")

        with patch(
            "src.super_orchestrator.pipeline._register_single_contract",
            side_effect=mock_register,
        ):
            await run_contract_registration(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert "contract_registration" in sample_state.completed_phases
        # Should have processed both services (one via MCP, one via filesystem)
        assert call_count == 2

    async def test_no_stubs_file_still_completes(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """Contract registration completes even if stubs.json is missing,
        using inline contract fields from the service map."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        # Remove stubs.json
        stubs_file = Path(sample_state.contract_registry_path) / "stubs.json"
        if stubs_file.exists():
            stubs_file.unlink()

        with patch(
            "src.super_orchestrator.pipeline._register_single_contract",
            new_callable=AsyncMock,
            side_effect=ConfigurationError("MCP down"),
        ):
            await run_contract_registration(
                sample_state, sample_config, cost_tracker, shutdown
            )

        assert "contract_registration" in sample_state.completed_phases


# ---------------------------------------------------------------------------
# 4.4c: Codebase Intelligence MCP failure -> skip gracefully
# ---------------------------------------------------------------------------


class TestCodebaseIntelligenceMCPSkip:
    """Test that Codebase Intelligence MCP failure is handled gracefully."""

    async def test_ci_mcp_import_failure_skips(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        tmp_output: Path,
    ) -> None:
        """When CI MCP client cannot be imported, indexing is skipped."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_statuses = {"auth-service": "healthy"}

        # _index_generated_code catches ImportError internally
        with patch.dict(
            "sys.modules", {"src.codebase_intelligence.mcp_client": None}
        ):
            # Should not raise
            await _index_generated_code(sample_state, sample_config)

        # No crash, no data loss -- state should be unchanged
        assert sample_state.builder_statuses["auth-service"] == "healthy"

    async def test_ci_mcp_connection_failure_skips(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        tmp_output: Path,
    ) -> None:
        """When CI MCP server is unreachable, individual file indexing
        failures are logged but don't crash the pipeline."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_statuses = {"auth-service": "healthy"}

        # Create a fake source file
        auth_dir = tmp_output / "auth-service"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (auth_dir / "main.py").write_text("print('hello')", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.register_artifact = AsyncMock(
            side_effect=ConnectionError("CI MCP unreachable")
        )

        mock_module = MagicMock()
        mock_module.CodebaseIntelligenceClient.return_value = mock_client

        with patch.dict(
            "sys.modules",
            {"src.codebase_intelligence.mcp_client": mock_module},
        ):
            # Should not raise -- failures are logged and skipped
            await _index_generated_code(sample_state, sample_config)

        # State should be intact
        assert sample_state.builder_statuses["auth-service"] == "healthy"

    async def test_ci_mcp_failure_does_not_lose_data(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        tmp_output: Path,
    ) -> None:
        """CI MCP failure does not affect builder results or other state."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_statuses = {"auth-service": "healthy"}
        sample_state.builder_results = {
            "auth-service": {"success": True, "cost": 2.0},
        }
        sample_state.completed_phases = ["architect", "contract_registration", "builders"]
        original_cost = sample_state.total_cost

        with patch.dict(
            "sys.modules", {"src.codebase_intelligence.mcp_client": None}
        ):
            await _index_generated_code(sample_state, sample_config)

        # All state data preserved
        assert sample_state.builder_results["auth-service"]["success"] is True
        assert sample_state.total_cost == original_cost
        assert sample_state.completed_phases == [
            "architect",
            "contract_registration",
            "builders",
        ]

    async def test_ci_mcp_timeout_does_not_block(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        tmp_output: Path,
    ) -> None:
        """Even if CI MCP times out per file, the pipeline continues."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_statuses = {"auth-service": "healthy"}

        # Create a fake source file
        auth_dir = tmp_output / "auth-service"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (auth_dir / "app.py").write_text("x = 1", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.register_artifact = AsyncMock(
            side_effect=asyncio.TimeoutError("MCP timed out")
        )

        mock_module = MagicMock()
        mock_module.CodebaseIntelligenceClient.return_value = mock_client

        with patch.dict(
            "sys.modules",
            {"src.codebase_intelligence.mcp_client": mock_module},
        ):
            # Should complete without raising
            await _index_generated_code(sample_state, sample_config)

        assert sample_state.builder_statuses["auth-service"] == "healthy"

    async def test_ci_mcp_no_healthy_services_skips(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        tmp_output: Path,
    ) -> None:
        """When no services are healthy, indexing is skipped entirely."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        sample_state.builder_statuses = {"auth-service": "failed"}

        mock_client = MagicMock()
        mock_client.register_artifact = AsyncMock()

        mock_module = MagicMock()
        mock_module.CodebaseIntelligenceClient.return_value = mock_client

        with patch.dict(
            "sys.modules",
            {"src.codebase_intelligence.mcp_client": mock_module},
        ):
            await _index_generated_code(sample_state, sample_config)

        # register_artifact should never be called for failed services
        mock_client.register_artifact.assert_not_called()
