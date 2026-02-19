"""Pipeline cost tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PhaseCost:
    """Cost record for a single pipeline phase."""

    phase_name: str = ""
    cost_usd: float = 0.0
    start_time: str = ""
    end_time: str = ""
    sub_phases: dict[str, float] = field(default_factory=dict)


@dataclass
class PipelineCostTracker:
    """Tracks cumulative cost across pipeline phases."""

    phases: dict[str, PhaseCost] = field(default_factory=dict)
    budget_limit: float | None = None

    _current_phase: str | None = field(default=None, repr=False)
    _current_start: str = field(default="", repr=False)

    def start_phase(self, phase: str) -> None:
        """Mark the start of a phase for cost tracking.

        Args:
            phase: The phase name to start tracking.
        """
        self._current_phase = phase
        self._current_start = datetime.now(timezone.utc).isoformat()
        if phase not in self.phases:
            self.phases[phase] = PhaseCost(
                phase_name=phase,
                cost_usd=0.0,
                start_time=self._current_start,
                end_time="",
            )

    def end_phase(self, cost: float) -> None:
        """Mark the end of the current phase and record its cost.

        Args:
            cost: The cost incurred during the phase.
        """
        now = datetime.now(timezone.utc).isoformat()
        phase = self._current_phase
        if phase and phase in self.phases:
            self.phases[phase].cost_usd += cost
            self.phases[phase].end_time = now
        elif phase:
            self.phases[phase] = PhaseCost(
                phase_name=phase,
                cost_usd=cost,
                start_time=self._current_start or now,
                end_time=now,
            )
        self._current_phase = None

    @property
    def phase_costs(self) -> dict[str, float]:
        """Return a mapping of phase name to cumulative cost."""
        return {name: p.cost_usd for name, p in self.phases.items()}

    def add_phase_cost(self, phase: str, cost: float) -> None:
        """Record cost for a phase.

        If the phase already exists, its cost is updated.

        Args:
            phase: The phase name.
            cost: The cost incurred during this phase.
        """
        if phase in self.phases:
            self.phases[phase].cost_usd += cost
        else:
            self.phases[phase] = PhaseCost(
                phase_name=phase,
                cost_usd=cost,
                start_time=datetime.now(timezone.utc).isoformat(),
                end_time=datetime.now(timezone.utc).isoformat(),
            )

    @property
    def total_cost(self) -> float:
        """Total cost across all phases."""
        return sum(p.cost_usd for p in self.phases.values())

    def check_budget(self) -> tuple[bool, str]:
        """Check whether the budget has been exceeded.

        Returns:
            A tuple of (within_budget, message).  Returns ``(True, "")``
            if within budget or no limit is set.  Returns ``(False, message)``
            if the budget is exceeded.
        """
        if self.budget_limit is None:
            return (True, "")
        if self.total_cost > self.budget_limit:
            return (
                False,
                f"Budget exceeded: ${self.total_cost:.2f} spent, "
                f"limit is ${self.budget_limit:.2f}",
            )
        return (True, "")

    def to_dict(self) -> dict[str, Any]:
        """Serialise tracker state."""
        return {
            "budget_limit": self.budget_limit,
            "total_cost": self.total_cost,
            "phases": {
                name: {
                    "phase_name": p.phase_name,
                    "cost_usd": p.cost_usd,
                    "start_time": p.start_time,
                    "end_time": p.end_time,
                    "sub_phases": p.sub_phases,
                }
                for name, p in self.phases.items()
            },
        }
