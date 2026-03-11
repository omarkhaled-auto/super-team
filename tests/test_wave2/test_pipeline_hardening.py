"""Wave 2 tests for pipeline hardening.

Tests that the pipeline handles crashes via state machine fail transitions,
saves state before re-raising, and handles builder isolation correctly.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.super_orchestrator.state_machine import (
    STATES,
    TRANSITIONS,
    create_pipeline_machine,
)


# ---------------------------------------------------------------------------
# Reusable state machine model stub
# ---------------------------------------------------------------------------


class PipelineModel:
    """Stub model implementing all guard conditions for the state machine."""

    def __init__(self) -> None:
        self.state: str = "init"
        self._configured = True
        self._has_service_map = True
        self._service_map_valid = True
        self._contracts_valid = True
        self._has_builder_results = True
        self._any_builder_passed = True
        self._has_integration_report = True
        self._gate_passed = True
        self._fix_attempts_remaining = True
        self._fix_applied = True
        self._retries_remaining = True
        self._advisory_only = True

    def on_enter_init(self, *a, **kw): pass
    def on_enter_architect_running(self, *a, **kw): pass
    def on_enter_architect_review(self, *a, **kw): pass
    def on_enter_contracts_registering(self, *a, **kw): pass
    def on_enter_builders_running(self, *a, **kw): pass
    def on_enter_builders_complete(self, *a, **kw): pass
    def on_enter_integrating(self, *a, **kw): pass
    def on_enter_quality_gate(self, *a, **kw): pass
    def on_enter_fix_pass(self, *a, **kw): pass
    def on_enter_complete(self, *a, **kw): pass
    def on_enter_failed(self, *a, **kw): pass

    def is_configured(self, *a, **kw) -> bool: return self._configured
    def has_service_map(self, *a, **kw) -> bool: return self._has_service_map
    def service_map_valid(self, *a, **kw) -> bool: return self._service_map_valid
    def contracts_valid(self, *a, **kw) -> bool: return self._contracts_valid
    def has_builder_results(self, *a, **kw) -> bool: return self._has_builder_results
    def any_builder_passed(self, *a, **kw) -> bool: return self._any_builder_passed
    def has_integration_report(self, *a, **kw) -> bool: return self._has_integration_report
    def gate_passed(self, *a, **kw) -> bool: return self._gate_passed
    def fix_attempts_remaining(self, *a, **kw) -> bool: return self._fix_attempts_remaining
    def fix_applied(self, *a, **kw) -> bool: return self._fix_applied
    def retries_remaining(self, *a, **kw) -> bool: return self._retries_remaining
    def advisory_only(self, *a, **kw) -> bool: return self._advisory_only


# ---------------------------------------------------------------------------
# 1. Pipeline crash -> failed state transition
# ---------------------------------------------------------------------------


class TestPipelineCrashStateTransition:
    """Pipeline crash transitions the state machine to 'failed'."""

    @pytest.mark.asyncio
    async def test_fail_trigger_from_architect_running(self):
        """fail trigger from architect_running transitions to failed."""
        model = PipelineModel()
        machine = create_pipeline_machine(model, initial_state="architect_running")
        await model.fail()
        assert model.state == "failed"

    @pytest.mark.asyncio
    async def test_fail_trigger_from_builders_running(self):
        """fail trigger from builders_running transitions to failed."""
        model = PipelineModel()
        machine = create_pipeline_machine(model, initial_state="builders_running")
        await model.fail()
        assert model.state == "failed"

    @pytest.mark.asyncio
    async def test_fail_trigger_from_integrating(self):
        """fail trigger from integrating transitions to failed."""
        model = PipelineModel()
        machine = create_pipeline_machine(model, initial_state="integrating")
        await model.fail()
        assert model.state == "failed"


# ---------------------------------------------------------------------------
# 2. State saved before re-raise
# ---------------------------------------------------------------------------


class TestStateSavedBeforeReRaise:
    """Pipeline saves state before re-raising exceptions."""

    @pytest.mark.asyncio
    async def test_architect_phase_saves_state_on_failure(self):
        """run_architect_phase calls state.save() when the architect fails."""
        from src.super_orchestrator.pipeline import run_architect_phase
        from src.super_orchestrator.state import PipelineState
        from src.super_orchestrator.cost import PipelineCostTracker
        from src.super_orchestrator.shutdown import GracefulShutdown
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            prd_path = Path(tmpdir) / "prd.md"
            prd_path.write_text("# Test PRD\nThis is a test PRD document for the system.\n")

            state = PipelineState()
            state.prd_path = str(prd_path)
            state.save = MagicMock()

            config = MagicMock()
            config.output_dir = tmpdir
            config.architect.max_retries = 1  # Allow 1 retry so save is called after 1st failure
            config.architect.timeout = 10

            cost_tracker = PipelineCostTracker()
            shutdown = GracefulShutdown()

            with patch(
                "src.super_orchestrator.pipeline._call_architect",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Architect failed"),
            ):
                with pytest.raises(Exception):
                    await run_architect_phase(state, config, cost_tracker, shutdown)

            # state.save() should be called between retries (after first failure)
            assert state.save.called


# ---------------------------------------------------------------------------
# 3. State machine transition verification
# ---------------------------------------------------------------------------


class TestStateMachineTransitions:
    """All expected state machine transitions work correctly."""

    @pytest.mark.asyncio
    async def test_happy_path_transitions(self):
        """The normal flow init -> ... -> complete transitions correctly."""
        model = PipelineModel()
        machine = create_pipeline_machine(model, initial_state="init")

        await model.start_architect()
        assert model.state == "architect_running"

        await model.architect_done()
        assert model.state == "architect_review"

        await model.approve_architect()
        assert model.state == "contracts_registering"

        await model.contracts_registered()
        assert model.state == "builders_running"

        await model.builders_done()
        assert model.state == "builders_complete"

        await model.start_integration()
        assert model.state == "integrating"

        await model.integration_done()
        assert model.state == "quality_gate"

        await model.quality_passed()
        assert model.state == "complete"
