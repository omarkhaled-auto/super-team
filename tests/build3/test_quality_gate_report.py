"""Tests for generate_quality_gate_report (TEST-028).

Verifies that the Markdown report produced by ``generate_quality_gate_report``
contains the expected sections, content, and formatting for a variety of
input scenarios.

TEST-028: >= 4 test cases (7 provided).
"""

from __future__ import annotations

import pytest

from src.build3_shared.models import (
    GateVerdict,
    LayerResult,
    QualityGateReport,
    QualityLevel,
    ScanViolation,
)
from src.quality_gate.report import generate_quality_gate_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_layer(
    layer: QualityLevel,
    verdict: GateVerdict,
    total: int = 5,
    passed: int = 5,
    duration: float = 1.2,
    violations: list[ScanViolation] | None = None,
) -> LayerResult:
    """Convenience factory for building a ``LayerResult``."""
    return LayerResult(
        layer=layer,
        verdict=verdict,
        total_checks=total,
        passed_checks=passed,
        duration_seconds=duration,
        violations=violations or [],
    )


# ---------------------------------------------------------------------------
# Test: all layers PASSED, no violations
# ---------------------------------------------------------------------------


class TestAllLayersPassed:
    """Report with every layer PASSED and zero violations."""

    def test_contains_passed_verdict(self) -> None:
        report = QualityGateReport(
            overall_verdict=GateVerdict.PASSED,
            layers={
                "layer1_service": _make_layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED),
                "layer2_contract": _make_layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED),
            },
            total_violations=0,
            blocking_violations=0,
        )
        output = generate_quality_gate_report(report)

        assert "PASSED" in output

    def test_contains_summary_section(self) -> None:
        report = QualityGateReport(
            overall_verdict=GateVerdict.PASSED,
            layers={
                "layer1_service": _make_layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED),
            },
            total_violations=0,
            blocking_violations=0,
        )
        output = generate_quality_gate_report(report)

        assert "## Summary" in output
        assert "Total violations" in output
        assert "| 0 |" in output  # total violations cell

    def test_no_violations_message(self) -> None:
        report = QualityGateReport(
            overall_verdict=GateVerdict.PASSED,
            layers={
                "layer1_service": _make_layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED),
            },
            total_violations=0,
            blocking_violations=0,
        )
        output = generate_quality_gate_report(report)

        assert "No violations found." in output

    def test_recommendations_all_passed(self) -> None:
        report = QualityGateReport(
            overall_verdict=GateVerdict.PASSED,
            layers={
                "layer1_service": _make_layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED),
            },
            total_violations=0,
            blocking_violations=0,
        )
        output = generate_quality_gate_report(report)

        assert "## Recommendations" in output
        assert "All quality gate checks passed. No action required." in output


# ---------------------------------------------------------------------------
# Test: report with violations
# ---------------------------------------------------------------------------


class TestReportWithViolations:
    """Violations section must show code, severity, file, and message."""

    def test_violation_details_rendered(self) -> None:
        violation = ScanViolation(
            code="SEC-001",
            severity="error",
            category="security",
            file_path="src/auth/jwt.py",
            line=42,
            message="JWT secret is hard-coded. Suggestion: Use an environment variable instead.",
        )
        layer = _make_layer(
            QualityLevel.LAYER3_SYSTEM,
            GateVerdict.FAILED,
            total=10,
            passed=8,
            violations=[violation],
        )
        report = QualityGateReport(
            overall_verdict=GateVerdict.FAILED,
            layers={"layer3_system": layer},
            total_violations=1,
            blocking_violations=1,
        )
        output = generate_quality_gate_report(report)

        assert "`SEC-001`" in output
        assert "ERROR" in output
        assert "`src/auth/jwt.py`" in output
        assert "42" in output
        assert "JWT secret is hard-coded" in output

    def test_multiple_severities_grouped(self) -> None:
        error_v = ScanViolation(
            code="DOCKER-001",
            severity="error",
            category="docker",
            file_path="Dockerfile",
            line=1,
            message="Running as root",
        )
        warning_v = ScanViolation(
            code="LOG-002",
            severity="warning",
            category="logging",
            file_path="src/app.py",
            line=55,
            message="Missing structured logging",
        )
        info_v = ScanViolation(
            code="TRACE-003",
            severity="info",
            category="trace",
            file_path="src/handler.py",
            line=10,
            message="No trace context propagated",
        )
        layer = _make_layer(
            QualityLevel.LAYER3_SYSTEM,
            GateVerdict.FAILED,
            total=10,
            passed=7,
            violations=[error_v, warning_v, info_v],
        )
        report = QualityGateReport(
            overall_verdict=GateVerdict.FAILED,
            layers={"layer3_system": layer},
            total_violations=3,
            blocking_violations=1,
        )
        output = generate_quality_gate_report(report)

        # Each severity group has its own sub-heading.
        assert "### " in output
        assert "ERROR" in output
        assert "WARNING" in output
        assert "INFO" in output
        # All three violation codes appear.
        assert "`DOCKER-001`" in output
        assert "`LOG-002`" in output
        assert "`TRACE-003`" in output


# ---------------------------------------------------------------------------
# Test: FAILED verdict
# ---------------------------------------------------------------------------


