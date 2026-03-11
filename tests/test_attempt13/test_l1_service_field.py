"""Tests for Layer 1 per-service violation service field (Fix 10).

Verifies that L1 violations have the service field properly set
to the builder's service_id, not empty or 'unknown'.
"""

from __future__ import annotations

import pytest

from src.build3_shared.models import (
    BuilderResult,
    GateVerdict,
    QualityLevel,
)
from src.quality_gate.layer1_per_service import Layer1Scanner


class TestL1ViolationServiceField:
    """Test that L1 violations have service field set."""

    def test_failed_builder_violation_has_service(self):
        """Failed builder produces violation with service = service_id."""
        results = [
            BuilderResult(
                system_id="sys-1",
                service_id="auth-service",
                success=False,
                error="Tests failed",
                convergence_ratio=0.5,
            ),
        ]
        scanner = Layer1Scanner()
        result = scanner.evaluate(results)

        fail_violations = [v for v in result.violations if v.code == "L1-FAIL"]
        assert len(fail_violations) == 1
        assert fail_violations[0].service == "auth-service"

    def test_multiple_failures_each_has_service(self):
        """Each failed builder gets its own violation with correct service_id."""
        results = [
            BuilderResult(
                system_id="sys-1",
                service_id="auth-service",
                success=False,
                error="Auth failed",
                convergence_ratio=0.3,
            ),
            BuilderResult(
                system_id="sys-2",
                service_id="invoicing-service",
                success=False,
                error="Invoice failed",
                convergence_ratio=0.4,
            ),
            BuilderResult(
                system_id="sys-3",
                service_id="accounts-service",
                success=True,
                convergence_ratio=0.95,
            ),
        ]
        scanner = Layer1Scanner()
        result = scanner.evaluate(results)

        fail_violations = [v for v in result.violations if v.code == "L1-FAIL"]
        services = {v.service for v in fail_violations}
        assert "auth-service" in services
        assert "invoicing-service" in services
        assert "accounts-service" not in services  # Didn't fail

    def test_convergence_violation_has_pipeline_level_service(self):
        """Convergence warning uses 'pipeline-level' as service."""
        results = [
            BuilderResult(
                system_id="sys-1",
                service_id="auth-service",
                success=True,
                convergence_ratio=0.5,
            ),
        ]
        scanner = Layer1Scanner()
        result = scanner.evaluate(results)

        conv_violations = [v for v in result.violations if v.code == "L1-CONVERGENCE"]
        assert len(conv_violations) == 1
        assert conv_violations[0].service == "pipeline-level"

    def test_no_violations_on_full_success(self):
        """All builders passing produces no L1-FAIL violations."""
        results = [
            BuilderResult(
                system_id="sys-1",
                service_id="auth-service",
                success=True,
                convergence_ratio=0.95,
            ),
            BuilderResult(
                system_id="sys-2",
                service_id="accounts-service",
                success=True,
                convergence_ratio=0.98,
            ),
        ]
        scanner = Layer1Scanner()
        result = scanner.evaluate(results)

        fail_violations = [v for v in result.violations if v.code == "L1-FAIL"]
        assert len(fail_violations) == 0
        assert result.verdict == GateVerdict.PASSED

    def test_violation_service_not_empty(self):
        """L1 violation service field is never empty string."""
        results = [
            BuilderResult(
                system_id="sys-1",
                service_id="frontend",
                success=False,
                error="No Dockerfile",
                convergence_ratio=0.0,
            ),
        ]
        scanner = Layer1Scanner()
        result = scanner.evaluate(results)

        for v in result.violations:
            assert v.service != "", f"Violation {v.code} has empty service"
            assert v.service != "unknown", f"Violation {v.code} has 'unknown' service"
