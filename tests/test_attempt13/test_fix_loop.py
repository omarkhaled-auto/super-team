"""Tests for fix loop improvements (Fixes 10, 11, 12, 25).

Tests verify that:
- Empty/unknown service violations are skipped (Fix 10)
- Docker failures are classified as unfixable (Fix 11)
- Repeated violation signatures are detected (Fix 12)
- Unfixable violations are filtered before processing (Fix 25)
"""

from __future__ import annotations

from typing import Any

import pytest

from src.super_orchestrator.pipeline import (
    _get_violation_signature,
    _is_fixable_violation,
    _has_fixable_violations,
)


class TestIsFixableViolation:
    """Test _is_fixable_violation classification."""

    def test_empty_service_skipped(self):
        """Violations with empty service name are not fixable."""
        v = {"code": "L1-FAIL", "service": "", "message": "Docker failed"}
        assert _is_fixable_violation(v) is False

    def test_unknown_service_skipped(self):
        """Violations with 'unknown' service are not fixable."""
        v = {"code": "CODE-001", "service": "unknown", "message": "Missing test"}
        assert _is_fixable_violation(v) is False

    def test_valid_service_is_fixable(self):
        """Violations with a real service name are fixable."""
        v = {"code": "CODE-001", "service": "auth-service", "message": "Missing test"}
        assert _is_fixable_violation(v) is True

    def test_docker_dockerfile_failure_unfixable(self):
        """Docker 'failed to read dockerfile' classified as unfixable."""
        v = {
            "code": "L1-FAIL",
            "service": "frontend",
            "message": "target frontend: failed to solve: failed to read dockerfile",
        }
        assert _is_fixable_violation(v) is False

    def test_npm_build_failure_unfixable(self):
        """npm run build failure classified as unfixable."""
        v = {
            "code": "L1-FAIL",
            "service": "accounts",
            "message": "npm run build failed with exit code 1",
        }
        assert _is_fixable_violation(v) is False

    def test_docker_compose_no_services_unfixable(self):
        """Docker compose 'no running services' classified as unfixable."""
        v = {
            "code": "L1-FAIL",
            "service": "pipeline",
            "message": "docker compose up returned no running services",
        }
        assert _is_fixable_violation(v) is False

    def test_docker_build_failure_unfixable(self):
        """Docker build failure classified as unfixable."""
        v = {
            "code": "L1-FAIL",
            "service": "auth-service",
            "message": "docker build returned non-zero exit code",
        }
        assert _is_fixable_violation(v) is False

    def test_docker_compose_failure_unfixable(self):
        """Docker compose failure classified as unfixable."""
        v = {
            "code": "L1-FAIL",
            "service": "pipeline",
            "message": "docker compose up failed to start services",
        }
        assert _is_fixable_violation(v) is False

    def test_integration_prefix_unfixable(self):
        """INTEGRATION-* prefix classified as unfixable."""
        v = {
            "code": "INTEGRATION-FAIL",
            "service": "auth-service",
            "message": "Integration test failed",
        }
        assert _is_fixable_violation(v) is False

    def test_infra_prefix_unfixable(self):
        """INFRA-* prefix classified as unfixable."""
        v = {
            "code": "INFRA-DOCKER",
            "service": "auth-service",
            "message": "Infrastructure failure",
        }
        assert _is_fixable_violation(v) is False

    def test_docker_prefix_unfixable(self):
        """DOCKER-* prefix classified as unfixable."""
        v = {
            "code": "DOCKER-BUILD",
            "service": "auth-service",
            "message": "Docker build failed",
        }
        assert _is_fixable_violation(v) is False

    def test_build_nosrc_unfixable(self):
        """BUILD-NOSRC prefix classified as unfixable."""
        v = {
            "code": "BUILD-NOSRC",
            "service": "frontend",
            "message": "No source files produced",
        }
        assert _is_fixable_violation(v) is False

    def test_l2_integration_fail_unfixable(self):
        """L2-INTEGRATION-FAIL prefix classified as unfixable."""
        v = {
            "code": "L2-INTEGRATION-FAIL",
            "service": "pipeline-level",
            "message": "Docker integration failed",
        }
        assert _is_fixable_violation(v) is False

    def test_normal_code_violation_fixable(self):
        """Normal code violation with valid service is fixable."""
        v = {
            "code": "L1-LOW-CONVERGENCE",
            "service": "auth-service",
            "message": "Convergence ratio 0.75 below threshold",
        }
        assert _is_fixable_violation(v) is True


