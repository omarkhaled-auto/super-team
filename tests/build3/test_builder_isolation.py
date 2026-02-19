"""Test concurrent builder isolation.

Phase 4.2: Verifies that parallel builders are properly isolated:
- Each builder writes only to its own output directory
- STATE.json files are independent
- Semaphore correctly gates concurrency (3 concurrent, 4th waits)
- No cross-contamination between builder directories
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.build3_shared.models import BuilderResult, ServiceInfo
from src.super_orchestrator.config import SuperOrchestratorConfig, BuilderConfig
from src.super_orchestrator.cost import PipelineCostTracker
from src.super_orchestrator.pipeline import run_parallel_builders
from src.super_orchestrator.shutdown import GracefulShutdown
from src.super_orchestrator.state import PipelineState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service_info(service_id: str, port: int = 8000) -> ServiceInfo:
    """Create a minimal ServiceInfo for testing."""
    return ServiceInfo(
        service_id=service_id,
        domain="test",
        stack={"language": "python", "framework": "fastapi"},
        port=port,
        health_endpoint="/health",
    )


def _make_service_map(services: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal service_map.json payload."""
    return {"services": services}


def _make_state_json(service_id: str, success: bool = True) -> dict[str, Any]:
    """Build a minimal STATE.json that _parse_builder_result expects."""
    return {
        "system_id": f"sys-{service_id}",
        "total_cost": 1.25,
        "summary": {
            "success": success,
            "test_passed": 10,
            "test_total": 10,
            "convergence_ratio": 0.95,
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """Temporary output directory for the pipeline."""
    out = tmp_path / "output"
    out.mkdir()
    return out


@pytest.fixture
def base_config(tmp_output_dir: Path) -> SuperOrchestratorConfig:
    """SuperOrchestratorConfig pointing at the tmp output dir."""
    cfg = SuperOrchestratorConfig(
        output_dir=str(tmp_output_dir),
        builder=BuilderConfig(max_concurrent=3, timeout_per_builder=60, depth="quick"),
    )
    return cfg


@pytest.fixture
def three_services() -> list[dict[str, Any]]:
    """Three service definitions for the service map."""
    return [
        {"service_id": "svc-alpha", "domain": "auth", "stack": {}, "port": 8001},
        {"service_id": "svc-beta", "domain": "orders", "stack": {}, "port": 8002},
        {"service_id": "svc-gamma", "domain": "notify", "stack": {}, "port": 8003},
    ]


@pytest.fixture
def four_services(three_services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Four services -- the fourth should wait for the Semaphore(3)."""
    return three_services + [
        {"service_id": "svc-delta", "domain": "analytics", "stack": {}, "port": 8004},
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuilderIsolation:
    """Suite verifying parallel builder output-directory isolation."""

    @pytest.mark.asyncio
    async def test_three_builders_get_unique_output_dirs(
        self,
        tmp_output_dir: Path,
        base_config: SuperOrchestratorConfig,
        three_services: list[dict[str, Any]],
    ):
        """Each of the 3 builders receives a unique, service-specific output_dir."""
        service_map = _make_service_map(three_services)
        smap_path = tmp_output_dir / "service_map.json"
        smap_path.write_text(json.dumps(service_map), encoding="utf-8")

        # Write PRD file that the builder needs
        prd_path = tmp_output_dir / "test_prd.md"
        prd_path.write_text("# Test PRD\nSimple test.", encoding="utf-8")

        state = PipelineState(
            prd_path=str(prd_path),
            service_map_path=str(smap_path),
        )
        cost = PipelineCostTracker()
        shutdown = GracefulShutdown()

        # Track which output_dir each builder call receives
        observed_output_dirs: list[str] = []

        async def _mock_single_builder(
            service_info: ServiceInfo,
            config: SuperOrchestratorConfig,
            state: PipelineState,
        ) -> BuilderResult:
            output_dir = Path(config.output_dir) / service_info.service_id
            observed_output_dirs.append(str(output_dir))

            # Simulate writing a file to our output dir
            output_dir.mkdir(parents=True, exist_ok=True)
            marker = output_dir / "marker.txt"
            marker.write_text(f"builder-{service_info.service_id}", encoding="utf-8")

            # Write STATE.json so _parse_builder_result succeeds
            agent_dir = output_dir / ".agent-team"
            agent_dir.mkdir(parents=True, exist_ok=True)
            state_file = agent_dir / "STATE.json"
            state_file.write_text(
                json.dumps(_make_state_json(service_info.service_id)),
                encoding="utf-8",
            )

            # Write a dummy source file so _parse_builder_result considers it successful
            (output_dir / "main.py").write_text("# generated", encoding="utf-8")

            return BuilderResult(
                system_id=f"sys-{service_info.service_id}",
                service_id=service_info.service_id,
                success=True,
                output_dir=str(output_dir),
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=_mock_single_builder,
        ):
            await run_parallel_builders(state, base_config, cost, shutdown)

        # All 3 builders should have run
        assert len(observed_output_dirs) == 3, (
            f"Expected 3 builder calls, got {len(observed_output_dirs)}"
        )

        # Each output_dir must be unique
        unique_dirs = set(observed_output_dirs)
        assert len(unique_dirs) == 3, (
            f"Expected 3 unique output dirs, got {len(unique_dirs)}: {observed_output_dirs}"
        )

        # Each dir should contain the correct service ID
        for svc in three_services:
            sid = svc["service_id"]
            svc_dir = tmp_output_dir / sid
            assert svc_dir.exists(), f"Output dir for {sid} does not exist"

    @pytest.mark.asyncio
    async def test_no_cross_contamination(
        self,
        tmp_output_dir: Path,
        base_config: SuperOrchestratorConfig,
        three_services: list[dict[str, Any]],
    ):
        """Each builder's marker file exists only in its own directory."""
        service_map = _make_service_map(three_services)
        smap_path = tmp_output_dir / "service_map.json"
        smap_path.write_text(json.dumps(service_map), encoding="utf-8")

        prd_path = tmp_output_dir / "test_prd.md"
        prd_path.write_text("# Test PRD\nSimple test.", encoding="utf-8")

        state = PipelineState(
            prd_path=str(prd_path),
            service_map_path=str(smap_path),
        )
        cost = PipelineCostTracker()
        shutdown = GracefulShutdown()

        async def _mock_single_builder(
            service_info: ServiceInfo,
            config: SuperOrchestratorConfig,
            state: PipelineState,
        ) -> BuilderResult:
            output_dir = Path(config.output_dir) / service_info.service_id
            output_dir.mkdir(parents=True, exist_ok=True)

            # Each builder writes a unique marker
            marker = output_dir / f"built_by_{service_info.service_id}.flag"
            marker.write_text(service_info.service_id, encoding="utf-8")

            # STATE.json for _parse_builder_result
            agent_dir = output_dir / ".agent-team"
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "STATE.json").write_text(
                json.dumps(_make_state_json(service_info.service_id)),
                encoding="utf-8",
            )
            (output_dir / "main.py").write_text("# generated", encoding="utf-8")

            return BuilderResult(
                system_id=f"sys-{service_info.service_id}",
                service_id=service_info.service_id,
                success=True,
                output_dir=str(output_dir),
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=_mock_single_builder,
        ):
            await run_parallel_builders(state, base_config, cost, shutdown)

        # Verify each service dir contains ONLY its own marker
        for svc in three_services:
            sid = svc["service_id"]
            svc_dir = tmp_output_dir / sid

            # Own marker must exist
            own_marker = svc_dir / f"built_by_{sid}.flag"
            assert own_marker.exists(), f"Marker for {sid} is missing"
            assert own_marker.read_text(encoding="utf-8") == sid

            # No other service's marker should be present
            for other_svc in three_services:
                other_sid = other_svc["service_id"]
                if other_sid == sid:
                    continue
                foreign_marker = svc_dir / f"built_by_{other_sid}.flag"
                assert not foreign_marker.exists(), (
                    f"Cross-contamination: {other_sid} marker found in {sid} directory"
                )

    @pytest.mark.asyncio
    async def test_state_json_independence(
        self,
        tmp_output_dir: Path,
        base_config: SuperOrchestratorConfig,
        three_services: list[dict[str, Any]],
    ):
        """Each builder's STATE.json is independent and contains service-specific data."""
        service_map = _make_service_map(three_services)
        smap_path = tmp_output_dir / "service_map.json"
        smap_path.write_text(json.dumps(service_map), encoding="utf-8")

        prd_path = tmp_output_dir / "test_prd.md"
        prd_path.write_text("# Test PRD\nSimple test.", encoding="utf-8")

        state = PipelineState(
            prd_path=str(prd_path),
            service_map_path=str(smap_path),
        )
        cost = PipelineCostTracker()
        shutdown = GracefulShutdown()

        async def _mock_single_builder(
            service_info: ServiceInfo,
            config: SuperOrchestratorConfig,
            state: PipelineState,
        ) -> BuilderResult:
            output_dir = Path(config.output_dir) / service_info.service_id
            output_dir.mkdir(parents=True, exist_ok=True)

            # Write a unique STATE.json per service
            agent_dir = output_dir / ".agent-team"
            agent_dir.mkdir(parents=True, exist_ok=True)

            state_data = _make_state_json(service_info.service_id)
            state_data["service_specific_marker"] = service_info.service_id
            (agent_dir / "STATE.json").write_text(
                json.dumps(state_data), encoding="utf-8"
            )
            (output_dir / "main.py").write_text("# generated", encoding="utf-8")

            return BuilderResult(
                system_id=f"sys-{service_info.service_id}",
                service_id=service_info.service_id,
                success=True,
                output_dir=str(output_dir),
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=_mock_single_builder,
        ):
            await run_parallel_builders(state, base_config, cost, shutdown)

        # Verify each STATE.json is unique
        for svc in three_services:
            sid = svc["service_id"]
            state_file = tmp_output_dir / sid / ".agent-team" / "STATE.json"
            assert state_file.exists(), f"STATE.json missing for {sid}"

            data = json.loads(state_file.read_text(encoding="utf-8"))
            assert data["service_specific_marker"] == sid, (
                f"STATE.json for {sid} contains wrong marker: {data['service_specific_marker']}"
            )
            assert data["system_id"] == f"sys-{sid}", (
                f"STATE.json system_id mismatch for {sid}"
            )

    @pytest.mark.asyncio
    async def test_semaphore_gates_concurrency(
        self,
        tmp_output_dir: Path,
        base_config: SuperOrchestratorConfig,
        four_services: list[dict[str, Any]],
    ):
        """With Semaphore(3), at most 3 builders run concurrently; the 4th waits."""
        service_map = _make_service_map(four_services)
        smap_path = tmp_output_dir / "service_map.json"
        smap_path.write_text(json.dumps(service_map), encoding="utf-8")

        prd_path = tmp_output_dir / "test_prd.md"
        prd_path.write_text("# Test PRD\nSimple test.", encoding="utf-8")

        state = PipelineState(
            prd_path=str(prd_path),
            service_map_path=str(smap_path),
        )
        cost = PipelineCostTracker()
        shutdown = GracefulShutdown()

        # Track concurrent running count
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def _mock_single_builder(
            service_info: ServiceInfo,
            config: SuperOrchestratorConfig,
            state: PipelineState,
        ) -> BuilderResult:
            nonlocal max_concurrent, current_concurrent

            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent

            # Simulate some work (enough for overlap)
            await asyncio.sleep(0.1)

            output_dir = Path(config.output_dir) / service_info.service_id
            output_dir.mkdir(parents=True, exist_ok=True)
            agent_dir = output_dir / ".agent-team"
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "STATE.json").write_text(
                json.dumps(_make_state_json(service_info.service_id)),
                encoding="utf-8",
            )
            (output_dir / "main.py").write_text("# generated", encoding="utf-8")

            async with lock:
                current_concurrent -= 1

            return BuilderResult(
                system_id=f"sys-{service_info.service_id}",
                service_id=service_info.service_id,
                success=True,
                output_dir=str(output_dir),
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=_mock_single_builder,
        ):
            await run_parallel_builders(state, base_config, cost, shutdown)

        # Max concurrent should be capped at 3 (the semaphore value)
        assert max_concurrent <= 3, (
            f"Semaphore violation: max concurrent was {max_concurrent}, expected <= 3"
        )

        # All 4 builders should have completed
        assert state.successful_builders == 4, (
            f"Expected 4 successful builders, got {state.successful_builders}"
        )
        assert state.total_builders == 4, (
            f"Expected 4 total builders, got {state.total_builders}"
        )

    @pytest.mark.asyncio
    async def test_fourth_builder_waits_for_semaphore(
        self,
        tmp_output_dir: Path,
        base_config: SuperOrchestratorConfig,
        four_services: list[dict[str, Any]],
    ):
        """The 4th builder must wait for a semaphore slot before running."""
        service_map = _make_service_map(four_services)
        smap_path = tmp_output_dir / "service_map.json"
        smap_path.write_text(json.dumps(service_map), encoding="utf-8")

        prd_path = tmp_output_dir / "test_prd.md"
        prd_path.write_text("# Test PRD\nSimple test.", encoding="utf-8")

        state = PipelineState(
            prd_path=str(prd_path),
            service_map_path=str(smap_path),
        )
        cost = PipelineCostTracker()
        shutdown = GracefulShutdown()

        # Record start times to check ordering
        start_times: dict[str, float] = {}
        end_times: dict[str, float] = {}
        lock = asyncio.Lock()

        async def _mock_single_builder(
            service_info: ServiceInfo,
            config: SuperOrchestratorConfig,
            state: PipelineState,
        ) -> BuilderResult:
            sid = service_info.service_id
            now = asyncio.get_event_loop().time()
            async with lock:
                start_times[sid] = now

            # Hold the semaphore slot for 0.2s to force the 4th to wait
            await asyncio.sleep(0.2)

            output_dir = Path(config.output_dir) / sid
            output_dir.mkdir(parents=True, exist_ok=True)
            agent_dir = output_dir / ".agent-team"
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "STATE.json").write_text(
                json.dumps(_make_state_json(sid)), encoding="utf-8"
            )
            (output_dir / "main.py").write_text("# generated", encoding="utf-8")

            finish = asyncio.get_event_loop().time()
            async with lock:
                end_times[sid] = finish

            return BuilderResult(
                system_id=f"sys-{sid}",
                service_id=sid,
                success=True,
                output_dir=str(output_dir),
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=_mock_single_builder,
        ):
            await run_parallel_builders(state, base_config, cost, shutdown)

        # All 4 should complete
        assert len(start_times) == 4
        assert len(end_times) == 4
        assert state.successful_builders == 4

        # Sort by start time to identify which started last
        sorted_starts = sorted(start_times.items(), key=lambda x: x[1])
        last_started = sorted_starts[-1]

        # The last-started builder should have started AFTER the earliest finisher
        # (meaning it waited for a semaphore slot)
        earliest_end = min(end_times.values())

        # Allow small timing tolerance (10ms)
        # The 4th builder's start should be close to or after the earliest end
        assert last_started[1] >= earliest_end - 0.01, (
            f"4th builder ({last_started[0]}) started at {last_started[1]:.3f} "
            f"but earliest builder finished at {earliest_end:.3f}. "
            f"Semaphore may not be gating properly."
        )

    @pytest.mark.asyncio
    async def test_builder_results_tracked_per_service(
        self,
        tmp_output_dir: Path,
        base_config: SuperOrchestratorConfig,
        three_services: list[dict[str, Any]],
    ):
        """PipelineState.builder_results has one entry per service after parallel run."""
        service_map = _make_service_map(three_services)
        smap_path = tmp_output_dir / "service_map.json"
        smap_path.write_text(json.dumps(service_map), encoding="utf-8")

        prd_path = tmp_output_dir / "test_prd.md"
        prd_path.write_text("# Test PRD\nSimple test.", encoding="utf-8")

        state = PipelineState(
            prd_path=str(prd_path),
            service_map_path=str(smap_path),
        )
        cost = PipelineCostTracker()
        shutdown = GracefulShutdown()

        async def _mock_single_builder(
            service_info: ServiceInfo,
            config: SuperOrchestratorConfig,
            state: PipelineState,
        ) -> BuilderResult:
            output_dir = Path(config.output_dir) / service_info.service_id
            output_dir.mkdir(parents=True, exist_ok=True)
            agent_dir = output_dir / ".agent-team"
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "STATE.json").write_text(
                json.dumps(_make_state_json(service_info.service_id)),
                encoding="utf-8",
            )
            (output_dir / "main.py").write_text("# generated", encoding="utf-8")

            return BuilderResult(
                system_id=f"sys-{service_info.service_id}",
                service_id=service_info.service_id,
                success=True,
                cost=1.25,
                output_dir=str(output_dir),
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=_mock_single_builder,
        ):
            await run_parallel_builders(state, base_config, cost, shutdown)

        # Verify state tracking
        assert state.total_builders == 3
        assert state.successful_builders == 3
        assert len(state.builder_results) == 3
        assert len(state.builder_statuses) == 3

        for svc in three_services:
            sid = svc["service_id"]
            assert sid in state.builder_results, f"{sid} missing from builder_results"
            assert sid in state.builder_statuses, f"{sid} missing from builder_statuses"
            assert state.builder_statuses[sid] == "healthy", (
                f"{sid} status is {state.builder_statuses[sid]}, expected 'healthy'"
            )
            assert state.builder_results[sid]["success"] is True

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure_isolation(
        self,
        tmp_output_dir: Path,
        base_config: SuperOrchestratorConfig,
        three_services: list[dict[str, Any]],
    ):
        """When one builder fails, others still succeed and their state is correct."""
        service_map = _make_service_map(three_services)
        smap_path = tmp_output_dir / "service_map.json"
        smap_path.write_text(json.dumps(service_map), encoding="utf-8")

        prd_path = tmp_output_dir / "test_prd.md"
        prd_path.write_text("# Test PRD\nSimple test.", encoding="utf-8")

        state = PipelineState(
            prd_path=str(prd_path),
            service_map_path=str(smap_path),
        )
        cost = PipelineCostTracker()
        shutdown = GracefulShutdown()

        fail_service = "svc-beta"

        async def _mock_single_builder(
            service_info: ServiceInfo,
            config: SuperOrchestratorConfig,
            state: PipelineState,
        ) -> BuilderResult:
            output_dir = Path(config.output_dir) / service_info.service_id
            output_dir.mkdir(parents=True, exist_ok=True)

            if service_info.service_id == fail_service:
                # Simulate a build failure
                return BuilderResult(
                    system_id=f"sys-{service_info.service_id}",
                    service_id=service_info.service_id,
                    success=False,
                    error="Simulated build failure",
                )

            # Successful build
            agent_dir = output_dir / ".agent-team"
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "STATE.json").write_text(
                json.dumps(_make_state_json(service_info.service_id)),
                encoding="utf-8",
            )
            (output_dir / "main.py").write_text("# generated", encoding="utf-8")

            return BuilderResult(
                system_id=f"sys-{service_info.service_id}",
                service_id=service_info.service_id,
                success=True,
                output_dir=str(output_dir),
            )

        with patch(
            "src.super_orchestrator.pipeline._run_single_builder",
            side_effect=_mock_single_builder,
        ):
            await run_parallel_builders(state, base_config, cost, shutdown)

        # 2 succeed, 1 fails
        assert state.successful_builders == 2
        assert state.total_builders == 3

        # Failed builder is marked as failed
        assert state.builder_statuses[fail_service] == "failed"

        # Successful builders are marked as healthy
        for svc in three_services:
            sid = svc["service_id"]
            if sid == fail_service:
                continue
            assert state.builder_statuses[sid] == "healthy", (
                f"Builder {sid} should be healthy, got {state.builder_statuses[sid]}"
            )
