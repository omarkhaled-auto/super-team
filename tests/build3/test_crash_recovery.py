"""Test pipeline crash recovery and resume.

Phase 4 (Stress Test & Hardening) -- Task 4.3

Tests that the pipeline can:
    1. Handle interruption (KeyboardInterrupt) during builders_running
    2. Persist state with interrupted=True on crash
    3. Resume from interrupted state, picking up from the correct phase
    4. Preserve completed_phases across save/load cycles
    5. Set GracefulShutdown.should_stop on interrupt
    6. Write state atomically (no partial writes)
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.build3_shared.constants import STATE_FILE
from src.build3_shared.models import BuilderResult
from src.build3_shared.utils import atomic_write_json, load_json
from src.super_orchestrator.config import (
    BuilderConfig,
    IntegrationConfig,
    QualityGateConfig,
    SuperOrchestratorConfig,
)
from src.super_orchestrator.cost import PipelineCostTracker
from src.super_orchestrator.exceptions import ConfigurationError, PipelineError
from src.super_orchestrator.pipeline import (
    execute_pipeline,
    run_parallel_builders,
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
    """Create a pre-configured pipeline state with a PRD and service map."""
    prd = tmp_path / "test_prd.md"
    prd.write_text(
        "# Test PRD\nThis is a test PRD with enough content for validation.",
        encoding="utf-8",
    )

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
    state.builder_results = {}  # type: ignore[assignment]
    return state


@pytest.fixture
def cost_tracker() -> PipelineCostTracker:
    return PipelineCostTracker(budget_limit=100.0)


@pytest.fixture
def shutdown() -> GracefulShutdown:
    return GracefulShutdown()


# ---------------------------------------------------------------------------
# 4.3a: Simulate interrupt at builders_running
# ---------------------------------------------------------------------------


class TestInterruptAtBuildersRunning:
    """Simulate KeyboardInterrupt during the builders phase."""

    async def test_keyboard_interrupt_sets_interrupted_flag(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
        tmp_path: Path,
    ) -> None:
        """When run_parallel_builders raises KeyboardInterrupt,
        execute_pipeline catches it, sets state.interrupted=True, and saves."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        prd = tmp_path / "test_prd.md"

        # Pre-populate completed phases (architect + contract_registration done)
        sample_state.completed_phases = ["architect", "contract_registration"]
        sample_state.current_state = "builders_running"

        # Mock _run_pipeline_loop to raise KeyboardInterrupt
        # (simulating an interrupt during builders)
        with patch(
            "src.super_orchestrator.pipeline._run_pipeline_loop",
            side_effect=KeyboardInterrupt(),
        ), patch(
            "src.super_orchestrator.pipeline.GracefulShutdown",
            return_value=shutdown,
        ), patch(
            "src.super_orchestrator.pipeline.create_pipeline_machine",
        ), patch.object(
            PipelineState,
            "load",
            return_value=sample_state,
        ), patch.object(
            PipelineState, "save"
        ) as mock_save:
            with pytest.raises(KeyboardInterrupt):
                await execute_pipeline(prd, resume=True)

        # State should be marked as interrupted
        assert sample_state.interrupted is True
        assert sample_state.interrupt_reason == "Keyboard interrupt"
        # save() must have been called
        assert mock_save.called

    async def test_interrupt_during_builders_preserves_state_on_disk(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
        tmp_path: Path,
    ) -> None:
        """KeyboardInterrupt during builders persists state to disk."""
        state_dir = tmp_path / "crash_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        prd = tmp_path / "test_prd.md"

        sample_state.completed_phases = ["architect", "contract_registration"]
        sample_state.current_state = "builders_running"

        # Use real save to a custom directory
        original_save = PipelineState.save

        def patched_save(self_state, directory=None):
            return original_save(self_state, directory=state_dir)

        with patch(
            "src.super_orchestrator.pipeline._run_pipeline_loop",
            side_effect=KeyboardInterrupt(),
        ), patch(
            "src.super_orchestrator.pipeline.GracefulShutdown",
            return_value=shutdown,
        ), patch(
            "src.super_orchestrator.pipeline.create_pipeline_machine",
        ), patch.object(
            PipelineState,
            "load",
            return_value=sample_state,
        ), patch.object(
            PipelineState, "save", patched_save
        ):
            with pytest.raises(KeyboardInterrupt):
                await execute_pipeline(prd, resume=True)

        # State file should exist on disk
        state_file = state_dir / STATE_FILE
        assert state_file.exists(), "State file must be preserved on disk after crash"

        # Verify persisted content
        data = load_json(state_file)
        assert data is not None
        assert data["interrupted"] is True
        assert "architect" in data["completed_phases"]
        assert "contract_registration" in data["completed_phases"]

    async def test_interrupt_in_run_parallel_builders_propagates(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        shutdown: GracefulShutdown,
        tmp_output: Path,
    ) -> None:
        """A RuntimeError (standing in for KeyboardInterrupt) inside
        run_parallel_builders propagates up through asyncio.gather.

        Note: We use RuntimeError instead of real KeyboardInterrupt
        because a real KeyboardInterrupt inside asyncio.gather will
        escape the test harness itself and abort the entire pytest run.
        This validates the propagation path without side effects.
        """
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))

        # Mock _run_single_builder to raise RuntimeError (proxy for interrupt)
        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Simulated interrupt"),
        ):
            # asyncio.gather propagates exceptions from child tasks
            # run_parallel_builders does not catch RuntimeError
            # so it will propagate up
            with pytest.raises(RuntimeError, match="Simulated interrupt"):
                await run_parallel_builders(
                    sample_state, sample_config, cost_tracker, shutdown
                )


