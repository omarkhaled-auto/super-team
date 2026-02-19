"""Integration report generator for Milestone 2 -- Contract Compliance Verification."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from src.build3_shared.models import ContractViolation, IntegrationReport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_BADGES: dict[str, str] = {
    "critical": "[CRITICAL]",
    "error": "[ERROR]",
    "warning": "[WARNING]",
    "info": "[INFO]",
}


def _severity_badge(severity: str) -> str:
    """Return a human-readable severity badge string."""
    return _SEVERITY_BADGES.get(severity.lower(), f"[{severity.upper()}]")


# ---------------------------------------------------------------------------
# Internal section builders
# ---------------------------------------------------------------------------


def _summary_section(report: IntegrationReport) -> str:
    """Build the summary section of the report."""
    total_violations = len(report.violations)

    lines: list[str] = [
        "# Integration Report",
        "",
        f"**Overall Health:** {report.overall_health}",
        "",
        f"- **Services deployed:** {report.services_deployed}",
        f"- **Services healthy:** {report.services_healthy}",
        "",
        "### Test Results",
        "",
        "| Category | Passed | Total |",
        "|---|---|---|",
        f"| Contract tests | {report.contract_tests_passed} | {report.contract_tests_total} |",
        f"| Integration tests | {report.integration_tests_passed} | {report.integration_tests_total} |",
        f"| Data flow tests | {report.data_flow_tests_passed} | {report.data_flow_tests_total} |",
        f"| Boundary tests | {report.boundary_tests_passed} | {report.boundary_tests_total} |",
        "",
        f"**Total violations:** {total_violations}",
        "",
    ]
    return "\n".join(lines)


def _per_service_section(report: IntegrationReport) -> str:
    """Build the per-service results section."""
    lines: list[str] = [
        "## Per-Service Results",
        "",
    ]

    if report.services_deployed == 0:
        lines.append("No services were deployed.")
        lines.append("")
    else:
        lines.append(
            f"- **Deployed:** {report.services_deployed} service(s)"
        )
        lines.append(
            f"- **Healthy:** {report.services_healthy} / {report.services_deployed}"
        )
        lines.append("")

    return "\n".join(lines)


def _violations_section(report: IntegrationReport) -> str:
    """Build the violations section."""
    lines: list[str] = [
        "## Violations",
        "",
    ]

    if not report.violations:
        lines.append("No violations found.")
        lines.append("")
        return "\n".join(lines)

    for idx, violation in enumerate(report.violations, start=1):
        badge = _severity_badge(violation.severity)
        lines.append(f"### Violation {idx} {badge}")
        lines.append("")
        lines.append(f"- **Code:** {violation.code}")
        lines.append(f"- **Service:** {violation.service}")
        lines.append(f"- **Endpoint:** {violation.endpoint}")
        lines.append(f"- **Message:** {violation.message}")

        if violation.expected:
            lines.append(f"- **Expected:** {violation.expected}")
        if violation.actual:
            lines.append(f"- **Actual:** {violation.actual}")

        lines.append("")

    return "\n".join(lines)


def _recommendations_section(report: IntegrationReport) -> str:
    """Build the recommendations section based on test results."""
    lines: list[str] = [
        "## Recommendations",
        "",
    ]

    recommendations: list[str] = []

    # Overall health check
    if report.overall_health != "passed":
        recommendations.append(
            "- Fix all contract violations before proceeding to deployment."
        )

    # Contract test failures
    contract_failed = report.contract_tests_total - report.contract_tests_passed
    if contract_failed > 0:
        recommendations.append(
            f"- {contract_failed} contract test(s) failed. "
            "Review and fix API schema mismatches."
        )

    # Boundary test failures
    boundary_failed = report.boundary_tests_total - report.boundary_tests_passed
    if boundary_failed > 0:
        recommendations.append(
            f"- {boundary_failed} boundary test(s) failed. "
            "Review and fix boundary condition handling."
        )

    if not recommendations:
        lines.append("All contract compliance checks passed.")
        lines.append("")
    else:
        lines.extend(recommendations)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_integration_report(report: IntegrationReport) -> str:
    """Generate a markdown integration report from an IntegrationReport dataclass.

    This is a pure function: it performs no I/O and has no side effects.
    It returns a single markdown-formatted string suitable for writing
    to a file or displaying in a terminal.

    Args:
        report: The ``IntegrationReport`` dataclass containing all test
            results, deployment stats, and violations.

    Returns:
        A complete markdown report string.
    """
    logger.debug(
        "Generating integration report (violations=%d, health=%s)",
        len(report.violations),
        report.overall_health,
    )

    sections = [
        _summary_section(report),
        _per_service_section(report),
        _violations_section(report),
        _recommendations_section(report),
    ]

    return "\n".join(sections)
