"""Scan aggregator for the quality gate engine.

Aggregates layer-level scan results into a unified QualityGateReport,
deduplicating violations and computing an overall verdict.
"""

from __future__ import annotations

from src.build3_shared.models import (
    GateVerdict,
    LayerResult,
    QualityGateReport,
    ScanViolation,
)


class ScanAggregator:
    """Aggregates quality gate layer results into a final report.

    Collects violations from every layer, removes duplicates, counts
    blocking issues, and derives the overall gate verdict.
    """

    def aggregate(
        self,
        layer_results: dict[str, LayerResult],
        fix_attempts: int = 0,
        max_fix_attempts: int = 3,
    ) -> QualityGateReport:
        """Produce a single QualityGateReport from per-layer results.

        Args:
            layer_results: Mapping of layer name to its LayerResult.
            fix_attempts: Number of auto-fix attempts already made.
            max_fix_attempts: Maximum auto-fix attempts allowed.

        Returns:
            A fully populated QualityGateReport.
        """
        all_violations: list[ScanViolation] = []
        for layer_result in layer_results.values():
            all_violations.extend(layer_result.violations)

        unique_violations = self._deduplicate(all_violations)
        blocking_count = self._count_blocking(unique_violations)
        overall_verdict = self._compute_verdict(layer_results)

        return QualityGateReport(
            overall_verdict=overall_verdict,
            layers=dict(layer_results),
            fix_attempts=fix_attempts,
            max_fix_attempts=max_fix_attempts,
            total_violations=len(unique_violations),
            blocking_violations=blocking_count,
        )

    def _deduplicate(
        self, violations: list[ScanViolation]
    ) -> list[ScanViolation]:
        """Remove duplicate violations, keeping the first occurrence.

        Duplicates are identified by the (code, file_path, line) tuple.

        Args:
            violations: Full list of violations (may contain duplicates).

        Returns:
            A deduplicated list preserving original insertion order.
        """
        seen: set[tuple[str, str, int]] = set()
        unique: list[ScanViolation] = []

        for violation in violations:
            key = (violation.code, violation.file_path, violation.line)
            if key not in seen:
                seen.add(key)
                unique.append(violation)

        return unique

    def _compute_verdict(
        self, layer_results: dict[str, LayerResult]
    ) -> GateVerdict:
        """Derive the overall verdict from individual layer verdicts.

        Precedence (highest to lowest):
            1. FAILED  -- any layer failed means overall failure.
            2. PARTIAL -- any layer partial (with none failed) means partial.
            3. PASSED  -- all layers passed means overall pass.
            4. SKIPPED -- all layers skipped means overall skipped.

        Args:
            layer_results: Mapping of layer name to its LayerResult.

        Returns:
            The computed GateVerdict.
        """
        if not layer_results:
            return GateVerdict.SKIPPED

        verdicts = [lr.verdict for lr in layer_results.values()]

        if any(v == GateVerdict.FAILED for v in verdicts):
            return GateVerdict.FAILED

        if any(v == GateVerdict.PARTIAL for v in verdicts):
            return GateVerdict.PARTIAL

        if all(v == GateVerdict.PASSED for v in verdicts):
            return GateVerdict.PASSED

        if all(v == GateVerdict.SKIPPED for v in verdicts):
            return GateVerdict.SKIPPED

        # Mixed PASSED / SKIPPED -- treat as partial because not every
        # layer actually ran, but nothing explicitly failed.
        return GateVerdict.PARTIAL

    def _count_blocking(self, violations: list[ScanViolation]) -> int:
        """Count violations whose severity is ``"error"``.

        Args:
            violations: List of (typically deduplicated) violations.

        Returns:
            Number of blocking violations.
        """
        return sum(1 for v in violations if v.severity == "error")
