"""Wave 2 tests for MCP error handling -- state machine fail transitions.

Tests that the 'fail' trigger works from every non-terminal state.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.super_orchestrator.state_machine import (
    STATES,
    TRANSITIONS,
    create_pipeline_machine,
)


# ---------------------------------------------------------------------------
# Reusable state machine model stub (matches existing test_state_machine.py)
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

    # on_enter callbacks
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

    # Guard methods
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
# 1. State machine fail transition
# ---------------------------------------------------------------------------


class TestFailTransitionFromEveryState:
    """The 'fail' trigger works from every non-terminal state."""

    @pytest.mark.parametrize(
        "source_state",
        [
            "init",
            "architect_running",
            "architect_review",
            "contracts_registering",
            "builders_running",
            "builders_complete",
            "integrating",
            "quality_gate",
            "fix_pass",
        ],
    )
    @pytest.mark.asyncio
    async def test_fail_from_non_terminal_state(self, source_state: str):
        """The 'fail' trigger transitions from every non-terminal state to 'failed'."""
        model = PipelineModel()
        machine = create_pipeline_machine(model, initial_state=source_state)
        await model.fail()
        assert model.state == "failed"

    @pytest.mark.asyncio
    async def test_fail_not_from_complete(self):
        """The 'fail' trigger does NOT work from 'complete' state."""
        model = PipelineModel()
        machine = create_pipeline_machine(model, initial_state="complete")
        await model.fail()
        assert model.state == "complete"

    @pytest.mark.asyncio
    async def test_fail_not_from_failed(self):
        """The 'fail' trigger does NOT work from 'failed' state."""
        model = PipelineModel()
        machine = create_pipeline_machine(model, initial_state="failed")
        await model.fail()
        assert model.state == "failed"
