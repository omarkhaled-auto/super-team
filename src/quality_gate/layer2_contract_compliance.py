"""Layer 2 Quality Gate -- Contract Compliance Scanner.

Evaluates contract compliance from an IntegrationReport produced by
Milestone 2's ContractComplianceVerifier.  The scanner determines a
verdict based on contract-test pass rates and emits non-blocking
warnings for low pass rates on integration, data-flow, and boundary
test categories.
"""

from __future__ import annotations

import time

from src.build3_shared.models import (
    ContractViolation,
    GateVerdict,
    IntegrationReport,
    LayerResult,
    QualityLevel,
    ScanViolation,
)


class Layer2Scanner:
    """Scan an IntegrationReport and produce a Layer 2 quality result.

    Verdict logic (based on *contract* tests only):
        - 100 % pass  -> PASSED
        - >= 70 % pass -> PARTIAL
        - < 70 % pass  -> FAILED
        - 0 total tests -> SKIPPED

    Non-contract test categories (integration / data-flow / boundary) are
    checked but are **non-blocking**: a pass rate below 70 % adds a warning
    violation without downgrading the verdict.
    """

    CONTRACT_PASS_THRESHOLD: float = 1.0   # 100 % required for PASSED
    CONTRACT_PARTIAL_THRESHOLD: float = 0.7  # 70 % for PARTIAL
    OTHER_PASS_THRESHOLD: float = 0.7        # 70 % for non-blocking tests

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, integration_report: IntegrationReport) -> LayerResult:
        """Evaluate *integration_report* and return a :class:`LayerResult`."""

        start = time.monotonic()
        violations: list[ScanViolation] = []

        # ---- Convert ContractViolations to ScanViolations ----
        for cv in integration_report.violations:
            violations.append(
                ScanViolation(
                    code=cv.code,
                    severity=cv.severity,
                    category="layer2",
                    file_path=cv.file_path,
                    message=f"{cv.message}. Suggestion: Expected: {cv.expected}, Actual: {cv.actual}",
                )
            )

        # ---- Contract-test pass rate & verdict ----
        contract_rate = self._pass_rate(
            integration_report.contract_tests_passed,
            integration_report.contract_tests_total,
        )
        verdict = self._determine_verdict(
            contract_rate, integration_report.contract_tests_total
        )

        # ---- Non-blocking test categories (warnings only) ----
        self._check_non_blocking(
            label="integration",
            passed=integration_report.integration_tests_passed,
            total=integration_report.integration_tests_total,
            violations=violations,
        )
        self._check_non_blocking(
            label="data_flow",
            passed=integration_report.data_flow_tests_passed,
            total=integration_report.data_flow_tests_total,
            violations=violations,
        )
        self._check_non_blocking(
            label="boundary",
            passed=integration_report.boundary_tests_passed,
            total=integration_report.boundary_tests_total,
            violations=violations,
        )

        duration = time.monotonic() - start

        # ---- Aggregate totals across all test categories ----
        total_checks = (
            integration_report.contract_tests_total
            + integration_report.integration_tests_total
            + integration_report.data_flow_tests_total
            + integration_report.boundary_tests_total
        )
        passed_checks = (
            integration_report.contract_tests_passed
            + integration_report.integration_tests_passed
            + integration_report.data_flow_tests_passed
            + integration_report.boundary_tests_passed
        )

        return LayerResult(
            layer=QualityLevel.LAYER2_CONTRACT,
            verdict=verdict,
            violations=violations,
            total_checks=total_checks,
            passed_checks=passed_checks,
            duration_seconds=duration,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pass_rate(passed: int, total: int) -> float:
        """Return the pass rate as a float in [0.0, 1.0].

        Returns 0.0 when *total* is zero to avoid division-by-zero.
        """
        if total == 0:
            return 0.0
        return passed / total

    def _determine_verdict(
        self, contract_rate: float, contract_total: int
    ) -> GateVerdict:
        """Map a contract-test pass rate to a :class:`GateVerdict`.

        When there are no contract tests at all the verdict is SKIPPED.
        """
        if contract_total == 0:
            return GateVerdict.SKIPPED
        if contract_rate >= self.CONTRACT_PASS_THRESHOLD:
            return GateVerdict.PASSED
        if contract_rate >= self.CONTRACT_PARTIAL_THRESHOLD:
            return GateVerdict.PARTIAL
        return GateVerdict.FAILED

    def _check_non_blocking(
        self,
        label: str,
        passed: int,
        total: int,
        violations: list[ScanViolation],
    ) -> None:
        """Append a warning violation when a non-blocking category is below threshold.

        Categories with zero total tests are silently skipped.
        """
        if total == 0:
            return

        rate = self._pass_rate(passed, total)
        if rate < self.OTHER_PASS_THRESHOLD:
            pct = rate * 100
            violations.append(
                ScanViolation(
                    code=f"L2-LOW-{label.upper()}",
                    severity="warning",
                    category="layer2",
                    file_path="",
                    line=0,
                    message=(
                        f"{label} tests below threshold: "
                        f"{passed}/{total} ({pct:.1f}%) passed, "
                        f"threshold is {self.OTHER_PASS_THRESHOLD * 100:.0f}%. "
                        f"Suggestion: Improve {label} test coverage to at least "
                        f"{self.OTHER_PASS_THRESHOLD * 100:.0f}% pass rate."
                    ),
                )
            )
