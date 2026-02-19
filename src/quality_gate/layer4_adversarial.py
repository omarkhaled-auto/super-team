"""Layer 4 Quality Gate -- Adversarial Analysis (Advisory-Only).

Wraps the :class:`AdversarialScanner` to provide static heuristic analysis
of the codebase for adversarial patterns such as dead event handlers, dead
contracts, orphan services, naming inconsistencies, missing error handling,
and potential race conditions.

**This layer is strictly advisory.**  The verdict is *always*
:attr:`GateVerdict.PASSED` regardless of any findings.  Violations are
surfaced in the :class:`LayerResult` for observability and developer
awareness, but they never block the build pipeline.
"""

from __future__ import annotations

import time
from pathlib import Path

from src.build3_shared.models import (
    GateVerdict,
    LayerResult,
    QualityLevel,
    ScanViolation,
)
from src.quality_gate.adversarial_patterns import AdversarialScanner


class Layer4Scanner:
    """Layer 4: Adversarial analysis (advisory-only).

    Wraps the :class:`AdversarialScanner` for static heuristic analysis.
    The verdict is **always** :attr:`GateVerdict.PASSED` -- findings are
    advisory and never block the pipeline.

    Usage
    -----
    ::

        scanner = Layer4Scanner()
        result = await scanner.evaluate(Path("src/"))
        # result.verdict is always GateVerdict.PASSED
        # result.violations contains advisory findings
    """

    def __init__(self) -> None:
        self._scanner = AdversarialScanner()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(self, target_dir: Path) -> LayerResult:
        """Run adversarial analysis on *target_dir*.

        Parameters
        ----------
        target_dir:
            Root directory to scan for adversarial patterns.

        Returns
        -------
        LayerResult
            Always carries ``verdict=GateVerdict.PASSED``.  The
            ``violations`` list contains any advisory findings produced
            by the underlying :class:`AdversarialScanner`.
        """
        start = time.monotonic()
        violations: list[ScanViolation] = await self._scanner.scan(target_dir)
        duration = time.monotonic() - start

        # Advisory-only: verdict is ALWAYS PASSED regardless of findings.
        return LayerResult(
            layer=QualityLevel.LAYER4_ADVERSARIAL,
            verdict=GateVerdict.PASSED,
            violations=violations,
            total_checks=len(violations),
            passed_checks=len(violations),  # All findings are advisory
            duration_seconds=duration,
        )
