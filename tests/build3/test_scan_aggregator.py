"""Tests for ScanAggregator (TEST-027).

Covers verdict computation, violation deduplication, blocking counts,
fix-attempt pass-through, and edge cases like empty layer results.
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
from src.quality_gate.scan_aggregator import ScanAggregator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_violation(
    code: str = "V001",
    severity: str = "error",
    category: str = "style",
    file_path: str = "src/app.py",
    line: int = 10,
    message: str = "test violation",
) -> ScanViolation:
    """Create a ScanViolation with sensible defaults."""
    return ScanViolation(
        code=code,
        severity=severity,
        category=category,
        file_path=file_path,
        line=line,
        message=message,
    )


def _make_layer(
    layer: QualityLevel = QualityLevel.LAYER1_SERVICE,
    verdict: GateVerdict = GateVerdict.PASSED,
    violations: list[ScanViolation] | None = None,
    total_checks: int = 5,
    passed_checks: int = 5,
    duration_seconds: float = 1.0,
) -> LayerResult:
    """Create a LayerResult with sensible defaults."""
    return LayerResult(
        layer=layer,
        verdict=verdict,
        violations=violations if violations is not None else [],
        total_checks=total_checks,
        passed_checks=passed_checks,
        duration_seconds=duration_seconds,
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def aggregator():
    return ScanAggregator()


# ---------------------------------------------------------------------------
# Verdict computation
# ---------------------------------------------------------------------------

class TestComputeVerdict:
    """Tests for the overall verdict logic."""

    def test_all_layers_passed_gives_passed(self, aggregator: ScanAggregator) -> None:
        """When every layer reports PASSED the overall verdict is PASSED."""
        layer_results = {
            "layer1": _make_layer(verdict=GateVerdict.PASSED),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, verdict=GateVerdict.PASSED),
            "layer3": _make_layer(layer=QualityLevel.LAYER3_SYSTEM, verdict=GateVerdict.PASSED),
        }
        report = aggregator.aggregate(layer_results)

        assert report.overall_verdict == GateVerdict.PASSED

    def test_one_layer_failed_gives_failed(self, aggregator: ScanAggregator) -> None:
        """A single FAILED layer forces the overall verdict to FAILED."""
        layer_results = {
            "layer1": _make_layer(verdict=GateVerdict.PASSED),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, verdict=GateVerdict.FAILED),
            "layer3": _make_layer(layer=QualityLevel.LAYER3_SYSTEM, verdict=GateVerdict.PASSED),
        }
        report = aggregator.aggregate(layer_results)

        assert report.overall_verdict == GateVerdict.FAILED

    def test_multiple_failed_layers_still_failed(
        self, aggregator: ScanAggregator
    ) -> None:
        """Multiple FAILED layers still produce a single overall FAILED."""
        layer_results = {
            "layer1": _make_layer(verdict=GateVerdict.FAILED),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, verdict=GateVerdict.FAILED),
        }
        report = aggregator.aggregate(layer_results)

        assert report.overall_verdict == GateVerdict.FAILED

    def test_partial_without_failed_gives_partial(
        self, aggregator: ScanAggregator
    ) -> None:
        """A PARTIAL layer with no FAILED layers yields overall PARTIAL."""
        layer_results = {
            "layer1": _make_layer(verdict=GateVerdict.PASSED),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, verdict=GateVerdict.PARTIAL),
        }
        report = aggregator.aggregate(layer_results)

        assert report.overall_verdict == GateVerdict.PARTIAL

    def test_partial_overridden_by_failed(
        self, aggregator: ScanAggregator
    ) -> None:
        """FAILED takes precedence over PARTIAL."""
        layer_results = {
            "layer1": _make_layer(verdict=GateVerdict.PARTIAL),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, verdict=GateVerdict.FAILED),
        }
        report = aggregator.aggregate(layer_results)

        assert report.overall_verdict == GateVerdict.FAILED

    def test_all_layers_skipped_gives_skipped(
        self, aggregator: ScanAggregator
    ) -> None:
        """When every layer is SKIPPED the overall verdict is SKIPPED."""
        layer_results = {
            "layer1": _make_layer(verdict=GateVerdict.SKIPPED),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, verdict=GateVerdict.SKIPPED),
        }
        report = aggregator.aggregate(layer_results)

        assert report.overall_verdict == GateVerdict.SKIPPED

    def test_empty_layer_results_gives_skipped(
        self, aggregator: ScanAggregator
    ) -> None:
        """An empty dict of layer results is treated as SKIPPED."""
        report = aggregator.aggregate({})

        assert report.overall_verdict == GateVerdict.SKIPPED

    def test_mixed_passed_and_skipped_gives_partial(
        self, aggregator: ScanAggregator
    ) -> None:
        """A mix of PASSED and SKIPPED (no FAILED/PARTIAL) yields PARTIAL.

        Not every layer ran, so the gate cannot confidently report PASSED.
        """
        layer_results = {
            "layer1": _make_layer(verdict=GateVerdict.PASSED),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, verdict=GateVerdict.SKIPPED),
        }
        report = aggregator.aggregate(layer_results)

        assert report.overall_verdict == GateVerdict.PARTIAL


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    """Tests for violation deduplication."""

    def test_duplicate_violations_removed(
        self, aggregator: ScanAggregator
    ) -> None:
        """Violations sharing (code, file_path, line) are deduplicated."""
        v1 = _make_violation(code="E001", file_path="a.py", line=1)
        v2 = _make_violation(code="E001", file_path="a.py", line=1)  # duplicate
        v3 = _make_violation(code="E002", file_path="a.py", line=1)  # different code

        layer_results = {
            "layer1": _make_layer(violations=[v1, v3]),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, violations=[v2]),
        }
        report = aggregator.aggregate(layer_results)

        assert report.total_violations == 2

    def test_same_code_different_file_not_deduplicated(
        self, aggregator: ScanAggregator
    ) -> None:
        """Same code on different files are distinct violations."""
        v1 = _make_violation(code="E001", file_path="a.py", line=1)
        v2 = _make_violation(code="E001", file_path="b.py", line=1)

        layer_results = {
            "layer1": _make_layer(violations=[v1, v2]),
        }
        report = aggregator.aggregate(layer_results)

        assert report.total_violations == 2

    def test_same_code_same_file_different_line_not_deduplicated(
        self, aggregator: ScanAggregator
    ) -> None:
        """Same code on the same file but different lines are distinct."""
        v1 = _make_violation(code="E001", file_path="a.py", line=1)
        v2 = _make_violation(code="E001", file_path="a.py", line=2)

        layer_results = {
            "layer1": _make_layer(violations=[v1, v2]),
        }
        report = aggregator.aggregate(layer_results)

        assert report.total_violations == 2

    def test_dedup_preserves_first_occurrence(
        self, aggregator: ScanAggregator
    ) -> None:
        """The first violation of a duplicate set is the one kept."""
        v_first = _make_violation(
            code="E001", file_path="a.py", line=1, message="first"
        )
        v_second = _make_violation(
            code="E001", file_path="a.py", line=1, message="second"
        )

        # Call _deduplicate directly to inspect ordering.
        result = aggregator._deduplicate([v_first, v_second])

        assert len(result) == 1
        assert result[0].message == "first"

    def test_no_violations_dedup_returns_empty(
        self, aggregator: ScanAggregator
    ) -> None:
        """Deduplication of an empty list returns an empty list."""
        result = aggregator._deduplicate([])

        assert result == []


# ---------------------------------------------------------------------------
# Blocking count
# ---------------------------------------------------------------------------

class TestBlockingCount:
    """Tests for blocking violation counting."""

    def test_only_error_severity_counted_as_blocking(
        self, aggregator: ScanAggregator
    ) -> None:
        """Only severity=='error' violations count as blocking."""
        violations = [
            _make_violation(code="E001", severity="error", file_path="a.py", line=1),
            _make_violation(code="W001", severity="warning", file_path="b.py", line=2),
            _make_violation(code="I001", severity="info", file_path="c.py", line=3),
            _make_violation(code="E002", severity="error", file_path="d.py", line=4),
        ]

        layer_results = {
            "layer1": _make_layer(violations=violations),
        }
        report = aggregator.aggregate(layer_results)

        assert report.blocking_violations == 2

    def test_no_error_violations_gives_zero_blocking(
        self, aggregator: ScanAggregator
    ) -> None:
        """When no violations have severity 'error', blocking count is zero."""
        violations = [
            _make_violation(code="W001", severity="warning", file_path="a.py", line=1),
            _make_violation(code="I001", severity="info", file_path="b.py", line=2),
        ]

        layer_results = {
            "layer1": _make_layer(violations=violations),
        }
        report = aggregator.aggregate(layer_results)

        assert report.blocking_violations == 0

    def test_blocking_count_after_dedup(
        self, aggregator: ScanAggregator
    ) -> None:
        """Blocking count is computed on the deduplicated violation set."""
        dup = _make_violation(code="E001", severity="error", file_path="a.py", line=1)

        layer_results = {
            "layer1": _make_layer(violations=[dup]),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, violations=[dup]),
        }
        report = aggregator.aggregate(layer_results)

        # The same violation appears in both layers but should be counted once.
        assert report.total_violations == 1
        assert report.blocking_violations == 1


# ---------------------------------------------------------------------------
# Fix attempts pass-through
# ---------------------------------------------------------------------------

class TestFixAttempts:
    """Tests that fix_attempts and max_fix_attempts are forwarded."""

    def test_fix_attempts_defaults(self, aggregator: ScanAggregator) -> None:
        """Default values are fix_attempts=0 and max_fix_attempts=3."""
        report = aggregator.aggregate({})

        assert report.fix_attempts == 0
        assert report.max_fix_attempts == 3

    def test_fix_attempts_passed_through(
        self, aggregator: ScanAggregator
    ) -> None:
        """Custom fix_attempts and max_fix_attempts appear in the report."""
        layer_results = {
            "layer1": _make_layer(verdict=GateVerdict.PASSED),
        }
        report = aggregator.aggregate(
            layer_results, fix_attempts=2, max_fix_attempts=5
        )

        assert report.fix_attempts == 2
        assert report.max_fix_attempts == 5

    def test_fix_attempts_zero_and_max_zero(
        self, aggregator: ScanAggregator
    ) -> None:
        """Edge case: both fix_attempts and max_fix_attempts can be zero."""
        report = aggregator.aggregate({}, fix_attempts=0, max_fix_attempts=0)

        assert report.fix_attempts == 0
        assert report.max_fix_attempts == 0


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    """Tests for the shape and contents of the returned report."""

    def test_report_is_quality_gate_report(
        self, aggregator: ScanAggregator
    ) -> None:
        """aggregate() returns a QualityGateReport instance."""
        report = aggregator.aggregate({})

        assert isinstance(report, QualityGateReport)

    def test_layers_dict_preserved_in_report(
        self, aggregator: ScanAggregator
    ) -> None:
        """The layers dict in the report matches the input layer results."""
        lr1 = _make_layer(layer=QualityLevel.LAYER1_SERVICE, verdict=GateVerdict.PASSED)
        lr2 = _make_layer(layer=QualityLevel.LAYER2_CONTRACT, verdict=GateVerdict.PARTIAL)

        layer_results = {"layer1": lr1, "layer2": lr2}
        report = aggregator.aggregate(layer_results)

        assert set(report.layers.keys()) == {"layer1", "layer2"}
        assert report.layers["layer1"] is lr1
        assert report.layers["layer2"] is lr2

    def test_total_violations_counts_unique_across_layers(
        self, aggregator: ScanAggregator
    ) -> None:
        """total_violations reflects the deduplicated count across layers."""
        v1 = _make_violation(code="E001", file_path="a.py", line=1)
        v2 = _make_violation(code="E002", file_path="a.py", line=2)
        v3 = _make_violation(code="E001", file_path="a.py", line=1)  # dup of v1

        layer_results = {
            "layer1": _make_layer(violations=[v1, v2]),
            "layer2": _make_layer(layer=QualityLevel.LAYER2_CONTRACT, violations=[v3]),
        }
        report = aggregator.aggregate(layer_results)

        assert report.total_violations == 2

    def test_empty_report_has_zero_violations(
        self, aggregator: ScanAggregator
    ) -> None:
        """An empty layer-results dict produces zero violations."""
        report = aggregator.aggregate({})

        assert report.total_violations == 0
        assert report.blocking_violations == 0

    def test_single_layer_many_violations(
        self, aggregator: ScanAggregator
    ) -> None:
        """A single layer with many distinct violations all appear."""
        violations = [
            _make_violation(code=f"E{i:03d}", file_path="app.py", line=i)
            for i in range(1, 21)
        ]

        layer_results = {"layer1": _make_layer(violations=violations)}
        report = aggregator.aggregate(layer_results)

        assert report.total_violations == 20
        assert report.blocking_violations == 20  # all default severity="error"
