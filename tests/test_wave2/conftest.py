"""Conftest for Wave 2 tests.

Adds PipelineCostTracker shims (start_phase/end_phase/phase_costs) that may
be cleaned up by the build3 conftest teardown before wave2 tests run.
"""

import pytest


@pytest.fixture(autouse=True)
def _ensure_cost_tracker_shims():
    """Add backward-compatible shim methods to PipelineCostTracker.

    Mirrors the shim in tests/build3/conftest.py to avoid AttributeError
    when wave2 tests run after build3 tests have cleaned up the shims.
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
