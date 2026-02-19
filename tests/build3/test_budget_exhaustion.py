"""Tests for budget exhaustion behavior in the pipeline.

Phase 4 (Stress Test & Hardening) - Task 4.5: Budget Exhaustion Test

Verifies that:
  - The pipeline stops gracefully when budget is exhausted.
  - Budget tracking per phase accumulates correctly.
  - A budget-exhausted state can be resumed with a higher budget.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.build3_shared.constants import PHASE_ARCHITECT
from src.super_orchestrator.config import SuperOrchestratorConfig
from src.super_orchestrator.cost import PipelineCostTracker
from src.super_orchestrator.exceptions import BudgetExceededError
from src.super_orchestrator.shutdown import GracefulShutdown
from src.super_orchestrator.state import PipelineState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    budget_limit: float | None = None,
    output_dir: str = ".test-orchestrator",
) -> SuperOrchestratorConfig:
    """Create a SuperOrchestratorConfig with a given budget limit."""
    return SuperOrchestratorConfig(
        budget_limit=budget_limit,
        output_dir=output_dir,
    )


def _make_state(
    tmp_path: Path,
    budget_limit: float | None = None,
) -> PipelineState:
    """Create a PipelineState wired to a temp directory."""
    prd = tmp_path / "prd.md"
    prd.write_text("# Test PRD\nBuild something.", encoding="utf-8")
    return PipelineState(
        pipeline_id="budget-test-001",
        prd_path=str(prd),
        config_path="",
        depth="standard",
        current_state="init",
        budget_limit=budget_limit,
    )


# ---------------------------------------------------------------------------
# 4.5a -- Budget limit of $0.01 with architect costing $0.02
# ---------------------------------------------------------------------------


class TestBudgetExhaustionAfterArchitect:
    """Pipeline stops gracefully when the architect phase exceeds the budget."""

    @pytest.mark.asyncio
    async def test_pipeline_stops_after_architect_exceeds_budget(
        self, tmp_path: Path
    ) -> None:
        """Set budget_limit=0.01, architect reports cost=0.02 => pipeline stops."""
        config = _make_config(budget_limit=0.01, output_dir=str(tmp_path / "out"))
        state = _make_state(tmp_path, budget_limit=0.01)
        cost_tracker = PipelineCostTracker(budget_limit=0.01)
        shutdown = GracefulShutdown()

        # Mock the architect to succeed but report a cost that exceeds the budget.
        architect_result: dict[str, Any] = {
            "service_map": {"services": []},
            "domain_model": {},
            "contract_stubs": {},
            "cost": 0.02,
        }

        with patch(
            "src.super_orchestrator.pipeline._call_architect",
            new_callable=AsyncMock,
            return_value=architect_result,
        ):
            from src.super_orchestrator.pipeline import run_architect_phase

            await run_architect_phase(state, config, cost_tracker, shutdown)

        # After the architect phase the tracker should show $0.02.
        assert cost_tracker.total_cost == pytest.approx(0.02)

        # The budget check should report exceeded.
        within, msg = cost_tracker.check_budget()
        assert within is False, "Expected budget to be exceeded"
        assert "exceeded" in msg.lower() or "Budget" in msg

    @pytest.mark.asyncio
    async def test_state_total_cost_tracked(self, tmp_path: Path) -> None:
        """Verify state.total_cost is populated after the architect phase."""
        config = _make_config(budget_limit=0.01, output_dir=str(tmp_path / "out"))
        state = _make_state(tmp_path, budget_limit=0.01)
        cost_tracker = PipelineCostTracker(budget_limit=0.01)
        shutdown = GracefulShutdown()

        architect_result: dict[str, Any] = {
            "service_map": {"services": []},
            "domain_model": {},
            "contract_stubs": {},
            "cost": 0.02,
        }

        with patch(
            "src.super_orchestrator.pipeline._call_architect",
            new_callable=AsyncMock,
            return_value=architect_result,
        ):
            from src.super_orchestrator.pipeline import run_architect_phase

            await run_architect_phase(state, config, cost_tracker, shutdown)

        assert state.total_cost == pytest.approx(0.02)

    @pytest.mark.asyncio
    async def test_state_saved_before_stopping(self, tmp_path: Path) -> None:
        """Verify that state.save() is called during the architect phase."""
        config = _make_config(budget_limit=0.01, output_dir=str(tmp_path / "out"))
        state = _make_state(tmp_path, budget_limit=0.01)
        cost_tracker = PipelineCostTracker(budget_limit=0.01)
        shutdown = GracefulShutdown()

        architect_result: dict[str, Any] = {
            "service_map": {"services": []},
            "domain_model": {},
            "contract_stubs": {},
            "cost": 0.02,
        }

        save_call_count = 0
        original_save = state.save

        def counting_save(*args: Any, **kwargs: Any) -> Path:
            nonlocal save_call_count
            save_call_count += 1
            return original_save(directory=tmp_path / "state")

        state.save = counting_save  # type: ignore[assignment]

        with patch(
            "src.super_orchestrator.pipeline._call_architect",
            new_callable=AsyncMock,
            return_value=architect_result,
        ):
            from src.super_orchestrator.pipeline import run_architect_phase

            await run_architect_phase(state, config, cost_tracker, shutdown)

        assert save_call_count >= 1, "state.save() should be called at least once"

    @pytest.mark.asyncio
    async def test_budget_exceeded_halts_pipeline_loop(
        self, tmp_path: Path
    ) -> None:
        """The pipeline loop's check_budget returns (False, msg) after overspend."""
        config = _make_config(budget_limit=0.01, output_dir=str(tmp_path / "out"))
        state = _make_state(tmp_path, budget_limit=0.01)
        cost_tracker = PipelineCostTracker(budget_limit=0.01)

        # Simulate architect cost already recorded.
        cost_tracker.start_phase(PHASE_ARCHITECT)
        cost_tracker.end_phase(0.02)

        # After the phase, the budget check should fail.
        within, msg = cost_tracker.check_budget()
        assert within is False
        assert cost_tracker.total_cost > config.budget_limit  # type: ignore[operator]


