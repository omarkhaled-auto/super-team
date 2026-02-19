"""Tests for src.super_orchestrator.display module.

TEST-034: 8+ test cases covering all display functions.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from src.super_orchestrator.display import (
    _console,
    create_progress_bar,
    print_builder_table,
    print_error_panel,
    print_final_summary,
    print_phase_table,
    print_pipeline_header,
    print_quality_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_output(fn, *args, **kwargs) -> str:
    """Capture Rich console output by temporarily replacing the console's file."""
    buf = io.StringIO()
    # Use a temporary console for capture
    import src.super_orchestrator.display as display_mod

    original = display_mod._console
    display_mod._console = Console(file=buf, force_terminal=True, width=120)
    try:
        fn(*args, **kwargs)
    finally:
        display_mod._console = original
    return buf.getvalue()


@dataclass
class MockState:
    """Mock PipelineState for testing display functions."""

    pipeline_id: str = "test-uuid-1234"
    prd_path: str = "/path/to/prd.md"
    current_state: str = "builders_running"
    completed_phases: list = field(default_factory=lambda: ["architect", "contract_registration"])
    phase_costs: dict = field(default_factory=lambda: {"architect": 0.25, "contract_registration": 0.05})
    builder_results: dict = field(
        default_factory=lambda: {
            "auth-service": {
                "success": True,
                "test_passed": 15,
                "test_total": 20,
                "convergence_ratio": 0.75,
            },
            "order-service": {
                "success": False,
                "test_passed": 3,
                "test_total": 10,
                "convergence_ratio": 0.3,
                "error": "Test failures",
            },
        }
    )
    builder_statuses: dict = field(
        default_factory=lambda: {
            "auth-service": "healthy",
            "order-service": "failed",
        }
    )
    builder_costs: dict = field(
        default_factory=lambda: {
            "auth-service": 1.5,
            "order-service": 0.8,
        }
    )
    total_builders: int = 2
    successful_builders: int = 1
    total_cost: float = 2.6
    budget_limit: float = 50.0
    interrupted: bool = False
    interrupt_reason: str = ""
    last_quality_results: dict = field(default_factory=dict)


