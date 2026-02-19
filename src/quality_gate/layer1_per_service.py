"""Layer 1 quality gate: per-service build result evaluation.

Evaluates the aggregate builder results to determine whether individual
service builds meet the minimum quality bar for pass rate and convergence.
"""

from __future__ import annotations

import time

from src.build3_shared.models import (
    BuilderResult,
    GateVerdict,
    LayerResult,
    QualityLevel,
    ScanViolation,
)


class Layer1Scanner:
    """Evaluates per-service builder results against quality thresholds.

    Thresholds
    ----------
    PASS_RATE_THRESHOLD : float
        Minimum fraction of builders that must report ``success=True``
        for the gate to fully pass (default 0.9 / 90 %).
    CONVERGENCE_THRESHOLD : float
        Minimum average ``convergence_ratio`` across all builders
        for the gate to fully pass (default 0.9).
    PARTIAL_THRESHOLD : float
        If either the pass rate or the average convergence ratio meets
        this lower bar the verdict is PARTIAL instead of FAILED
        (default 0.7 / 70 %).
    """

    PASS_RATE_THRESHOLD: float = 0.9
    CONVERGENCE_THRESHOLD: float = 0.9
    PARTIAL_THRESHOLD: float = 0.7

    # -- public API -----------------------------------------------------------

    def evaluate(self, builder_results: list[BuilderResult]) -> LayerResult:
        """Run the Layer 1 quality gate over *builder_results*.

        Parameters
        ----------
        builder_results:
            Outcomes produced by the build pipeline for each service.

        Returns
        -------
        LayerResult
            Contains the verdict, any violations found, and timing info.
        """
        start = time.monotonic()

        # Fast-path: nothing to evaluate.
        if not builder_results:
            duration = time.monotonic() - start
            return LayerResult(
                layer=QualityLevel.LAYER1_SERVICE,
                verdict=GateVerdict.SKIPPED,
                violations=[],
                total_checks=0,
                passed_checks=0,
                duration_seconds=duration,
            )

        # -- metrics ----------------------------------------------------------
        total = len(builder_results)
        passed_count = sum(1 for br in builder_results if br.success)
        pass_rate = passed_count / total

        avg_convergence = (
            sum(br.convergence_ratio for br in builder_results) / total
        )

        # -- violations -------------------------------------------------------
        violations: list[ScanViolation] = []

        for br in builder_results:
            if not br.success:
                reason = br.error if br.error else "Builder reported failure"
                violations.append(
                    ScanViolation(
                        code="L1-FAIL",
                        severity="error",
                        category="layer1",
                        message=(
                            f"Service '{br.service_id}' build failed: {reason}"
                        ),
                        file_path="",
                        line=0,
                    )
                )

        if avg_convergence < self.CONVERGENCE_THRESHOLD:
            violations.append(
                ScanViolation(
                    code="L1-CONVERGENCE",
                    severity="warning",
                    category="layer1",
                    message=(
                        f"Average convergence ratio {avg_convergence:.4f} "
                        f"is below threshold {self.CONVERGENCE_THRESHOLD}"
                    ),
                    file_path="",
                    line=0,
                )
            )

        # -- verdict ----------------------------------------------------------
        verdict = self._determine_verdict(pass_rate, avg_convergence)

        duration = time.monotonic() - start
        return LayerResult(
            layer=QualityLevel.LAYER1_SERVICE,
            verdict=verdict,
            violations=violations,
            total_checks=total,
            passed_checks=passed_count,
            duration_seconds=duration,
        )

    # -- internals ------------------------------------------------------------

    def _determine_verdict(
        self, pass_rate: float, avg_convergence: float
    ) -> GateVerdict:
        """Map pass-rate and convergence metrics to a gate verdict."""
        if (
            pass_rate >= self.PASS_RATE_THRESHOLD
            and avg_convergence >= self.CONVERGENCE_THRESHOLD
        ):
            return GateVerdict.PASSED

        if (
            pass_rate >= self.PARTIAL_THRESHOLD
            or avg_convergence >= self.PARTIAL_THRESHOLD
        ):
            return GateVerdict.PARTIAL

        return GateVerdict.FAILED
