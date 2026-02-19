"""State Machine Transition Performance Benchmarks.

Tests that:
  1. All 13 state machine transitions complete in < 10ms each
  2. State persistence (save/load) completes in < 50ms

Usage:
    python -m pytest tests/benchmarks/test_state_machine_perf.py -v --timeout=30
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from src.super_orchestrator.state import PipelineState
from src.super_orchestrator.state_machine import (
    STATES,
    TRANSITIONS,
    RESUME_TRIGGERS,
    create_pipeline_machine,
)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

TRANSITION_THRESHOLD = 0.01    # 10ms per transition
SAVE_LOAD_THRESHOLD = 0.05     # 50ms for save + load round-trip
STATE_INIT_THRESHOLD = 0.005   # 5ms for state initialization


# ---------------------------------------------------------------------------
# Results collector
# ---------------------------------------------------------------------------

_sm_results: list[dict[str, Any]] = []


def _record(name: str, elapsed_ms: float, target_ms: float, passed: bool) -> None:
    """Record a benchmark result for the summary."""
    _sm_results.append({
        "name": name,
        "elapsed_ms": elapsed_ms,
        "target_ms": target_ms,
        "passed": passed,
    })


# ---------------------------------------------------------------------------
# PipelineModel stub for state machine tests
# ---------------------------------------------------------------------------

class StubPipelineModel:
    """Stub model that satisfies all state machine guard conditions.

    Every guard method returns True so that all transitions succeed.
    """

    def __init__(self) -> None:
        self.state: str = "init"

    def is_configured(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def has_service_map(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def service_map_valid(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def contracts_valid(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def has_builder_results(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def any_builder_passed(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def has_integration_report(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def gate_passed(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def fix_attempts_remaining(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def fix_applied(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def retries_remaining(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def advisory_only(self, *args: Any, **kwargs: Any) -> bool:
        return True


# ---------------------------------------------------------------------------
# Tests: State Machine Transitions
# ---------------------------------------------------------------------------

@pytest.mark.benchmark
class TestStateMachineTransitionPerformance:
    """Verify all 13 state machine transitions are fast."""

    def test_state_count(self) -> None:
        """Verify the state machine defines exactly 11 states."""
        assert len(STATES) == 11, f"Expected 11 states, got {len(STATES)}"

    def test_transition_count(self) -> None:
        """Verify the state machine defines exactly 13 transitions."""
        assert len(TRANSITIONS) == 13, f"Expected 13 transitions, got {len(TRANSITIONS)}"

    async def test_happy_path_transitions(self) -> None:
        """The full happy path (init -> complete) should be fast.

        Exercises 8 transitions in sequence:
          init -> architect_running -> architect_review ->
          contracts_registering -> builders_running ->
          builders_complete -> integrating -> quality_gate -> complete

        Note: The first transition may incur a one-time warmup cost from
        the transitions library's internal setup. We use a slightly
        higher threshold (20ms) for the first transition.
        """
        model = StubPipelineModel()
        machine = create_pipeline_machine(model)

        # Warmup: run one throwaway transition on a separate model to
        # prime the transitions library's internal caches.
        warmup_model = StubPipelineModel()
        _warmup_machine = create_pipeline_machine(warmup_model)
        await warmup_model.start_architect()

        happy_path = [
            ("start_architect", "architect_running"),
            ("architect_done", "architect_review"),
            ("approve_architect", "contracts_registering"),
            ("contracts_registered", "builders_running"),
            ("builders_done", "builders_complete"),
            ("start_integration", "integrating"),
            ("integration_done", "quality_gate"),
            ("quality_passed", "complete"),
        ]

        for trigger_name, expected_dest in happy_path:
            trigger_fn = getattr(model, trigger_name)

            start = time.monotonic()
            await trigger_fn()
            elapsed = time.monotonic() - start

            elapsed_ms = elapsed * 1000
            passed = elapsed < TRANSITION_THRESHOLD

            _record(
                f"T: {trigger_name}",
                elapsed_ms,
                TRANSITION_THRESHOLD * 1000,
                passed,
            )

            assert model.state == expected_dest, (
                f"After {trigger_name}: expected state '{expected_dest}', "
                f"got '{model.state}'"
            )
            assert elapsed < TRANSITION_THRESHOLD, (
                f"Transition {trigger_name} took {elapsed_ms:.2f}ms, "
                f"exceeds {TRANSITION_THRESHOLD * 1000:.0f}ms threshold"
            )

    async def test_fix_loop_transitions(self) -> None:
        """The fix loop path (quality_gate -> fix_pass -> builders_running) should be fast.

        Exercises the quality_needs_fix and fix_done transitions.
        """
        model = StubPipelineModel()
        machine = create_pipeline_machine(model)

        # Navigate to quality_gate state first
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()

        assert model.state == "quality_gate"

        # Transition: quality_gate -> fix_pass
        start = time.monotonic()
        await model.quality_needs_fix()
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        _record(
            "T: quality_needs_fix",
            elapsed_ms,
            TRANSITION_THRESHOLD * 1000,
            elapsed < TRANSITION_THRESHOLD,
        )
        assert model.state == "fix_pass"
        assert elapsed < TRANSITION_THRESHOLD

        # Transition: fix_pass -> builders_running
        start = time.monotonic()
        await model.fix_done()
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        _record(
            "T: fix_done",
            elapsed_ms,
            TRANSITION_THRESHOLD * 1000,
            elapsed < TRANSITION_THRESHOLD,
        )
        assert model.state == "builders_running"
        assert elapsed < TRANSITION_THRESHOLD

    async def test_fail_transition(self) -> None:
        """The fail transition from any state should be fast."""
        model = StubPipelineModel()
        machine = create_pipeline_machine(model)

        # Test fail from init
        start = time.monotonic()
        await model.fail()
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        _record(
            "T: fail (from init)",
            elapsed_ms,
            TRANSITION_THRESHOLD * 1000,
            elapsed < TRANSITION_THRESHOLD,
        )
        assert model.state == "failed"
        assert elapsed < TRANSITION_THRESHOLD

    async def test_retry_architect_transition(self) -> None:
        """The retry_architect self-loop should be fast."""
        model = StubPipelineModel()
        machine = create_pipeline_machine(model)

        await model.start_architect()
        assert model.state == "architect_running"

        start = time.monotonic()
        await model.retry_architect()
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        _record(
            "T: retry_architect",
            elapsed_ms,
            TRANSITION_THRESHOLD * 1000,
            elapsed < TRANSITION_THRESHOLD,
        )
        assert model.state == "architect_running"
        assert elapsed < TRANSITION_THRESHOLD

    async def test_skip_to_complete_transition(self) -> None:
        """The skip_to_complete transition from quality_gate should be fast."""
        model = StubPipelineModel()
        machine = create_pipeline_machine(model)

        # Navigate to quality_gate
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()
        assert model.state == "quality_gate"

        start = time.monotonic()
        await model.skip_to_complete()
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        _record(
            "T: skip_to_complete",
            elapsed_ms,
            TRANSITION_THRESHOLD * 1000,
            elapsed < TRANSITION_THRESHOLD,
        )
        assert model.state == "complete"
        assert elapsed < TRANSITION_THRESHOLD

    async def test_all_13_transitions_covered(self) -> None:
        """Verify we have benchmarked all 13 transitions.

        This meta-test checks that our benchmark suite covers every
        transition defined in the state machine.
        """
        all_triggers = set()
        for t in TRANSITIONS:
            all_triggers.add(t["trigger"])

        # We test these triggers across the above test methods:
        tested_triggers = {
            "start_architect",
            "architect_done",
            "approve_architect",
            "contracts_registered",
            "builders_done",
            "start_integration",
            "integration_done",
            "quality_passed",
            "quality_needs_fix",
            "fix_done",
            "fail",
            "retry_architect",
            "skip_to_complete",
        }

        assert tested_triggers == all_triggers, (
            f"Missing triggers: {all_triggers - tested_triggers}, "
            f"Extra triggers: {tested_triggers - all_triggers}"
        )


# ---------------------------------------------------------------------------
# Tests: State Persistence Performance
# ---------------------------------------------------------------------------

@pytest.mark.benchmark
class TestStatePersistencePerformance:
    """Measure state save/load round-trip time."""

    def test_state_initialization_speed(self) -> None:
        """Creating a new PipelineState should be near-instant (< 5ms)."""
        start = time.monotonic()
        state = PipelineState(
            prd_path="/tmp/test.md",
            config_path="/tmp/config.yaml",
            depth="standard",
        )
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        _record(
            "State Init",
            elapsed_ms,
            STATE_INIT_THRESHOLD * 1000,
            elapsed < STATE_INIT_THRESHOLD,
        )

        assert state.pipeline_id is not None
        assert elapsed < STATE_INIT_THRESHOLD, (
            f"State initialization took {elapsed_ms:.2f}ms, "
            f"exceeds {STATE_INIT_THRESHOLD * 1000:.0f}ms threshold"
        )

    def test_state_save_speed(self, tmp_path: Path) -> None:
        """Saving state to disk should be fast (< 25ms)."""
        state = PipelineState(
            prd_path="/tmp/test.md",
            config_path="/tmp/config.yaml",
            depth="thorough",
        )
        # Populate with realistic data
        state.builder_results = {
            f"service-{i}": {
                "system_id": f"sys-{i}",
                "service_id": f"service-{i}",
                "success": True,
                "cost": 0.5,
            }
            for i in range(5)
        }
        state.phase_artifacts = {
            "architect": {"service_map_path": "/tmp/smap.json"},
            "builders": {"total_builders": 5, "successful_builders": 5},
            "quality_gate": {"overall_verdict": "PASSED"},
        }

        start = time.monotonic()
        state.save(directory=tmp_path)
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        save_threshold = SAVE_LOAD_THRESHOLD / 2  # Half the budget for save
        _record(
            "State Save",
            elapsed_ms,
            save_threshold * 1000,
            elapsed < save_threshold,
        )

        assert elapsed < save_threshold, (
            f"State save took {elapsed_ms:.2f}ms, "
            f"exceeds {save_threshold * 1000:.0f}ms threshold"
        )

    def test_state_load_speed(self, tmp_path: Path) -> None:
        """Loading state from disk should be fast (< 25ms)."""
        # First, save a state
        state = PipelineState(
            prd_path="/tmp/test.md",
            config_path="/tmp/config.yaml",
            depth="thorough",
        )
        state.builder_results = {
            f"service-{i}": {
                "system_id": f"sys-{i}",
                "service_id": f"service-{i}",
                "success": True,
                "cost": 0.5,
            }
            for i in range(5)
        }
        state.save(directory=tmp_path)

        # Now benchmark the load
        start = time.monotonic()
        loaded = PipelineState.load(directory=tmp_path)
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        load_threshold = SAVE_LOAD_THRESHOLD / 2  # Half the budget for load
        _record(
            "State Load",
            elapsed_ms,
            load_threshold * 1000,
            elapsed < load_threshold,
        )

        assert loaded is not None
        assert loaded.pipeline_id == state.pipeline_id
        assert elapsed < load_threshold, (
            f"State load took {elapsed_ms:.2f}ms, "
            f"exceeds {load_threshold * 1000:.0f}ms threshold"
        )

    def test_state_save_load_roundtrip(self, tmp_path: Path) -> None:
        """Full save + load round-trip should be < 50ms."""
        state = PipelineState(
            prd_path="/tmp/test.md",
            config_path="/tmp/config.yaml",
            depth="thorough",
        )
        # Populate with maximum realistic payload
        state.builder_results = {
            f"service-{i}": {
                "system_id": f"sys-{i}",
                "service_id": f"service-{i}",
                "success": i % 2 == 0,
                "cost": 0.5 * i,
                "test_passed": 10 + i,
                "test_total": 15 + i,
                "convergence_ratio": 0.8 + (i * 0.01),
                "error": "" if i % 2 == 0 else f"Error in service {i}",
            }
            for i in range(10)
        }
        state.builder_statuses = {
            f"service-{i}": "healthy" if i % 2 == 0 else "failed"
            for i in range(10)
        }
        state.phase_artifacts = {
            "architect": {
                "service_map_path": "/tmp/smap.json",
                "domain_model_path": "/tmp/dmodel.json",
                "contract_registry_path": "/tmp/contracts/",
            },
            "builders": {"total_builders": 10, "successful_builders": 5},
            "integration": {"services_deployed": 5, "services_healthy": 5},
            "quality_gate": {"overall_verdict": "PASSED", "total_violations": 12},
        }
        state.last_quality_results = {
            "overall_verdict": "PASSED",
            "total_violations": 12,
            "blocking_violations": 0,
            "layers": {
                "layer1": {"violations": [], "passed": True},
                "layer2": {"violations": [], "passed": True},
                "layer3": {
                    "violations": [
                        {"code": f"SEC-{i:03d}", "severity": "warning", "message": f"Warning {i}"}
                        for i in range(12)
                    ],
                    "passed": True,
                },
                "layer4": {"violations": [], "passed": True},
            },
        }

        start = time.monotonic()
        state.save(directory=tmp_path)
        loaded = PipelineState.load(directory=tmp_path)
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        _record(
            "State Save/Load RT",
            elapsed_ms,
            SAVE_LOAD_THRESHOLD * 1000,
            elapsed < SAVE_LOAD_THRESHOLD,
        )

        assert loaded is not None
        assert loaded.pipeline_id == state.pipeline_id
        assert len(loaded.builder_results) == 10
        assert elapsed < SAVE_LOAD_THRESHOLD, (
            f"State save/load round-trip took {elapsed_ms:.2f}ms, "
            f"exceeds {SAVE_LOAD_THRESHOLD * 1000:.0f}ms threshold"
        )


# ---------------------------------------------------------------------------
# Tests: State Machine Creation Performance
# ---------------------------------------------------------------------------

@pytest.mark.benchmark
class TestStateMachineCreationPerformance:
    """Measure the cost of creating a new AsyncMachine instance."""

    def test_machine_creation_speed(self) -> None:
        """Creating a new state machine should be fast (< 10ms)."""
        model = StubPipelineModel()

        start = time.monotonic()
        machine = create_pipeline_machine(model)
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        creation_threshold = 0.01  # 10ms

        _record(
            "Machine Creation",
            elapsed_ms,
            creation_threshold * 1000,
            elapsed < creation_threshold,
        )

        assert machine is not None
        assert model.state == "init"
        assert elapsed < creation_threshold, (
            f"Machine creation took {elapsed_ms:.2f}ms, "
            f"exceeds {creation_threshold * 1000:.0f}ms threshold"
        )

    def test_machine_creation_100_iterations(self) -> None:
        """Creating 100 state machines should complete in < 500ms total."""
        threshold = 0.5  # 500ms total

        start = time.monotonic()
        for _ in range(100):
            model = StubPipelineModel()
            create_pipeline_machine(model)
        elapsed = time.monotonic() - start
        elapsed_ms = elapsed * 1000

        _record(
            "100x Machine Create",
            elapsed_ms,
            threshold * 1000,
            elapsed < threshold,
        )

        assert elapsed < threshold, (
            f"100 machine creations took {elapsed_ms:.1f}ms, "
            f"exceeds {threshold * 1000:.0f}ms threshold"
        )


# ---------------------------------------------------------------------------
# Summary Report
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def print_state_machine_summary(request: pytest.FixtureRequest) -> None:
    """Print a summary of all state machine performance results."""

    def _finalizer() -> None:
        if not _sm_results:
            return

        print("\n")
        print("=" * 60)
        print("  State Machine Performance Results")
        print("=" * 60)
        print(f"{'Benchmark':<28} {'Elapsed':>10} {'Target':>10} {'Status':>8}")
        print("-" * 60)

        all_passed = True
        for r in _sm_results:
            status = "PASS" if r["passed"] else "FAIL"
            if not r["passed"]:
                all_passed = False
            print(
                f"  {r['name']:<26} {r['elapsed_ms']:>8.2f}ms {r['target_ms']:>8.0f}ms "
                f"{'  ' + status:>8}"
            )

        print("-" * 60)
        overall = "ALL PASSED" if all_passed else "SOME FAILED"
        print(f"  Overall: {overall}")
        print("=" * 60)

    request.addfinalizer(_finalizer)
