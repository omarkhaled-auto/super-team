"""Pipeline state machine using the ``transitions`` library.

Defines 11 states, 13 transitions (each with a guard condition),
and resume triggers for re-entering the pipeline from any interrupted state.
"""

from __future__ import annotations

import logging
from typing import Any

from transitions.extensions.asyncio import AsyncMachine, AsyncState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# States -- exactly 11 (AsyncState objects for async state machine)
# State transitions are handled by phase handlers in the pipeline loop
# ---------------------------------------------------------------------------
STATES: list[AsyncState] = [
    AsyncState("init"),
    AsyncState("architect_running"),
    AsyncState("architect_review"),
    AsyncState("contracts_registering"),
    AsyncState("builders_running"),
    AsyncState("builders_complete"),
    AsyncState("integrating"),
    AsyncState("quality_gate"),
    AsyncState("fix_pass"),
    AsyncState("complete"),
    AsyncState("failed"),
]

# ---------------------------------------------------------------------------
# Transitions -- exactly 13
# ---------------------------------------------------------------------------
TRANSITIONS: list[dict[str, Any]] = [
    {
        "trigger": "start_architect",
        "source": "init",
        "dest": "architect_running",
        "conditions": ["is_configured"],
    },
    {
        "trigger": "architect_done",
        "source": "architect_running",
        "dest": "architect_review",
        "conditions": ["has_service_map"],
    },
    {
        "trigger": "approve_architect",
        "source": "architect_review",
        "dest": "contracts_registering",
        "conditions": ["service_map_valid"],
    },
    {
        "trigger": "contracts_registered",
        "source": "contracts_registering",
        "dest": "builders_running",
        "conditions": ["contracts_valid"],
    },
    {
        "trigger": "builders_done",
        "source": "builders_running",
        "dest": "builders_complete",
        "conditions": ["has_builder_results"],
    },
    {
        "trigger": "start_integration",
        "source": "builders_complete",
        "dest": "integrating",
        "conditions": ["any_builder_passed"],
    },
    {
        "trigger": "integration_done",
        "source": "integrating",
        "dest": "quality_gate",
        "conditions": ["has_integration_report"],
    },
    {
        "trigger": "quality_passed",
        "source": "quality_gate",
        "dest": "complete",
        "conditions": ["gate_passed"],
    },
    {
        "trigger": "quality_needs_fix",
        "source": "quality_gate",
        "dest": "fix_pass",
        "conditions": ["fix_attempts_remaining"],
    },
    {
        "trigger": "fix_done",
        "source": "fix_pass",
        "dest": "builders_running",
        "conditions": ["fix_applied"],
    },
    {
        "trigger": "fail",
        "source": [
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
        "dest": "failed",
    },
    {
        "trigger": "retry_architect",
        "source": "architect_running",
        "dest": "architect_running",
        "conditions": ["retries_remaining"],
    },
    {
        "trigger": "skip_to_complete",
        "source": "quality_gate",
        "dest": "complete",
        "conditions": ["advisory_only"],
    },
]

# ---------------------------------------------------------------------------
# Resume triggers -- map interrupted state -> trigger to re-enter
# ---------------------------------------------------------------------------
RESUME_TRIGGERS: dict[str, str | None] = {
    "init": "start_architect",
    "architect_running": None,
    "architect_review": None,
    "contracts_registering": None,
    "builders_running": None,
    "builders_complete": "start_integration",
    "integrating": None,
    "quality_gate": None,
    "fix_pass": None,
}


def create_pipeline_machine(
    model: Any, initial_state: str = "init"
) -> AsyncMachine:
    """Create and return an ``AsyncMachine`` bound to *model*.

    The model object must implement the guard methods referenced in
    ``TRANSITIONS`` (e.g. ``is_configured``, ``has_service_map``, ...).
    These are expected to be simple boolean-returning methods.

    Args:
        model: The object whose state the machine manages.
        initial_state: The initial state for the machine.

    Returns:
        Configured ``AsyncMachine`` instance.
    """
    machine = AsyncMachine(
        model=model,
        states=STATES,
        transitions=TRANSITIONS,
        initial=initial_state,
        auto_transitions=False,
        send_event=True,
        queued=True,
        ignore_invalid_triggers=True,
    )
    return machine
