"""Tests for Layer 2 quality gate integration health (Fix 13).

Verifies that Layer2Scanner returns FAILED (not SKIPPED) when
integration has failed, and creates L2-INTEGRATION-FAIL violations.
"""

from __future__ import annotations

import pytest

from src.build3_shared.models import (
    GateVerdict,
    IntegrationReport,
    QualityLevel,
)
from src.quality_gate.layer2_contract_compliance import Layer2Scanner


class TestLayer2IntegrationFailed:
    """Test L2 quality gate behavior on integration failure."""

    def test_failed_integration_returns_failed(self):
        """Integration failed -> L2 returns FAILED not SKIPPED."""
        report = IntegrationReport(
            overall_health="failed",
            services_deployed=5,
            services_healthy=2,
        )
        scanner = Layer2Scanner()
        result = scanner.evaluate(report)

        assert result.verdict == GateVerdict.FAILED
        assert result.layer == QualityLevel.LAYER2_CONTRACT

    def test_failed_integration_creates_violation(self):
        """Integration failed -> L2-INTEGRATION-FAIL violation created."""
        report = IntegrationReport(
            overall_health="failed",
            services_deployed=5,
            services_healthy=2,
        )
        scanner = Layer2Scanner()
        result = scanner.evaluate(report)

        assert len(result.violations) >= 1
        codes = [v.code for v in result.violations]
        assert "L2-INTEGRATION-FAIL" in codes

    def test_error_integration_returns_failed(self):
        """Integration error -> L2 returns FAILED."""
        report = IntegrationReport(
            overall_health="error",
            services_deployed=0,
            services_healthy=0,
        )
        scanner = Layer2Scanner()
        result = scanner.evaluate(report)

        assert result.verdict == GateVerdict.FAILED

    def test_passed_integration_not_failed(self):
        """Healthy integration -> L2 does not return FAILED."""
        report = IntegrationReport(
            overall_health="passed",
            services_deployed=5,
            services_healthy=5,
            contract_tests_passed=10,
            contract_tests_total=10,
        )
        scanner = Layer2Scanner()
        result = scanner.evaluate(report)

        assert result.verdict == GateVerdict.PASSED

    def test_no_tests_returns_skipped(self):
        """No contract tests at all -> SKIPPED verdict."""
        report = IntegrationReport(
            overall_health="passed",
            services_deployed=5,
            services_healthy=5,
            contract_tests_passed=0,
            contract_tests_total=0,
        )
        scanner = Layer2Scanner()
        result = scanner.evaluate(report)

        assert result.verdict == GateVerdict.SKIPPED

    def test_partial_pass_rate(self):
        """Contract test pass rate between 70-100% -> PARTIAL."""
        report = IntegrationReport(
            overall_health="passed",
            services_deployed=5,
            services_healthy=5,
            contract_tests_passed=8,
            contract_tests_total=10,
        )
        scanner = Layer2Scanner()
        result = scanner.evaluate(report)

        assert result.verdict == GateVerdict.PARTIAL

    def test_low_pass_rate_fails(self):
        """Contract test pass rate below 70% -> FAILED."""
        report = IntegrationReport(
            overall_health="passed",
            services_deployed=5,
            services_healthy=5,
            contract_tests_passed=5,
            contract_tests_total=10,
        )
        scanner = Layer2Scanner()
        result = scanner.evaluate(report)

        assert result.verdict == GateVerdict.FAILED

    def test_violation_contains_service_info(self):
        """L2-INTEGRATION-FAIL violation includes deployment context."""
        report = IntegrationReport(
            overall_health="failed",
            services_deployed=5,
            services_healthy=2,
        )
        scanner = Layer2Scanner()
        result = scanner.evaluate(report)

        fail_violation = next(v for v in result.violations if v.code == "L2-INTEGRATION-FAIL")
        assert "5" in fail_violation.message  # services_deployed
        assert "2" in fail_violation.message  # services_healthy

    def test_failed_returns_zero_passed(self):
        """Integration failed -> passed_checks is 0."""
        report = IntegrationReport(
            overall_health="failed",
            services_deployed=5,
            services_healthy=2,
        )
        scanner = Layer2Scanner()
        result = scanner.evaluate(report)

        assert result.passed_checks == 0
        assert result.total_checks == 1
