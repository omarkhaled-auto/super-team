"""Tests for the pipeline state machine.

TEST-001: >= 20 test cases covering 13 transitions, guards, fail trigger, resume.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from transitions import State

from src.super_orchestrator.state_machine import (
    RESUME_TRIGGERS,
    STATES,
    TRANSITIONS,
    create_pipeline_machine,
)


# ---------------------------------------------------------------------------
# State Machine Model stub -- provides all guard methods
# ---------------------------------------------------------------------------
class PipelineModel:
    """Stub model implementing all guard conditions."""

    def __init__(self) -> None:
        self.state: str = "init"
        # Guard flags
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

    # on_enter callbacks (required by State objects)
    def on_enter_init(self, *args, **kwargs): pass
    def on_enter_architect_running(self, *args, **kwargs): pass
    def on_enter_architect_review(self, *args, **kwargs): pass
    def on_enter_contracts_registering(self, *args, **kwargs): pass
    def on_enter_builders_running(self, *args, **kwargs): pass
    def on_enter_builders_complete(self, *args, **kwargs): pass
    def on_enter_integrating(self, *args, **kwargs): pass
    def on_enter_quality_gate(self, *args, **kwargs): pass
    def on_enter_fix_pass(self, *args, **kwargs): pass
    def on_enter_complete(self, *args, **kwargs): pass
    def on_enter_failed(self, *args, **kwargs): pass

    def is_configured(self, *args, **kwargs) -> bool:
        return self._configured

    def has_service_map(self, *args, **kwargs) -> bool:
        return self._has_service_map

    def service_map_valid(self, *args, **kwargs) -> bool:
        return self._service_map_valid

    def contracts_valid(self, *args, **kwargs) -> bool:
        return self._contracts_valid

    def has_builder_results(self, *args, **kwargs) -> bool:
        return self._has_builder_results

    def any_builder_passed(self, *args, **kwargs) -> bool:
        return self._any_builder_passed

    def has_integration_report(self, *args, **kwargs) -> bool:
        return self._has_integration_report

    def gate_passed(self, *args, **kwargs) -> bool:
        return self._gate_passed

    def fix_attempts_remaining(self, *args, **kwargs) -> bool:
        return self._fix_attempts_remaining

    def fix_applied(self, *args, **kwargs) -> bool:
        return self._fix_applied

    def retries_remaining(self, *args, **kwargs) -> bool:
        return self._retries_remaining

    def advisory_only(self, *args, **kwargs) -> bool:
        return self._advisory_only


# ===========================================================================
# TEST-001: State Machine Tests (>= 20 cases)
# ===========================================================================

class TestStateMachineConstants:
    """Verify state machine constants."""

    def test_states_count(self) -> None:
        assert len(STATES) == 11

    def test_transitions_count(self) -> None:
        assert len(TRANSITIONS) == 13

    def test_resume_triggers_defined(self) -> None:
        assert len(RESUME_TRIGGERS) >= 8

    def test_all_states_are_state_objects(self) -> None:
        for s in STATES:
            assert isinstance(s, State)

    def test_init_is_first_state(self) -> None:
        assert STATES[0].name == "init"

    def test_complete_and_failed_in_states(self) -> None:
        state_names = [s.name for s in STATES]
        assert "complete" in state_names
        assert "failed" in state_names


class TestStateMachineTransitions:
    """Test state machine transitions."""

    @pytest.fixture
    def model(self) -> PipelineModel:
        return PipelineModel()

    @pytest.fixture
    def machine(self, model: PipelineModel):
        return create_pipeline_machine(model)

    @pytest.mark.asyncio
    async def test_init_to_architect_running(self, model, machine) -> None:
        assert model.state == "init"
        await model.start_architect()
        assert model.state == "architect_running"

    @pytest.mark.asyncio
    async def test_architect_running_to_review(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        assert model.state == "architect_review"

    @pytest.mark.asyncio
    async def test_architect_review_to_contracts(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        assert model.state == "contracts_registering"

    @pytest.mark.asyncio
    async def test_contracts_to_builders(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        assert model.state == "builders_running"

    @pytest.mark.asyncio
    async def test_builders_to_complete(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        assert model.state == "builders_complete"

    @pytest.mark.asyncio
    async def test_builders_complete_to_integrating(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        assert model.state == "integrating"

    @pytest.mark.asyncio
    async def test_integrating_to_quality_gate(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()
        assert model.state == "quality_gate"

    @pytest.mark.asyncio
    async def test_quality_gate_passed(self, model, machine) -> None:
        # Full pipeline to quality_gate
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()
        await model.quality_passed()
        assert model.state == "complete"

    @pytest.mark.asyncio
    async def test_quality_gate_needs_fix(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()
        model._gate_passed = False
        await model.quality_needs_fix()
        assert model.state == "fix_pass"

    @pytest.mark.asyncio
    async def test_fix_pass_to_builders(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()
        model._gate_passed = False
        await model.quality_needs_fix()
        await model.fix_done()
        assert model.state == "builders_running"

    @pytest.mark.asyncio
    async def test_fail_from_any_state(self, model, machine) -> None:
        await model.start_architect()
        assert model.state == "architect_running"
        await model.fail()
        assert model.state == "failed"

    @pytest.mark.asyncio
    async def test_fail_from_init(self, model, machine) -> None:
        assert model.state == "init"
        await model.fail()
        assert model.state == "failed"

    @pytest.mark.asyncio
    async def test_fail_ignored_from_complete(self, model, machine) -> None:
        """Fail trigger must NOT transition from complete to failed."""
        # Walk to complete state
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()
        await model.quality_passed()
        assert model.state == "complete"
        # Fail trigger should be ignored -- complete is excluded from fail's source list
        await model.fail()
        assert model.state == "complete"

    @pytest.mark.asyncio
    async def test_fail_ignored_from_failed(self, model, machine) -> None:
        """Fail trigger must NOT transition from failed to failed (no self-loop)."""
        await model.fail()
        assert model.state == "failed"
        # Fail again -- should stay in failed (failed excluded from source list)
        await model.fail()
        assert model.state == "failed"

    @pytest.mark.asyncio
    async def test_retry_architect(self, model, machine) -> None:
        await model.start_architect()
        await model.retry_architect()
        assert model.state == "architect_running"

    @pytest.mark.asyncio
    async def test_skip_to_complete(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()
        await model.skip_to_complete()
        assert model.state == "complete"


class TestStateMachineGuards:
    """Test guard conditions block transitions."""

    @pytest.fixture
    def model(self) -> PipelineModel:
        return PipelineModel()

    @pytest.fixture
    def machine(self, model: PipelineModel):
        return create_pipeline_machine(model)

    @pytest.mark.asyncio
    async def test_guard_blocks_start_architect(self, model, machine) -> None:
        model._configured = False
        result = await model.start_architect()
        # When guard fails, transition doesn't happen
        assert model.state == "init"

    @pytest.mark.asyncio
    async def test_guard_blocks_architect_done(self, model, machine) -> None:
        await model.start_architect()
        model._has_service_map = False
        await model.architect_done()
        assert model.state == "architect_running"

    @pytest.mark.asyncio
    async def test_guard_blocks_quality_passed(self, model, machine) -> None:
        # Navigate to quality_gate
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()
        model._gate_passed = False
        await model.quality_passed()
        assert model.state == "quality_gate"

    @pytest.mark.asyncio
    async def test_guard_blocks_fix_no_attempts(self, model, machine) -> None:
        await model.start_architect()
        await model.architect_done()
        await model.approve_architect()
        await model.contracts_registered()
        await model.builders_done()
        await model.start_integration()
        await model.integration_done()
        model._fix_attempts_remaining = False
        await model.quality_needs_fix()
        assert model.state == "quality_gate"

    @pytest.mark.asyncio
    async def test_guard_blocks_retry_architect(self, model, machine) -> None:
        await model.start_architect()
        model._retries_remaining = False
        await model.retry_architect()
        assert model.state == "architect_running"


class TestResumeTriggersMap:
    """Test resume trigger mapping."""

    def test_resume_from_init(self) -> None:
        assert RESUME_TRIGGERS["init"] == "start_architect"

    def test_resume_from_architect_running(self) -> None:
        assert RESUME_TRIGGERS["architect_running"] is None

    def test_resume_from_builders_complete(self) -> None:
        assert RESUME_TRIGGERS["builders_complete"] == "start_integration"

    def test_resume_from_quality_gate(self) -> None:
        assert RESUME_TRIGGERS["quality_gate"] is None

    def test_resume_from_fix_pass(self) -> None:
        assert RESUME_TRIGGERS["fix_pass"] is None

    def test_all_interruptible_states_have_resume(self) -> None:
        state_names = [s.name for s in STATES]
        interruptible = [s for s in state_names if s not in ("complete", "failed")]
        for s in interruptible:
            assert s in RESUME_TRIGGERS, f"Missing resume trigger for {s}"

    def test_terminal_states_not_in_resume(self) -> None:
        assert "complete" not in RESUME_TRIGGERS
        assert "failed" not in RESUME_TRIGGERS
