"""Shared fixtures and configuration for benchmark tests.

Registers the 'benchmark' marker and provides a consolidated summary
report across all benchmark modules.
"""

from __future__ import annotations

import time
from typing import Any

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register the benchmark marker."""
    config.addinivalue_line(
        "markers",
        "benchmark: marks tests as performance benchmarks",
    )


@pytest.fixture(autouse=True)
def _ensure_cost_tracker_shims():
    """Add backward-compatible shim methods to PipelineCostTracker.

    Mirrors the shim in tests/build3/conftest.py to avoid AttributeError
    when benchmarks run after build3 tests have cleaned up the shims.
    """
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


# ---------------------------------------------------------------------------
# Consolidated Summary (aggregates results from all benchmark modules)
# ---------------------------------------------------------------------------

_all_results: list[dict[str, Any]] = []


def collect_result(name: str, elapsed_ms: float, target_ms: float, passed: bool) -> None:
    """Collect a result for the consolidated report."""
    _all_results.append({
        "name": name,
        "elapsed_ms": elapsed_ms,
        "target_ms": target_ms,
        "passed": passed,
    })


@pytest.fixture(scope="session", autouse=True)
def consolidated_benchmark_report(request: pytest.FixtureRequest) -> None:
    """Print the final consolidated benchmark report after all tests."""

    def _print_report() -> None:
        # Import results from each module
        try:
            from tests.benchmarks.test_mcp_latency import _benchmark_results as mcp_results
        except ImportError:
            mcp_results = []
        try:
            from tests.benchmarks.test_pipeline_timing import _phase_results as phase_results
        except ImportError:
            phase_results = []
        try:
            from tests.benchmarks.test_state_machine_perf import _sm_results as sm_results
        except ImportError:
            sm_results = []

        all_results = list(mcp_results) + list(phase_results) + list(sm_results)

        if not all_results:
            return

        print("\n\n")
        print("=" * 68)
        print("  === Performance Benchmark Results (Consolidated) ===")
        print("=" * 68)
        print(f"  {'Benchmark':<32} {'Elapsed':>10} {'Target':>10} {'Status':>8}")
        print("  " + "-" * 64)

        total_pass = 0
        total_fail = 0
        for r in all_results:
            if r["passed"]:
                status_str = "PASS"
                total_pass += 1
            else:
                status_str = "FAIL"
                total_fail += 1
            print(
                f"  {r['name']:<32} {r['elapsed_ms']:>8.1f}ms "
                f"{r['target_ms']:>8.0f}ms   {status_str:>6}"
            )

        print("  " + "-" * 64)
        print(f"  Total: {total_pass} passed, {total_fail} failed, {len(all_results)} total")
        if total_fail == 0:
            print("  Status: ALL BENCHMARKS PASSED")
        else:
            print(f"  Status: {total_fail} BENCHMARK(S) FAILED")
        print("=" * 68)

    request.addfinalizer(_print_report)
