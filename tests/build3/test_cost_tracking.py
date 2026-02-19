"""Tests for PipelineCostTracker.

TEST-003: >= 8 test cases.
"""

from __future__ import annotations

import pytest

from src.super_orchestrator.cost import PhaseCost, PipelineCostTracker


class TestPhaseCost:
    """Test PhaseCost dataclass."""

    def test_default_values(self) -> None:
        pc = PhaseCost()
        assert pc.phase_name == ""
        assert pc.cost_usd == 0.0
        assert pc.start_time == ""
        assert pc.end_time == ""
        assert pc.sub_phases == {}

    def test_custom_values(self) -> None:
        pc = PhaseCost(phase_name="architect", cost_usd=2.5, start_time="t1", end_time="t2")
        assert pc.phase_name == "architect"
        assert pc.cost_usd == 2.5


class TestPipelineCostTracker:
    """Test PipelineCostTracker."""

    def test_initial_total_cost_zero(self) -> None:
        tracker = PipelineCostTracker()
        assert tracker.total_cost == 0.0

    def test_add_phase_cost(self) -> None:
        tracker = PipelineCostTracker()
        tracker.add_phase_cost("architect", 3.0)
        assert tracker.total_cost == 3.0
        assert "architect" in tracker.phases
        assert tracker.phases["architect"].cost_usd == 3.0

    def test_multiple_phases_accumulate(self) -> None:
        tracker = PipelineCostTracker()
        tracker.add_phase_cost("architect", 2.0)
        tracker.add_phase_cost("builders", 5.0)
        assert tracker.total_cost == 7.0

    def test_same_phase_accumulates(self) -> None:
        tracker = PipelineCostTracker()
        tracker.add_phase_cost("architect", 2.0)
        tracker.add_phase_cost("architect", 3.0)
        assert tracker.phases["architect"].cost_usd == 5.0
        assert tracker.total_cost == 5.0

    def test_check_budget_under_limit(self) -> None:
        tracker = PipelineCostTracker(budget_limit=10.0)
        tracker.add_phase_cost("architect", 5.0)
        within, msg = tracker.check_budget()
        assert within is True
        assert msg == ""

    def test_check_budget_exceeded(self) -> None:
        tracker = PipelineCostTracker(budget_limit=5.0)
        tracker.add_phase_cost("architect", 6.0)
        within, msg = tracker.check_budget()
        assert within is False
        assert "exceeded" in msg.lower() or "Budget" in msg

    def test_check_budget_no_limit(self) -> None:
        tracker = PipelineCostTracker(budget_limit=None)
        tracker.add_phase_cost("architect", 1000.0)
        within, msg = tracker.check_budget()
        assert within is True
        assert msg == ""

    def test_to_dict(self) -> None:
        tracker = PipelineCostTracker(budget_limit=25.0)
        tracker.add_phase_cost("architect", 3.0)
        d = tracker.to_dict()
        assert d["budget_limit"] == 25.0
        assert d["total_cost"] == 3.0
        assert "architect" in d["phases"]
        assert d["phases"]["architect"]["phase_name"] == "architect"
        assert d["phases"]["architect"]["cost_usd"] == 3.0