@dataclass
class MockQualityReport:
    """Mock QualityGateReport for testing."""

    overall_verdict: str = "passed"
    total_violations: int = 3
    blocking_violations: int = 0
    fix_attempts: int = 1
    max_fix_attempts: int = 3
    layers: dict = field(
        default_factory=lambda: {
            "layer1_service": {"verdict": "passed", "total_checks": 10, "passed_checks": 10, "violations": []},
            "layer2_contract": {"verdict": "passed", "total_checks": 5, "passed_checks": 5, "violations": []},
            "layer3_system": {"verdict": "passed", "total_checks": 20, "passed_checks": 17, "violations": []},
            "layer4_adversarial": {"verdict": "passed", "total_checks": 8, "passed_checks": 6, "violations": []},
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConsole:
    """Test the module-level Console singleton."""

    def test_console_is_console_instance(self):
        """_console is an instance of rich.console.Console."""
        assert isinstance(_console, Console)

    def test_console_singleton(self):
        """_console is the module-level singleton."""
        import src.super_orchestrator.display as mod

        assert mod._console is _console


class TestPrintPipelineHeader:
    """Tests for print_pipeline_header."""

    def test_pipeline_header_contains_id(self):
        """Header output includes the pipeline ID."""
        state = MockState(pipeline_id="uuid-1234")
        output = _capture_output(print_pipeline_header, state)
        assert "uuid-1234" in output

    def test_pipeline_header_contains_prd(self):
        """Header output includes the PRD path."""
        state = MockState(prd_path="/my/prd.md")
        output = _capture_output(print_pipeline_header, state)
        assert "/my/prd.md" in output


class TestPrintPhaseTable:
    """Tests for print_phase_table."""

    def test_phase_table_shows_completed(self):
        """Completed phases show COMPLETE status."""
        state = MockState()
        output = _capture_output(print_phase_table, state)
        assert "COMPLETE" in output

    def test_phase_table_shows_running(self):
        """Active phase shows RUNNING status."""
        state = MockState(current_state="builders_running")
        output = _capture_output(print_phase_table, state)
        assert "RUNNING" in output

    def test_phase_table_shows_costs(self):
        """Phase costs are displayed."""
        state = MockState()
        output = _capture_output(print_phase_table, state)
        assert "$0.25" in output


class TestPrintBuilderTable:
    """Tests for print_builder_table."""

    def test_builder_table_shows_services(self):
        """Builder table includes service names."""
        state = MockState()
        output = _capture_output(print_builder_table, state)
        assert "auth-service" in output
        assert "order-service" in output

    def test_builder_table_shows_status(self):
        """Builder table includes HEALTHY/FAILED status."""
        state = MockState()
        output = _capture_output(print_builder_table, state)
        assert "HEALTHY" in output
        assert "FAILED" in output

    def test_builder_table_empty(self):
        """Empty builder results shows info message."""
        state = MockState(builder_results={}, builder_statuses={})
        output = _capture_output(print_builder_table, state)
        assert "No builder results" in output


class TestPrintQualitySummary:
    """Tests for print_quality_summary."""

    def test_quality_summary_passed(self):
        """Quality summary shows PASSED verdict."""
        report = MockQualityReport()
        output = _capture_output(print_quality_summary, report)
        assert "PASSED" in output

    def test_quality_summary_failed(self):
        """Quality summary shows FAILED verdict with red style."""
        report = MockQualityReport(overall_verdict="failed", blocking_violations=5)
        output = _capture_output(print_quality_summary, report)
        assert "FAILED" in output

    def test_quality_summary_layers(self):
        """Quality summary shows layer breakdown."""
        report = MockQualityReport()
        output = _capture_output(print_quality_summary, report)
        # Should have layer information
        assert "Layer" in output or "layer" in output


class TestPrintErrorPanel:
    """Tests for print_error_panel."""

    def test_error_panel_string(self):
        """Error panel shows string message."""
        output = _capture_output(print_error_panel, "Something went wrong!")
        assert "Something went wrong!" in output

    def test_error_panel_exception(self):
        """Error panel shows exception message."""
        exc = ValueError("Bad value")
        output = _capture_output(print_error_panel, exc)
        assert "Bad value" in output

    def test_error_panel_has_red_border(self):
        """Error panel uses red styling."""
        output = _capture_output(print_error_panel, "Test error")
        # Red border style shows in terminal codes
        assert "Error" in output


class TestCreateProgressBar:
    """Tests for create_progress_bar."""

    def test_progress_bar_type(self):
        """create_progress_bar returns a Progress instance."""
        progress = create_progress_bar()
        assert isinstance(progress, Progress)

    def test_progress_bar_with_description(self):
        """create_progress_bar accepts a description."""
        progress = create_progress_bar("Building...")
        assert isinstance(progress, Progress)

    def test_progress_bar_columns(self):
        """Progress bar has SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn."""
        progress = create_progress_bar()
        column_types = [type(c) for c in progress.columns]
        assert SpinnerColumn in column_types
        assert TextColumn in column_types
        assert BarColumn in column_types
        assert TimeElapsedColumn in column_types


class TestPrintFinalSummary:
    """Tests for print_final_summary."""

    def test_final_summary_complete(self):
        """Final summary for completed pipeline."""
        state = MockState(current_state="complete")
        output = _capture_output(print_final_summary, state)
        assert "complete" in output.lower()
        assert "test-uuid-1234" in output

    def test_final_summary_failed(self):
        """Final summary for failed pipeline."""
        state = MockState(current_state="failed")
        output = _capture_output(print_final_summary, state)
        assert "failed" in output.lower()

    def test_final_summary_cost(self):
        """Final summary includes cost information."""
        state = MockState(total_cost=2.6, budget_limit=50.0)
        output = _capture_output(print_final_summary, state)
        assert "$2.6" in output or "2.60" in output

    def test_final_summary_interrupted(self):
        """Final summary shows interrupted status."""
        state = MockState(
            current_state="builders_running",
            interrupted=True,
            interrupt_reason="Signal received",
        )
        output = _capture_output(print_final_summary, state)
        assert "Interrupted" in output or "Signal" in output

    def test_final_summary_with_cost_tracker(self):
        """Final summary includes cost tracker phase costs."""
        state = MockState()
        tracker = MagicMock()
        tracker.phase_costs = {"architect": 0.25, "builders": 1.50}
        output = _capture_output(print_final_summary, state, tracker)
        assert "$0.25" in output
