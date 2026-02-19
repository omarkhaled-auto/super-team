"""Tests for generate_integration_report.

TEST-004: >= 4 test cases (8 provided).
"""

from __future__ import annotations

from src.build3_shared.models import ContractViolation, IntegrationReport
from src.integrator.report import generate_integration_report


class TestReportSections:
    """Verify the report contains the expected top-level sections."""

    def test_report_has_summary_section(self) -> None:
        report = IntegrationReport(overall_health="passed")
        output = generate_integration_report(report)

        assert "# Integration Report" in output
        assert "Overall Health" in output

    def test_report_has_per_service_section(self) -> None:
        report = IntegrationReport(services_deployed=2, services_healthy=2)
        output = generate_integration_report(report)

        assert "## Per-Service Results" in output

    def test_report_has_violations_section(self) -> None:
        report = IntegrationReport()
        output = generate_integration_report(report)

        assert "## Violations" in output

    def test_report_has_recommendations_section(self) -> None:
        report = IntegrationReport()
        output = generate_integration_report(report)

        assert "## Recommendations" in output


class TestReportContent:
    """Verify report content varies correctly based on input data."""

    def test_empty_report_no_violations(self) -> None:
        report = IntegrationReport()
        output = generate_integration_report(report)

        assert "No violations found." in output

    def test_report_with_violations(self) -> None:
        violation = ContractViolation(
            code="SCHEMA-001",
            severity="critical",
            service="auth-service",
            endpoint="/api/login",
            message="Response body missing field 'token'",
            expected="string",
            actual="null",
        )
        report = IntegrationReport(
            services_deployed=2,
            services_healthy=1,
            contract_tests_passed=8,
            contract_tests_total=10,
            violations=[violation],
            overall_health="failed",
        )
        output = generate_integration_report(report)

        assert "SCHEMA-001" in output
        assert "[CRITICAL]" in output
        assert "auth-service" in output
        assert "/api/login" in output
        assert "Response body missing field 'token'" in output
        assert "Expected:" in output
        assert "Actual:" in output
        # The summary should reflect the violation count
        assert "Total violations:** 1" in output

    def test_report_failed_contract_tests(self) -> None:
        report = IntegrationReport(
            contract_tests_passed=7,
            contract_tests_total=10,
            overall_health="failed",
        )
        output = generate_integration_report(report)

        assert "schema mismatches" in output.lower() or "API schema mismatches" in output

    def test_report_all_passed(self) -> None:
        report = IntegrationReport(
            services_deployed=3,
            services_healthy=3,
            contract_tests_passed=10,
            contract_tests_total=10,
            integration_tests_passed=5,
            integration_tests_total=5,
            data_flow_tests_passed=3,
            data_flow_tests_total=3,
            boundary_tests_passed=4,
            boundary_tests_total=4,
            violations=[],
            overall_health="passed",
        )
        output = generate_integration_report(report)

        assert "All contract compliance checks passed." in output