class TestFailedVerdict:
    """Report with overall FAILED verdict must show the FAILED badge."""

    def test_contains_failed_badge(self) -> None:
        layer = _make_layer(
            "layer1_service",
            GateVerdict.FAILED,
            total=10,
            passed=3,
            violations=[
                ScanViolation(
                    code="SEC-010",
                    severity="error",
                    category="security",
                    file_path="src/main.py",
                    line=1,
                    message="Critical security flaw",
                ),
            ],
        )
        report = QualityGateReport(
            overall_verdict=GateVerdict.FAILED,
            layers={"layer1_service": layer},
            total_violations=1,
            blocking_violations=1,
        )
        output = generate_quality_gate_report(report)

        assert "FAILED" in output
        # The header section should carry the verdict badge.
        assert "**Verdict:**" in output

    def test_failed_recommendations(self) -> None:
        layer = _make_layer(
            "layer1_service",
            GateVerdict.FAILED,
            total=10,
            passed=3,
            violations=[
                ScanViolation(
                    code="SEC-010",
                    severity="error",
                    category="security",
                    file_path="src/main.py",
                    line=1,
                    message="Critical security flaw",
                ),
            ],
        )
        report = QualityGateReport(
            overall_verdict=GateVerdict.FAILED,
            layers={"layer1_service": layer},
            total_violations=1,
            blocking_violations=1,
        )
        output = generate_quality_gate_report(report)

        # A FAILED verdict triggers a critical recommendation.
        assert "Resolve all blocking violations before merging" in output
        assert "blocking violation(s)" in output


# ---------------------------------------------------------------------------
# Test: no layers executed
# ---------------------------------------------------------------------------


class TestNoLayers:
    """Report with an empty layers dict should gracefully indicate no layers."""

    def test_no_layers_message(self) -> None:
        report = QualityGateReport(
            overall_verdict=GateVerdict.SKIPPED,
            layers={},
            total_violations=0,
            blocking_violations=0,
        )
        output = generate_quality_gate_report(report)

        assert "No layers executed." in output

    def test_no_layers_still_has_all_sections(self) -> None:
        report = QualityGateReport(
            overall_verdict=GateVerdict.SKIPPED,
            layers={},
            total_violations=0,
            blocking_violations=0,
        )
        output = generate_quality_gate_report(report)

        assert "# Quality Gate Report" in output
        assert "## Summary" in output
        assert "## Per-Layer Results" in output
        assert "## Violations" in output
        assert "## Recommendations" in output


# ---------------------------------------------------------------------------
# Test: mixed verdicts across layers
# ---------------------------------------------------------------------------


class TestMixedVerdicts:
    """Report with layers having different verdicts renders each correctly."""

    def test_per_layer_table_mixed_icons(self) -> None:
        layers = {
            "layer1_service": _make_layer(
                "layer1_service", GateVerdict.PASSED, total=10, passed=10,
            ),
            "layer2_contract": _make_layer(
                "layer2_contract", GateVerdict.FAILED, total=8, passed=5,
                violations=[
                    ScanViolation(
                        code="SEC-005",
                        severity="error",
                        category="security",
                        file_path="src/api.py",
                        line=99,
                        message="Missing auth header validation",
                    ),
                ],
            ),
            "layer3_system": _make_layer(
                "layer3_system", GateVerdict.PARTIAL, total=6, passed=4,
            ),
            "layer4_adversarial": _make_layer(
                QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.SKIPPED, total=0, passed=0,
            ),
        }
        report = QualityGateReport(
            overall_verdict=GateVerdict.PARTIAL,
            layers=layers,
            total_violations=1,
            blocking_violations=1,
        )
        output = generate_quality_gate_report(report)

        # The per-layer table should contain a row for each layer.
        assert "PASSED" in output
        assert "FAILED" in output
        assert "PARTIAL" in output
        assert "SKIPPED" in output

        # Human-readable layer names should be used.
        assert "Layer 1" in output
        assert "Layer 2" in output
        assert "Layer 3" in output
        assert "Layer 4" in output

    def test_checks_ratio_displayed(self) -> None:
        layers = {
            "layer1_service": _make_layer(
                "layer1_service", GateVerdict.PASSED, total=10, passed=10,
            ),
            "layer2_contract": _make_layer(
                "layer2_contract", GateVerdict.FAILED, total=8, passed=5,
            ),
        }
        report = QualityGateReport(
            overall_verdict=GateVerdict.FAILED,
            layers=layers,
            total_violations=0,
            blocking_violations=0,
        )
        output = generate_quality_gate_report(report)

        # The table should show passed/total checks for each layer.
        assert "10/10" in output
        assert "5/8" in output

    def test_layers_executed_count(self) -> None:
        layers = {
            "layer1_service": _make_layer(
                "layer1_service", GateVerdict.PASSED,
            ),
            "layer2_contract": _make_layer(
                "layer2_contract", GateVerdict.PASSED,
            ),
            "layer3_system": _make_layer(
                "layer3_system", GateVerdict.PARTIAL,
            ),
        }
        report = QualityGateReport(
            overall_verdict=GateVerdict.PARTIAL,
            layers=layers,
            total_violations=0,
            blocking_violations=0,
        )
        output = generate_quality_gate_report(report)

        # The summary table should reflect the number of layers.
        assert "Layers executed" in output
        assert "| 3 |" in output
