"""Runtime-checkable protocols for Build 3 phase executors and scanners."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from src.build3_shared.models import ScanViolation


@runtime_checkable
class PhaseExecutor(Protocol):
    """Protocol for pipeline phase executors."""

    async def execute(self, context: Any) -> float:
        """Execute a pipeline phase.

        Args:
            context: The current pipeline context.

        Returns:
            Cost of the phase execution.
        """
        ...

    async def can_execute(self, context: Any) -> bool:
        """Check whether this phase can execute given the current context.

        Args:
            context: The current pipeline context.

        Returns:
            True if the phase can proceed.
        """
        ...


@runtime_checkable
class QualityScanner(Protocol):
    """Protocol for quality gate scanners."""

    def scan(self, project_root: Path) -> list[ScanViolation]:
        """Scan a project root directory for violations.

        Args:
            project_root: Root directory to scan.

        Returns:
            List of violations found.
        """
        ...

    @property
    def scan_codes(self) -> list[str]:
        """Return the list of scan codes this scanner checks."""
        ...