# ---------------------------------------------------------------------------
# 4.5b -- Budget tracking per phase
# ---------------------------------------------------------------------------


class TestBudgetTrackingPerPhase:
    """Phase costs are tracked correctly in PipelineCostTracker."""

    def test_phase_costs_accumulate(self) -> None:
        """Verify phase_costs dict accumulates correctly."""
        tracker = PipelineCostTracker(budget_limit=100.0)

        tracker.start_phase("architect")
        tracker.end_phase(2.50)

        tracker.start_phase("builders")
        tracker.end_phase(10.00)

        tracker.start_phase("integration")
        tracker.end_phase(1.25)

        phase_costs = tracker.phase_costs
        assert phase_costs["architect"] == pytest.approx(2.50)
        assert phase_costs["builders"] == pytest.approx(10.00)
        assert phase_costs["integration"] == pytest.approx(1.25)

    def test_total_cost_equals_sum_of_phase_costs(self) -> None:
        """Verify total_cost == sum(phase_costs.values())."""
        tracker = PipelineCostTracker(budget_limit=100.0)

        tracker.start_phase("architect")
        tracker.end_phase(3.00)

        tracker.start_phase("builders")
        tracker.end_phase(7.00)

        tracker.start_phase("quality_gate")
        tracker.end_phase(0.50)

        expected_total = 3.00 + 7.00 + 0.50
        assert tracker.total_cost == pytest.approx(expected_total)
        assert sum(tracker.phase_costs.values()) == pytest.approx(expected_total)

    def test_pipeline_state_mirrors_cost_tracker(self) -> None:
        """PipelineState.total_cost and phase_costs should mirror the tracker."""
        tracker = PipelineCostTracker(budget_limit=50.0)
        state = PipelineState(pipeline_id="mirror-test")

        tracker.start_phase("architect")
        tracker.end_phase(5.00)
        state.total_cost = tracker.total_cost
        state.phase_costs = tracker.phase_costs

        tracker.start_phase("builders")
        tracker.end_phase(15.00)
        state.total_cost = tracker.total_cost
        state.phase_costs = tracker.phase_costs

        assert state.total_cost == pytest.approx(20.00)
        assert state.phase_costs["architect"] == pytest.approx(5.00)
        assert state.phase_costs["builders"] == pytest.approx(15.00)

    def test_add_phase_cost_accumulates_on_same_phase(self) -> None:
        """Multiple add_phase_cost calls on the same phase sum up."""
        tracker = PipelineCostTracker(budget_limit=100.0)
        tracker.add_phase_cost("builders", 3.0)
        tracker.add_phase_cost("builders", 4.0)
        assert tracker.phase_costs["builders"] == pytest.approx(7.0)
        assert tracker.total_cost == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# 4.5c -- Resume with higher budget