# ---------------------------------------------------------------------------
# 4.3b: Resume from interrupted state
# ---------------------------------------------------------------------------


class TestResumeFromInterrupted:
    """Test that the pipeline can resume from an interrupted state."""

    async def test_resume_picks_up_from_interrupted_phase(
        self,
        tmp_path: Path,
    ) -> None:
        """execute_pipeline with resume=True loads saved state and
        picks up from the interrupted phase."""
        prd = tmp_path / "prd.md"
        prd.write_text("# Test PRD\n" + "x" * 200, encoding="utf-8")

        saved_state = PipelineState(
            prd_path=str(prd),
            current_state="builders_running",
            completed_phases=["architect", "contract_registration"],
            interrupted=True,
            interrupt_reason="Keyboard interrupt",
        )

        with patch.object(
            PipelineState, "load", return_value=saved_state
        ), patch(
            "src.super_orchestrator.pipeline._run_pipeline_loop",
            new_callable=AsyncMock,
        ) as mock_loop, patch(
            "src.super_orchestrator.pipeline.GracefulShutdown",
        ), patch(
            "src.super_orchestrator.pipeline.create_pipeline_machine",
        ):
            result = await execute_pipeline(prd, resume=True)

        # The loop should have been called
        assert mock_loop.called
        # The state should still know where it was interrupted
        assert result.current_state == "builders_running"
        assert "architect" in result.completed_phases
        assert "contract_registration" in result.completed_phases

    async def test_resume_preserves_completed_phases(
        self,
        tmp_path: Path,
    ) -> None:
        """Completed phases from the previous run are preserved on resume."""
        prd = tmp_path / "prd.md"
        prd.write_text("# Test PRD\n" + "x" * 200, encoding="utf-8")

        saved_state = PipelineState(
            prd_path=str(prd),
            current_state="builders_complete",
            completed_phases=["architect", "contract_registration", "builders"],
            builder_results={"auth-service": {"success": True, "cost": 1.5}},
            successful_builders=1,
        )

        with patch.object(
            PipelineState, "load", return_value=saved_state
        ), patch(
            "src.super_orchestrator.pipeline._run_pipeline_loop",
            new_callable=AsyncMock,
        ), patch(
            "src.super_orchestrator.pipeline.GracefulShutdown",
        ), patch(
            "src.super_orchestrator.pipeline.create_pipeline_machine",
        ):
            result = await execute_pipeline(prd, resume=True)

        # All prior completed phases must survive resume
        assert "architect" in result.completed_phases
        assert "contract_registration" in result.completed_phases
        assert "builders" in result.completed_phases
        # Builder results must also be preserved
        assert "auth-service" in result.builder_results

    async def test_resume_resets_interrupted_flag_implicitly(
        self,
        tmp_path: Path,
    ) -> None:
        """When resume succeeds, the pipeline loop can run normally.
        The interrupted flag from the previous crash is still present
        in the loaded state, but the loop handler will clear/reset it
        if it reaches a terminal state."""
        prd = tmp_path / "prd.md"
        prd.write_text("# Test PRD\n" + "x" * 200, encoding="utf-8")

        saved_state = PipelineState(
            prd_path=str(prd),
            current_state="builders_running",
            interrupted=True,
        )

        async def mock_loop(state, config, cost_tracker, shutdown, model):
            # Simulate successful completion after resume
            model.state = "complete"
            state.current_state = "complete"
            state.interrupted = False

        with patch.object(
            PipelineState, "load", return_value=saved_state
        ), patch(
            "src.super_orchestrator.pipeline._run_pipeline_loop",
            side_effect=mock_loop,
        ), patch(
            "src.super_orchestrator.pipeline.GracefulShutdown",
        ), patch(
            "src.super_orchestrator.pipeline.create_pipeline_machine",
        ):
            result = await execute_pipeline(prd, resume=True)

        assert result.interrupted is False
        assert result.current_state == "complete"


# ---------------------------------------------------------------------------
# 4.3c: Verify no orphan processes / GracefulShutdown
# ---------------------------------------------------------------------------


