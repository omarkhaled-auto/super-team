"""Custom exceptions for the Super Orchestrator pipeline."""

from __future__ import annotations


class PipelineError(Exception):
    """Base exception for all pipeline errors."""

    pass


class PhaseTimeoutError(PipelineError):
    """Raised when a pipeline phase exceeds its timeout."""

    def __init__(self, phase_name: str, timeout: int) -> None:
        self.phase_name = phase_name
        self.timeout = timeout
        super().__init__(f"Phase '{phase_name}' timed out after {timeout}s")


class BudgetExceededError(PipelineError):
    """Raised when pipeline cost exceeds the budget limit."""

    def __init__(self, total_cost: float, budget_limit: float) -> None:
        self.total_cost = total_cost
        self.budget_limit = budget_limit
        super().__init__(
            f"Budget exceeded: ${total_cost:.2f} spent, limit is ${budget_limit:.2f}"
        )


class ConfigurationError(PipelineError):
    """Raised for configuration issues (missing deps, bad config, etc.)."""

    pass


class BuilderFailureError(PipelineError):
    """Raised when all builders fail."""

    def __init__(self, service_id: str = "", message: str = "") -> None:
        self.service_id = service_id
        super().__init__(message or f"Builder failed for service '{service_id}'")


class IntegrationFailureError(PipelineError):
    """Raised when the integration phase fails."""

    pass


class QualityGateFailureError(PipelineError):
    """Raised when the quality gate fails after max retries."""

    def __init__(self, layer: str = "", message: str = "") -> None:
        self.layer = layer
        super().__init__(message or f"Quality gate failed at layer '{layer}'")