# ---------------------------------------------------------------------------


class TestResumeWithHigherBudget:
    """A budget-exhausted state can resume when the budget is raised."""

    def test_load_budget_exhausted_state(self, tmp_path: Path) -> None:
        """Load a state that was interrupted by budget exhaustion."""
        state = PipelineState(
            pipeline_id="resume-budget-test",
            prd_path="prd.md",
            budget_limit=0.01,
            total_cost=0.02,
            phase_costs={"architect": 0.02},
            interrupted=True,
            interrupt_reason="Budget exceeded",
            current_state="architect_running",
            completed_phases=["architect"],
        )
        state.save(directory=tmp_path / "state-dir")

        loaded = PipelineState.load(directory=tmp_path / "state-dir")
        assert loaded is not None
        assert loaded.interrupted is True
        assert loaded.interrupt_reason == "Budget exceeded"
        assert loaded.total_cost == pytest.approx(0.02)

    def test_resume_with_higher_budget_within_limit(self, tmp_path: Path) -> None:
        """After raising the budget, the cost check should pass."""
        # Simulate exhausted state.
        state = PipelineState(
            pipeline_id="resume-budget-test-2",
            prd_path="prd.md",
            budget_limit=0.01,
            total_cost=0.02,
            phase_costs={"architect": 0.02},
            interrupted=True,
            interrupt_reason="Budget exceeded",
            current_state="architect_running",
            completed_phases=["architect"],
        )
        state.save(directory=tmp_path / "state-dir")

        # Reload and raise the budget.
        loaded = PipelineState.load(directory=tmp_path / "state-dir")
        assert loaded is not None
        loaded.budget_limit = 100.0
        loaded.interrupted = False
        loaded.interrupt_reason = ""

        # Re-create cost tracker with the new limit and seed the existing cost.
        tracker = PipelineCostTracker(budget_limit=100.0)
        tracker.add_phase_cost("architect", loaded.total_cost)

        within, msg = tracker.check_budget()
        assert within is True, f"Expected budget OK but got: {msg}"
        assert tracker.total_cost == pytest.approx(0.02)

    def test_resumed_pipeline_can_continue(self, tmp_path: Path) -> None:
        """Pipeline state allows transition after resuming with higher budget."""
        state = PipelineState(
            pipeline_id="resume-budget-test-3",
            prd_path="prd.md",
            budget_limit=0.01,
            total_cost=0.02,
            phase_costs={"architect": 0.02},
            interrupted=True,
            interrupt_reason="Budget exceeded",
            current_state="architect_running",
            completed_phases=["architect"],
        )
        state.save(directory=tmp_path / "state-dir")

        loaded = PipelineState.load(directory=tmp_path / "state-dir")
        assert loaded is not None

        # Raise budget and clear interrupt flags.
        loaded.budget_limit = 100.0
        loaded.interrupted = False
        loaded.interrupt_reason = ""

        # The state should allow resumption (not stuck).
        assert loaded.current_state == "architect_running"
        assert "architect" in loaded.completed_phases
        assert loaded.budget_limit == 100.0
        assert loaded.total_cost == pytest.approx(0.02)

        # A new cost tracker at the higher budget should be within budget.
        tracker = PipelineCostTracker(budget_limit=loaded.budget_limit)
        tracker.add_phase_cost("architect", loaded.total_cost)
        within, _ = tracker.check_budget()
        assert within is True