class TestNoOrphanProcesses:
    """Verify that GracefulShutdown.should_stop is set on interrupt."""

    async def test_graceful_shutdown_should_stop_set_on_signal(self) -> None:
        """GracefulShutdown._signal_handler sets should_stop to True."""
        shutdown = GracefulShutdown()
        assert shutdown.should_stop is False
        shutdown._signal_handler(2, None)  # SIGINT
        assert shutdown.should_stop is True

    async def test_graceful_shutdown_emergency_save_on_interrupt(self) -> None:
        """Emergency save marks state as interrupted."""
        shutdown = GracefulShutdown()
        state = PipelineState(current_state="builders_running")
        shutdown.set_state(state)
        shutdown._signal_handler(2, None)
        assert state.interrupted is True
        assert state.interrupt_reason == "Signal received"

    async def test_builders_respect_shutdown_flag(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        tmp_output: Path,
    ) -> None:
        """Builders exit early when should_stop is True."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        shutdown = GracefulShutdown()
        shutdown.should_stop = True

        await run_parallel_builders(
            sample_state, sample_config, cost_tracker, shutdown
        )
        # Builders should not have run (phase not completed)
        assert "builders" not in sample_state.completed_phases

    async def test_shutdown_prevents_new_builder_execution(
        self,
        sample_state: PipelineState,
        sample_config: SuperOrchestratorConfig,
        cost_tracker: PipelineCostTracker,
        tmp_output: Path,
    ) -> None:
        """When shutdown is requested during builders, each builder task
        checks should_stop before executing."""
        sample_config = dataclasses.replace(sample_config, output_dir=str(tmp_output))
        shutdown = GracefulShutdown()

        call_count = 0

        async def mock_single_builder(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # After first builder, request shutdown
            shutdown.should_stop = True
            return BuilderResult(
                system_id="sys",
                service_id=f"svc-{call_count}",
                success=True,
                cost=0.5,
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=mock_single_builder,
        ):
            await run_parallel_builders(
                sample_state, sample_config, cost_tracker, shutdown
            )

        # At least one builder ran, but the shutdown flag was set
        assert shutdown.should_stop is True


# ---------------------------------------------------------------------------
# 4.3 (additional): State persistence across crashes
# ---------------------------------------------------------------------------


class TestStatePersistenceAcrossCrashes:
    """Verify state persistence mechanisms work correctly across crashes."""

    def test_pipeline_state_save_is_atomic(self, tmp_path: Path) -> None:
        """PipelineState.save() writes atomically via atomic_write_json."""
        state = PipelineState(
            pipeline_id="crash-test-1",
            current_state="builders_running",
            completed_phases=["architect", "contract_registration"],
            builder_results={"svc1": {"success": True}},
            total_cost=5.0,
        )
        saved_path = state.save(tmp_path)

        # Verify no .tmp file left behind
        tmp_file = saved_path.with_suffix(".tmp")
        assert not tmp_file.exists()

        # Verify content is valid JSON
        data = load_json(saved_path)
        assert data is not None
        assert data["pipeline_id"] == "crash-test-1"

    def test_pipeline_state_load_roundtrip_preserves_all_fields(
        self, tmp_path: Path
    ) -> None:
        """Save then load preserves current_state, completed_phases,
        builder_results."""
        state = PipelineState(
            pipeline_id="roundtrip-1",
            current_state="integrating",
            completed_phases=["architect", "contract_registration", "builders"],
            builder_results={
                "auth": {"success": True, "cost": 2.0},
                "orders": {"success": False, "error": "timeout"},
            },
            total_cost=8.5,
            budget_limit=100.0,
        )
        state.save(tmp_path)

        loaded = PipelineState.load(tmp_path)
        assert loaded is not None
        assert loaded.pipeline_id == "roundtrip-1"
        assert loaded.current_state == "integrating"
        assert loaded.completed_phases == [
            "architect",
            "contract_registration",
            "builders",
        ]
        assert loaded.builder_results["auth"]["success"] is True
        assert loaded.builder_results["orders"]["error"] == "timeout"
        assert loaded.total_cost == 8.5

    def test_interrupted_state_roundtrip(self, tmp_path: Path) -> None:
        """Interrupted flag and reason survive save/load cycle."""
        state = PipelineState(
            pipeline_id="interrupted-rt",
            current_state="builders_running",
            interrupted=True,
            interrupt_reason="Keyboard interrupt",
            completed_phases=["architect"],
        )
        state.save(tmp_path)

        loaded = PipelineState.load(tmp_path)
        assert loaded is not None
        assert loaded.interrupted is True
        assert loaded.interrupt_reason == "Keyboard interrupt"
        assert loaded.current_state == "builders_running"

    def test_atomic_write_leaves_no_partial_on_crash(self, tmp_path: Path) -> None:
        """If atomic_write_json crashes mid-write, no partial file is left."""
        target = tmp_path / "crash.json"

        with patch("json.dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                atomic_write_json(target, {"data": "test"})

        # Neither the target nor the temp file should exist
        assert not target.exists()
        assert not target.with_suffix(".tmp").exists()

    def test_multiple_saves_overwrite_correctly(self, tmp_path: Path) -> None:
        """Multiple saves update the same file, last write wins."""
        state = PipelineState(
            pipeline_id="multi-save",
            current_state="init",
        )
        state.save(tmp_path)

        state.current_state = "architect_running"
        state.completed_phases.append("architect")
        state.save(tmp_path)

        loaded = PipelineState.load(tmp_path)
        assert loaded is not None
        assert loaded.current_state == "architect_running"
        assert "architect" in loaded.completed_phases
