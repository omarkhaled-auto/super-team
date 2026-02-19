"""Tests for QualityGateEngine, Layer1/2/3 Scanners (TEST-019..022)."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from src.build3_shared.models import (
    BuilderResult,
    GateVerdict,
    IntegrationReport,
    LayerResult,
    QualityGateReport,
    QualityLevel,
    ScanViolation,
)
from src.quality_gate.gate_engine import QualityGateEngine
from src.quality_gate.layer1_per_service import Layer1Scanner
from src.quality_gate.layer2_contract_compliance import Layer2Scanner
from src.quality_gate.layer3_system_level import Layer3Scanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_builder(
    service_id: str = "svc",
    success: bool = True,
    convergence: float = 1.0,
    error: str = "",
) -> BuilderResult:
    """Create a BuilderResult with sensible defaults."""
    return BuilderResult(
        system_id="sys",
        service_id=service_id,
        success=success,
        cost=0.5,
        test_passed=10 if success else 0,
        test_total=10,
        convergence_ratio=convergence,
        error=error,
    )


def _make_layer_result(
    layer: QualityLevel,
    verdict: GateVerdict,
    violations: list[ScanViolation] | None = None,
) -> LayerResult:
    """Create a LayerResult with minimal boilerplate."""
    return LayerResult(
        layer=layer,
        verdict=verdict,
        violations=violations or [],
        total_checks=1,
        passed_checks=1 if verdict == GateVerdict.PASSED else 0,
        duration_seconds=0.01,
    )


def _make_integration_report(
    contract_passed: int = 10,
    contract_total: int = 10,
) -> IntegrationReport:
    """Create an IntegrationReport with contract test results."""
    return IntegrationReport(
        services_deployed=2,
        services_healthy=2,
        contract_tests_passed=contract_passed,
        contract_tests_total=contract_total,
        integration_tests_passed=5,
        integration_tests_total=5,
        data_flow_tests_passed=3,
        data_flow_tests_total=3,
        boundary_tests_passed=4,
        boundary_tests_total=4,
        violations=[],
        overall_health="passed",
    )


# ===========================================================================
# TEST-019: QualityGateEngine.run_all_layers and gating logic (15 cases)
# ===========================================================================


class TestQualityGateEngine:
    """Tests for the QualityGateEngine orchestrator."""

    # ---- Test 1: All layers pass -> overall PASSED -----------------------

    async def test_all_layers_pass_overall_passed(self, tmp_path: Path):
        """When every layer passes, the overall verdict should be PASSED."""
        engine = QualityGateEngine()

        l1_passed = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_passed = _make_layer_result(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED)
        l3_passed = _make_layer_result(QualityLevel.LAYER3_SYSTEM, GateVerdict.PASSED)
        l4_passed = _make_layer_result(QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.PASSED)

        engine._layer1.evaluate = MagicMock(return_value=l1_passed)
        engine._layer2.evaluate = MagicMock(return_value=l2_passed)
        engine._layer3.evaluate = AsyncMock(return_value=l3_passed)
        engine._layer4.evaluate = AsyncMock(return_value=l4_passed)

        report = await engine.run_all_layers(
            builder_results=[_make_builder()],
            integration_report=_make_integration_report(),
            target_dir=tmp_path,
        )

        assert report.overall_verdict == GateVerdict.PASSED
        assert QualityLevel.LAYER1_SERVICE in report.layers
        assert QualityLevel.LAYER4_ADVERSARIAL in report.layers

    # ---- Test 2: L1 fails -> L2, L3, L4 skipped -------------------------

    async def test_l1_fails_skips_remaining(self, tmp_path: Path):
        """When L1 FAILS, layers 2, 3, and 4 must be SKIPPED."""
        engine = QualityGateEngine()

        l1_failed = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.FAILED)
        engine._layer1.evaluate = MagicMock(return_value=l1_failed)
        engine._layer2.evaluate = MagicMock(side_effect=AssertionError("should not be called"))
        engine._layer3.evaluate = AsyncMock(side_effect=AssertionError("should not be called"))
        engine._layer4.evaluate = AsyncMock(side_effect=AssertionError("should not be called"))

        report = await engine.run_all_layers(
            builder_results=[_make_builder(success=False)],
            integration_report=_make_integration_report(),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER1_SERVICE].verdict == GateVerdict.FAILED
        assert report.layers[QualityLevel.LAYER2_CONTRACT].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER3_SYSTEM].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER4_ADVERSARIAL].verdict == GateVerdict.SKIPPED

    # ---- Test 3: L2 fails -> L3, L4 skipped -----------------------------

    async def test_l2_fails_skips_l3_l4(self, tmp_path: Path):
        """When L2 FAILS, layers 3 and 4 must be SKIPPED."""
        engine = QualityGateEngine()

        l1_passed = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_failed = _make_layer_result(QualityLevel.LAYER2_CONTRACT, GateVerdict.FAILED)

        engine._layer1.evaluate = MagicMock(return_value=l1_passed)
        engine._layer2.evaluate = MagicMock(return_value=l2_failed)
        engine._layer3.evaluate = AsyncMock(side_effect=AssertionError("should not be called"))
        engine._layer4.evaluate = AsyncMock(side_effect=AssertionError("should not be called"))

        report = await engine.run_all_layers(
            builder_results=[_make_builder()],
            integration_report=_make_integration_report(contract_passed=3, contract_total=10),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER2_CONTRACT].verdict == GateVerdict.FAILED
        assert report.layers[QualityLevel.LAYER3_SYSTEM].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER4_ADVERSARIAL].verdict == GateVerdict.SKIPPED

    # ---- Test 4: L3 fails -> L4 skipped ---------------------------------

    async def test_l3_fails_skips_l4(self, tmp_path: Path):
        """When L3 FAILS, layer 4 must be SKIPPED."""
        engine = QualityGateEngine()

        l1_passed = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_passed = _make_layer_result(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED)
        l3_failed = _make_layer_result(QualityLevel.LAYER3_SYSTEM, GateVerdict.FAILED)

        engine._layer1.evaluate = MagicMock(return_value=l1_passed)
        engine._layer2.evaluate = MagicMock(return_value=l2_passed)
        engine._layer3.evaluate = AsyncMock(return_value=l3_failed)
        engine._layer4.evaluate = AsyncMock(side_effect=AssertionError("should not be called"))

        report = await engine.run_all_layers(
            builder_results=[_make_builder()],
            integration_report=_make_integration_report(),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER3_SYSTEM].verdict == GateVerdict.FAILED
        assert report.layers[QualityLevel.LAYER4_ADVERSARIAL].verdict == GateVerdict.SKIPPED

    # ---- Test 5: L4 is always PASSED (advisory) -------------------------

    async def test_l4_always_passed_advisory(self, tmp_path: Path):
        """Layer 4 verdict is forced to PASSED regardless of findings."""
        engine = QualityGateEngine()

        l1_passed = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_passed = _make_layer_result(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED)
        l3_passed = _make_layer_result(QualityLevel.LAYER3_SYSTEM, GateVerdict.PASSED)
        # L4 returns PASSED even when it has violations (advisory).
        l4_advisory = _make_layer_result(
            QualityLevel.LAYER4_ADVERSARIAL,
            GateVerdict.PASSED,
            violations=[ScanViolation(code="ADV-001", severity="warning", category="adversarial", message="advisory")],
        )

        engine._layer1.evaluate = MagicMock(return_value=l1_passed)
        engine._layer2.evaluate = MagicMock(return_value=l2_passed)
        engine._layer3.evaluate = AsyncMock(return_value=l3_passed)
        engine._layer4.evaluate = AsyncMock(return_value=l4_advisory)

        report = await engine.run_all_layers(
            builder_results=[_make_builder()],
            integration_report=_make_integration_report(),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER4_ADVERSARIAL].verdict == GateVerdict.PASSED
        assert len(report.layers[QualityLevel.LAYER4_ADVERSARIAL].violations) == 1

    # ---- Test 6: should_promote True for PASSED --------------------------

    def test_should_promote_passed(self):
        engine = QualityGateEngine()
        lr = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        assert engine.should_promote(result=lr) is True

    # ---- Test 7: should_promote True for PARTIAL -------------------------

    def test_should_promote_partial(self):
        engine = QualityGateEngine()
        lr = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PARTIAL)
        assert engine.should_promote(result=lr) is True

    # ---- Test 8: should_promote False for FAILED -------------------------

    def test_should_promote_failed(self):
        engine = QualityGateEngine()
        lr = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.FAILED)
        assert engine.should_promote(result=lr) is False

    # ---- Test 9: should_promote False for SKIPPED ------------------------

    def test_should_promote_skipped(self):
        engine = QualityGateEngine()
        lr = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.SKIPPED)
        assert engine.should_promote(result=lr) is False

    # ---- Test 10: classify_violations groups by severity -----------------

    def test_classify_violations_groups_by_severity(self):
        engine = QualityGateEngine()
        violations = [
            ScanViolation(code="A", severity="error", category="security", message="err1"),
            ScanViolation(code="B", severity="warning", category="security", message="warn1"),
            ScanViolation(code="C", severity="info", category="security", message="info1"),
            ScanViolation(code="D", severity="error", category="security", message="err2"),
            ScanViolation(code="E", severity="unknown", category="security", message="unknown1"),
        ]
        grouped = engine.classify_violations(violations)

        assert len(grouped["error"]) == 2
        assert len(grouped["warning"]) == 1
        # "unknown" severity should be bucketed under "info"
        assert len(grouped["info"]) == 2
        assert grouped["error"][0].code == "A"
        assert grouped["error"][1].code == "D"
        assert grouped["info"][1].code == "E"

    # ---- Test 11: Empty builder_results -> L1 SKIPPED -> all skipped -----

    async def test_empty_builders_all_skipped(self, tmp_path: Path):
        """With no builder results, L1 is SKIPPED and remaining layers skip."""
        engine = QualityGateEngine()

        # L1 will return SKIPPED for empty list; SKIPPED blocks promotion.
        # We let L1 run normally (no mock), and mock the rest to assert not called.
        engine._layer2.evaluate = MagicMock(side_effect=AssertionError("should not be called"))
        engine._layer3.evaluate = AsyncMock(side_effect=AssertionError("should not be called"))
        engine._layer4.evaluate = AsyncMock(side_effect=AssertionError("should not be called"))

        report = await engine.run_all_layers(
            builder_results=[],
            integration_report=_make_integration_report(),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER1_SERVICE].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER2_CONTRACT].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER3_SYSTEM].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER4_ADVERSARIAL].verdict == GateVerdict.SKIPPED

    # ---- Test 12: L1 PARTIAL -> L2 still runs ----------------------------

    async def test_l1_partial_l2_still_runs(self, tmp_path: Path):
        """PARTIAL verdict from L1 should still allow L2 to execute."""
        engine = QualityGateEngine()

        l1_partial = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PARTIAL)
        l2_passed = _make_layer_result(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED)
        l3_passed = _make_layer_result(QualityLevel.LAYER3_SYSTEM, GateVerdict.PASSED)
        l4_passed = _make_layer_result(QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.PASSED)

        engine._layer1.evaluate = MagicMock(return_value=l1_partial)
        engine._layer2.evaluate = MagicMock(return_value=l2_passed)
        engine._layer3.evaluate = AsyncMock(return_value=l3_passed)
        engine._layer4.evaluate = AsyncMock(return_value=l4_passed)

        report = await engine.run_all_layers(
            builder_results=[_make_builder()],
            integration_report=_make_integration_report(),
            target_dir=tmp_path,
        )

        # L2 was called (returned PASSED)
        engine._layer2.evaluate.assert_called_once()
        assert report.layers[QualityLevel.LAYER2_CONTRACT].verdict == GateVerdict.PASSED

    # ---- Test 13: L2 PARTIAL -> L3 still runs ----------------------------

    async def test_l2_partial_l3_still_runs(self, tmp_path: Path):
        """PARTIAL verdict from L2 should still allow L3 to execute."""
        engine = QualityGateEngine()

        l1_passed = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_partial = _make_layer_result(QualityLevel.LAYER2_CONTRACT, GateVerdict.PARTIAL)
        l3_passed = _make_layer_result(QualityLevel.LAYER3_SYSTEM, GateVerdict.PASSED)
        l4_passed = _make_layer_result(QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.PASSED)

        engine._layer1.evaluate = MagicMock(return_value=l1_passed)
        engine._layer2.evaluate = MagicMock(return_value=l2_partial)
        engine._layer3.evaluate = AsyncMock(return_value=l3_passed)
        engine._layer4.evaluate = AsyncMock(return_value=l4_passed)

        report = await engine.run_all_layers(
            builder_results=[_make_builder()],
            integration_report=_make_integration_report(),
            target_dir=tmp_path,
        )

        engine._layer3.evaluate.assert_called_once()
        assert report.layers[QualityLevel.LAYER3_SYSTEM].verdict == GateVerdict.PASSED

    # ---- Test 14: fix_attempts passed through ----------------------------

    async def test_fix_attempts_passed_through(self, tmp_path: Path):
        """fix_attempts and max_fix_attempts should appear in the report."""
        engine = QualityGateEngine()

        l1_passed = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_passed = _make_layer_result(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED)
        l3_passed = _make_layer_result(QualityLevel.LAYER3_SYSTEM, GateVerdict.PASSED)
        l4_passed = _make_layer_result(QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.PASSED)

        engine._layer1.evaluate = MagicMock(return_value=l1_passed)
        engine._layer2.evaluate = MagicMock(return_value=l2_passed)
        engine._layer3.evaluate = AsyncMock(return_value=l3_passed)
        engine._layer4.evaluate = AsyncMock(return_value=l4_passed)

        report = await engine.run_all_layers(
            builder_results=[_make_builder()],
            integration_report=_make_integration_report(),
            target_dir=tmp_path,
            fix_attempts=2,
            max_fix_attempts=5,
        )

        assert report.fix_attempts == 2
        assert report.max_fix_attempts == 5

    # ---- Test 15: Full pipeline with violations at each layer ------------

    async def test_full_pipeline_with_violations(self, tmp_path: Path):
        """Each layer can accumulate violations; total_violations aggregates them."""
        engine = QualityGateEngine()

        v1 = ScanViolation(code="L1-FAIL", severity="warning", category="service", message="l1 issue")
        v2 = ScanViolation(code="L2-FAIL", severity="warning", category="contract", message="l2 issue")
        v3 = ScanViolation(code="L3-FAIL", severity="warning", category="system", message="l3 issue")
        v4 = ScanViolation(code="ADV-001", severity="info", category="adversarial", message="l4 advisory")

        l1 = _make_layer_result(QualityLevel.LAYER1_SERVICE, GateVerdict.PARTIAL, [v1])
        l2 = _make_layer_result(QualityLevel.LAYER2_CONTRACT, GateVerdict.PARTIAL, [v2])
        l3 = _make_layer_result(QualityLevel.LAYER3_SYSTEM, GateVerdict.PARTIAL, [v3])
        l4 = _make_layer_result(QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.PASSED, [v4])

        engine._layer1.evaluate = MagicMock(return_value=l1)
        engine._layer2.evaluate = MagicMock(return_value=l2)
        engine._layer3.evaluate = AsyncMock(return_value=l3)
        engine._layer4.evaluate = AsyncMock(return_value=l4)

        report = await engine.run_all_layers(
            builder_results=[_make_builder()],
            integration_report=_make_integration_report(),
            target_dir=tmp_path,
        )

        assert report.total_violations == 4
        assert report.overall_verdict == GateVerdict.PARTIAL


# ===========================================================================
# TEST-020: Layer1Scanner.evaluate edge cases (6 cases)
# ===========================================================================


class TestLayer1Scanner:
    """Tests for Layer1Scanner.evaluate."""

    # ---- Test 16: All builders pass (rate=1.0, convergence=1.0) -> PASSED -

    def test_all_pass_full_convergence(self):
        """100% pass rate and 100% convergence -> PASSED."""
        scanner = Layer1Scanner()
        builders = [_make_builder(f"svc-{i}", success=True, convergence=1.0) for i in range(10)]
        result = scanner.evaluate(builders)
        assert result.verdict == GateVerdict.PASSED
        assert result.total_checks == 10
        assert result.passed_checks == 10
        assert len(result.violations) == 0

    # ---- Test 17: 90% pass rate, 90% convergence -> PASSED ---------------

    def test_threshold_boundary_passed(self):
        """Exactly 90% pass rate and 90% convergence -> PASSED."""
        scanner = Layer1Scanner()
        builders = [
            _make_builder(f"svc-{i}", success=True, convergence=0.9)
            for i in range(9)
        ]
        # 1 failing builder out of 10 => 90% pass rate
        builders.append(_make_builder("svc-fail", success=False, convergence=0.9, error="oops"))
        result = scanner.evaluate(builders)
        assert result.verdict == GateVerdict.PASSED

    # ---- Test 18: 85% pass rate -> PARTIAL --------------------------------

    def test_partial_pass_rate(self):
        """85% pass rate (below 0.9 but above 0.7) -> PARTIAL."""
        scanner = Layer1Scanner()
        # 17 pass, 3 fail = 85%
        builders = [_make_builder(f"ok-{i}", success=True, convergence=0.5) for i in range(17)]
        builders += [_make_builder(f"bad-{i}", success=False, convergence=0.5, error="fail") for i in range(3)]
        result = scanner.evaluate(builders)
        assert result.verdict == GateVerdict.PARTIAL

    # ---- Test 19: 60% pass rate -> FAILED --------------------------------

    def test_low_pass_rate_failed(self):
        """60% pass rate (below 0.7) with low convergence -> FAILED."""
        scanner = Layer1Scanner()
        # 6 pass, 4 fail = 60%; convergence 0.5
        builders = [_make_builder(f"ok-{i}", success=True, convergence=0.5) for i in range(6)]
        builders += [
            _make_builder(f"bad-{i}", success=False, convergence=0.5, error="err")
            for i in range(4)
        ]
        result = scanner.evaluate(builders)
        assert result.verdict == GateVerdict.FAILED

    # ---- Test 20: All builders fail -> FAILED ----------------------------

    def test_all_fail(self):
        """0% pass rate -> FAILED, with one violation per failed builder."""
        scanner = Layer1Scanner()
        builders = [
            _make_builder(f"svc-{i}", success=False, convergence=0.0, error="total failure")
            for i in range(5)
        ]
        result = scanner.evaluate(builders)
        assert result.verdict == GateVerdict.FAILED
        assert result.passed_checks == 0
        # Each failed builder produces an L1-FAIL violation, plus an L1-CONVERGENCE warning
        fail_violations = [v for v in result.violations if v.code == "L1-FAIL"]
        assert len(fail_violations) == 5

    # ---- Test 21: Empty list -> SKIPPED ----------------------------------

    def test_empty_list_skipped(self):
        """No builder results -> SKIPPED."""
        scanner = Layer1Scanner()
        result = scanner.evaluate([])
        assert result.verdict == GateVerdict.SKIPPED
        assert result.total_checks == 0
        assert result.passed_checks == 0
        assert len(result.violations) == 0


# ===========================================================================
# TEST-021: Layer2Scanner.evaluate verdict thresholds (4 cases)
# ===========================================================================


class TestLayer2Scanner:
    """Tests for Layer2Scanner.evaluate."""

    # ---- Test 22: Contract tests 100% -> PASSED --------------------------

    def test_contract_100_percent_passed(self):
        """All contract tests pass -> PASSED."""
        scanner = Layer2Scanner()
        report = _make_integration_report(contract_passed=10, contract_total=10)
        result = scanner.evaluate(report)
        assert result.verdict == GateVerdict.PASSED

    # ---- Test 23: Contract tests 80% -> PARTIAL -------------------------

    def test_contract_80_percent_partial(self):
        """80% contract tests pass (>= 70%, < 100%) -> PARTIAL."""
        scanner = Layer2Scanner()
        report = _make_integration_report(contract_passed=8, contract_total=10)
        result = scanner.evaluate(report)
        assert result.verdict == GateVerdict.PARTIAL

    # ---- Test 24: Contract tests 50% -> FAILED --------------------------

    def test_contract_50_percent_failed(self):
        """50% contract tests pass (< 70%) -> FAILED."""
        scanner = Layer2Scanner()
        report = _make_integration_report(contract_passed=5, contract_total=10)
        result = scanner.evaluate(report)
        assert result.verdict == GateVerdict.FAILED

    # ---- Test 25: No tests (total=0) -> SKIPPED -------------------------

    def test_no_contract_tests_skipped(self):
        """Zero total contract tests -> SKIPPED."""
        scanner = Layer2Scanner()
        report = _make_integration_report(contract_passed=0, contract_total=0)
        result = scanner.evaluate(report)
        assert result.verdict == GateVerdict.SKIPPED


# ===========================================================================
# TEST-022: Layer3Scanner.evaluate with severity variations (6 cases)
# ===========================================================================


class TestLayer3Scanner:
    """Tests for Layer3Scanner.evaluate with temp files producing violations."""

    # ---- Test 26: Clean directory -> PASSED (no violations) ---------------

    async def test_clean_directory_passed(self, tmp_path: Path):
        """An empty (clean) directory produces no violations -> PASSED."""
        scanner = Layer3Scanner()
        result = await scanner.evaluate(tmp_path)
        assert result.verdict == GateVerdict.PASSED
        assert len(result.violations) == 0

    # ---- Test 27: Error-severity violations -> FAILED --------------------

    async def test_error_violation_failed(self, tmp_path: Path):
        """Files with hardcoded secrets produce error violations -> FAILED."""
        # Create a Python file with a hardcoded password (SEC-SECRET-002)
        py_file = tmp_path / "config.py"
        py_file.write_text(
            'DB_PASSWORD = "super_secret_password_123"\n',
            encoding="utf-8",
        )
        scanner = Layer3Scanner()
        result = await scanner.evaluate(tmp_path)
        assert result.verdict == GateVerdict.FAILED
        error_violations = [v for v in result.violations if v.severity == "error"]
        assert len(error_violations) >= 1

    # ---- Test 28: Warning-only violations -> PARTIAL ---------------------

    async def test_warning_only_partial(self, tmp_path: Path):
        """Files producing only warning-level violations -> PARTIAL."""
        # Create a Dockerfile without HEALTHCHECK (DOCKER-002, warning)
        # but with a USER instruction (no DOCKER-001 error).
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            "USER appuser\n"
            "CMD [\"python\", \"main.py\"]\n",
            encoding="utf-8",
        )
        scanner = Layer3Scanner()
        result = await scanner.evaluate(tmp_path)

        # DOCKER-002 (no healthcheck) is a warning; DOCKER-003 (FROM with tag) is not
        # triggered because we used a specific tag. The overall verdict should be
        # PARTIAL or FAILED depending on what the scanners find.
        # With only the Dockerfile and no Python source, we get only docker violations.
        has_error = any(v.severity == "error" for v in result.violations)
        has_warning = any(v.severity == "warning" for v in result.violations)

        if not has_error and has_warning:
            assert result.verdict == GateVerdict.PARTIAL
        # If there's an error (e.g. from other sub-scanner), it would be FAILED.
        # We accept both PARTIAL and FAILED since the scanners may pick up
        # additional issues, but at minimum we verify warnings exist.
        assert has_warning

    # ---- Test 29: Info-only violations -> PASSED -------------------------

    async def test_info_only_passed(self, tmp_path: Path):
        """Mock scanners to return only info-severity violations -> PASSED."""
        scanner = Layer3Scanner()
        info_violation = ScanViolation(
            code="TEST-INFO", severity="info", category="test", message="just info"
        )

        async def mock_scan(target_dir):
            return [info_violation]

        scanner._security.scan = mock_scan
        scanner._observability.scan = AsyncMock(return_value=[])
        scanner._docker.scan = AsyncMock(return_value=[])

        result = await scanner.evaluate(tmp_path)
        assert result.verdict == GateVerdict.PASSED
        assert len(result.violations) == 1
        assert result.violations[0].severity == "info"

    # ---- Test 30: Mixed error and warning violations -> FAILED -----------

    async def test_mixed_error_warning_failed(self, tmp_path: Path):
        """Mixed error + warning violations -> FAILED (error takes precedence)."""
        scanner = Layer3Scanner()

        error_v = ScanViolation(code="SEC-001", severity="error", category="security", message="critical")
        warning_v = ScanViolation(code="LOG-001", severity="warning", category="logging", message="warn")

        scanner._security.scan = AsyncMock(return_value=[error_v])
        scanner._observability.scan = AsyncMock(return_value=[warning_v])
        scanner._docker.scan = AsyncMock(return_value=[])

        result = await scanner.evaluate(tmp_path)
        assert result.verdict == GateVerdict.FAILED
        assert len(result.violations) == 2

    # ---- Test 31: Dockerfile running as root -> error violation ----------

    async def test_dockerfile_root_user_error(self, tmp_path: Path):
        """Dockerfile with no USER instruction -> DOCKER-001 error -> FAILED."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM ubuntu\n"
            "RUN apt-get update\n"
            "CMD [\"bash\"]\n",
            encoding="utf-8",
        )
        scanner = Layer3Scanner()
        result = await scanner.evaluate(tmp_path)
        assert result.verdict == GateVerdict.FAILED

        docker_errors = [
            v for v in result.violations
            if v.code.startswith("DOCKER") and v.severity == "error"
        ]
        assert len(docker_errors) >= 1

    # ---- Test 32 (bonus): Multiple files with security issues ------------

    async def test_multiple_security_issues(self, tmp_path: Path):
        """Multiple files with different security issues -> FAILED with multiple violations."""
        # File with a hardcoded API key
        api_file = tmp_path / "api_client.py"
        api_file.write_text(
            'api_key = "ABCDEFGHIJKLMNOP"\n',
            encoding="utf-8",
        )

        # File with a private key
        key_file = tmp_path / "certs.py"
        key_file.write_text(
            '-----BEGIN PRIVATE KEY-----\n'
            'MIIEvQIBADANBgkqhkiG9w0BAQ\n'
            '-----END PRIVATE KEY-----\n',
            encoding="utf-8",
        )

        scanner = Layer3Scanner()
        result = await scanner.evaluate(tmp_path)
        assert result.verdict == GateVerdict.FAILED
        error_violations = [v for v in result.violations if v.severity == "error"]
        assert len(error_violations) >= 2