class TestGetViolationSignature:
    """Test _get_violation_signature for repeat detection."""

    def test_same_violations_same_signature(self):
        """Identical violation sets produce identical signatures."""
        vs = [{"code": "A", "service": "x", "message": "err"}]
        sig1 = _get_violation_signature(vs)
        sig2 = _get_violation_signature(vs)
        assert sig1 == sig2

    def test_different_violations_different_signature(self):
        """Different violations produce different signatures."""
        vs1 = [{"code": "A", "service": "x", "message": "err1"}]
        vs2 = [{"code": "B", "service": "y", "message": "err2"}]
        assert _get_violation_signature(vs1) != _get_violation_signature(vs2)

    def test_order_independent(self):
        """Signature is order-independent (frozenset)."""
        vs1 = [
            {"code": "A", "service": "x", "message": "err1"},
            {"code": "B", "service": "y", "message": "err2"},
        ]
        vs2 = [
            {"code": "B", "service": "y", "message": "err2"},
            {"code": "A", "service": "x", "message": "err1"},
        ]
        assert _get_violation_signature(vs1) == _get_violation_signature(vs2)

    def test_message_truncated_at_50_chars(self):
        """Long messages are truncated at 50 chars for comparison."""
        long_msg = "x" * 100
        vs = [{"code": "A", "service": "x", "message": long_msg}]
        sig = _get_violation_signature(vs)
        # The signature element should have the first 50 chars
        for item in sig:
            assert len(item[2]) <= 50

    def test_empty_violations(self):
        """Empty violation list produces empty signature."""
        assert _get_violation_signature([]) == frozenset()


class TestHasFixableViolations:
    """Test _has_fixable_violations gate function."""

    def test_fixable_violations_present(self):
        """Returns True when fixable violations exist."""
        results = {
            "layers": {
                "layer1": {
                    "violations": [
                        {"code": "CODE-001", "service": "auth-service", "message": "Missing test"}
                    ]
                }
            }
        }
        assert _has_fixable_violations(results) is True

    def test_only_unfixable_violations(self):
        """Returns False when only unfixable violations remain."""
        results = {
            "layers": {
                "layer1": {
                    "violations": [
                        {"code": "INTEGRATION-FAIL", "service": "auth", "message": "Docker failed"},
                        {"code": "DOCKER-BUILD", "service": "frontend", "message": "Build failed"},
                    ]
                }
            }
        }
        assert _has_fixable_violations(results) is False

    def test_no_violations(self):
        """Returns False when no violations at all."""
        results = {
            "layers": {
                "layer1": {"violations": []}
            }
        }
        assert _has_fixable_violations(results) is False

    def test_fallback_to_blocking_count(self):
        """Falls back to blocking_violations count when layers have no violation details."""
        results = {
            "layers": {},
            "blocking_violations": 5,
        }
        assert _has_fixable_violations(results) is True

    def test_mixed_fixable_and_unfixable(self):
        """Returns True when at least one fixable violation exists among unfixable ones."""
        results = {
            "layers": {
                "layer1": {
                    "violations": [
                        {"code": "DOCKER-BUILD", "service": "frontend", "message": "Build failed"},
                        {"code": "CODE-001", "service": "auth-service", "message": "Missing test"},
                    ]
                }
            }
        }
        assert _has_fixable_violations(results) is True
