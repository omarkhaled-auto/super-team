"""Comprehensive quality gate verification tests (40 scan codes + gating logic).

Verifies:
    Part A -- Layer gating logic (QualityGateEngine)
    Part B -- ScanAggregator deduplication and verdict
    Part C -- All 40 scan codes: positive detection AND false-positive-free
    Part D -- Layer-specific edge cases (Layer1-4)

Run with:
    pytest tests/build3/test_quality_gate_verification.py -v
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.build3_shared.constants import (
    ADVERSARIAL_SCAN_CODES,
    ALL_SCAN_CODES,
    CORS_SCAN_CODES,
    DOCKER_SCAN_CODES,
    HEALTH_SCAN_CODES,
    LOGGING_SCAN_CODES,
    SECRET_SCAN_CODES,
    SECURITY_SCAN_CODES,
    TRACE_SCAN_CODES,
)
from src.build3_shared.models import (
    BuilderResult,
    ContractViolation,
    GateVerdict,
    IntegrationReport,
    LayerResult,
    QualityGateReport,
    QualityLevel,
    ScanViolation,
)
from src.quality_gate.adversarial_patterns import AdversarialScanner
from src.quality_gate.docker_security import DockerSecurityScanner
from src.quality_gate.gate_engine import QualityGateEngine
from src.quality_gate.layer1_per_service import Layer1Scanner
from src.quality_gate.layer2_contract_compliance import Layer2Scanner
from src.quality_gate.layer3_system_level import Layer3Scanner
from src.quality_gate.layer4_adversarial import Layer4Scanner
from src.quality_gate.observability_checker import ObservabilityChecker
from src.quality_gate.scan_aggregator import ScanAggregator
from src.quality_gate.security_scanner import SecurityScanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _builder(
    service_id: str = "svc",
    success: bool = True,
    convergence: float = 1.0,
    error: str = "",
) -> BuilderResult:
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


def _layer(
    layer: QualityLevel,
    verdict: GateVerdict,
    violations: list[ScanViolation] | None = None,
) -> LayerResult:
    return LayerResult(
        layer=layer,
        verdict=verdict,
        violations=violations or [],
        total_checks=1,
        passed_checks=1 if verdict == GateVerdict.PASSED else 0,
        duration_seconds=0.01,
    )


def _violation(
    code: str = "V001",
    severity: str = "error",
    category: str = "test",
    file_path: str = "f.py",
    line: int = 1,
    message: str = "test",
) -> ScanViolation:
    return ScanViolation(
        code=code,
        severity=severity,
        category=category,
        file_path=file_path,
        line=line,
        message=message,
    )


def _integration_report(
    contract_passed: int = 10,
    contract_total: int = 10,
    integration_passed: int = 5,
    integration_total: int = 5,
    data_flow_passed: int = 3,
    data_flow_total: int = 3,
    boundary_passed: int = 4,
    boundary_total: int = 4,
) -> IntegrationReport:
    return IntegrationReport(
        services_deployed=2,
        services_healthy=2,
        contract_tests_passed=contract_passed,
        contract_tests_total=contract_total,
        integration_tests_passed=integration_passed,
        integration_tests_total=integration_total,
        data_flow_tests_passed=data_flow_passed,
        data_flow_tests_total=data_flow_total,
        boundary_tests_passed=boundary_passed,
        boundary_tests_total=boundary_total,
        violations=[],
        overall_health="passed",
    )


def _write(directory: Path, name: str, content: str) -> Path:
    """Write dedented content to a file and return the path."""
    p = directory / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _codes(violations: list[ScanViolation]) -> set[str]:
    return {v.code for v in violations}


# ===========================================================================
# PART A: Layer Gating Logic
# ===========================================================================


class TestLayerGatingLogic:
    """Verify the QualityGateEngine gating between layers."""

    # A1: L1 FAILED -> L2, L3, L4 all SKIPPED
    async def test_l1_failed_skips_all_remaining(self, tmp_path: Path) -> None:
        engine = QualityGateEngine()
        l1_fail = _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.FAILED,
                         [_violation("L1-FAIL", "error")])
        engine._layer1.evaluate = MagicMock(return_value=l1_fail)

        report = await engine.run_all_layers(
            builder_results=[_builder(success=False)],
            integration_report=_integration_report(),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER1_SERVICE].verdict == GateVerdict.FAILED
        assert report.layers[QualityLevel.LAYER2_CONTRACT].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER3_SYSTEM].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER4_ADVERSARIAL].verdict == GateVerdict.SKIPPED
        assert report.overall_verdict == GateVerdict.FAILED

    # A2: L2 FAILED -> L3, L4 SKIPPED (enters fix loop territory)
    async def test_l2_failed_skips_l3_l4(self, tmp_path: Path) -> None:
        engine = QualityGateEngine()
        l1_pass = _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_fail = _layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.FAILED,
                         [_violation("L2-FAIL", "error")])
        engine._layer1.evaluate = MagicMock(return_value=l1_pass)
        engine._layer2.evaluate = MagicMock(return_value=l2_fail)

        report = await engine.run_all_layers(
            builder_results=[_builder()],
            integration_report=_integration_report(contract_passed=3, contract_total=10),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER2_CONTRACT].verdict == GateVerdict.FAILED
        assert report.layers[QualityLevel.LAYER3_SYSTEM].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER4_ADVERSARIAL].verdict == GateVerdict.SKIPPED

    # A3: L3 FAILED -> L4 SKIPPED
    async def test_l3_failed_skips_l4(self, tmp_path: Path) -> None:
        engine = QualityGateEngine()
        l1_pass = _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_pass = _layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED)
        l3_fail = _layer(QualityLevel.LAYER3_SYSTEM, GateVerdict.FAILED,
                         [_violation("SEC-002", "error")])
        engine._layer1.evaluate = MagicMock(return_value=l1_pass)
        engine._layer2.evaluate = MagicMock(return_value=l2_pass)
        engine._layer3.evaluate = AsyncMock(return_value=l3_fail)

        report = await engine.run_all_layers(
            builder_results=[_builder()],
            integration_report=_integration_report(),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER3_SYSTEM].verdict == GateVerdict.FAILED
        assert report.layers[QualityLevel.LAYER4_ADVERSARIAL].verdict == GateVerdict.SKIPPED

    # A4: L4 is ALWAYS PASSED regardless of adversarial violations
    async def test_l4_always_passed_despite_violations(self, tmp_path: Path) -> None:
        engine = QualityGateEngine()

        adv_violations = [
            _violation("ADV-001", "warning", "adversarial"),
            _violation("ADV-005", "warning", "adversarial"),
        ]
        l1_pass = _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_pass = _layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED)
        l3_pass = _layer(QualityLevel.LAYER3_SYSTEM, GateVerdict.PASSED)
        l4_adv = _layer(QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.PASSED, adv_violations)

        engine._layer1.evaluate = MagicMock(return_value=l1_pass)
        engine._layer2.evaluate = MagicMock(return_value=l2_pass)
        engine._layer3.evaluate = AsyncMock(return_value=l3_pass)
        engine._layer4.evaluate = AsyncMock(return_value=l4_adv)

        report = await engine.run_all_layers(
            builder_results=[_builder()],
            integration_report=_integration_report(),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER4_ADVERSARIAL].verdict == GateVerdict.PASSED
        assert report.overall_verdict == GateVerdict.PASSED
        assert report.total_violations == 2

    # A5: max_fix_retries enforcement pass-through
    async def test_max_fix_retries_passed_through(self, tmp_path: Path) -> None:
        engine = QualityGateEngine()
        l1_pass = _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED)
        l2_pass = _layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED)
        l3_pass = _layer(QualityLevel.LAYER3_SYSTEM, GateVerdict.PASSED)
        l4_pass = _layer(QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.PASSED)

        engine._layer1.evaluate = MagicMock(return_value=l1_pass)
        engine._layer2.evaluate = MagicMock(return_value=l2_pass)
        engine._layer3.evaluate = AsyncMock(return_value=l3_pass)
        engine._layer4.evaluate = AsyncMock(return_value=l4_pass)

        report = await engine.run_all_layers(
            builder_results=[_builder()],
            integration_report=_integration_report(),
            target_dir=tmp_path,
            fix_attempts=2,
            max_fix_attempts=5,
        )

        assert report.fix_attempts == 2
        assert report.max_fix_attempts == 5

    # A6: PARTIAL L1 allows L2 to proceed
    async def test_l1_partial_allows_l2(self, tmp_path: Path) -> None:
        engine = QualityGateEngine()
        l1_partial = _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PARTIAL)
        l2_pass = _layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED)
        l3_pass = _layer(QualityLevel.LAYER3_SYSTEM, GateVerdict.PASSED)
        l4_pass = _layer(QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.PASSED)

        engine._layer1.evaluate = MagicMock(return_value=l1_partial)
        engine._layer2.evaluate = MagicMock(return_value=l2_pass)
        engine._layer3.evaluate = AsyncMock(return_value=l3_pass)
        engine._layer4.evaluate = AsyncMock(return_value=l4_pass)

        report = await engine.run_all_layers(
            builder_results=[_builder()],
            integration_report=_integration_report(),
            target_dir=tmp_path,
        )

        engine._layer2.evaluate.assert_called_once()
        assert report.layers[QualityLevel.LAYER2_CONTRACT].verdict == GateVerdict.PASSED

    # A7: should_promote returns False for None result
    def test_should_promote_none_result(self) -> None:
        engine = QualityGateEngine()
        assert engine.should_promote(result=None) is False

    # A8: should_promote with FAILED verdict but only warning violations
    #     (blocking_severity check: no error-level violations -> should promote)
    def test_should_promote_failed_but_no_blocking_severity(self) -> None:
        engine = QualityGateEngine()
        lr = LayerResult(
            layer=QualityLevel.LAYER1_SERVICE,
            verdict=GateVerdict.FAILED,
            violations=[_violation("W001", "warning")],
            total_checks=1,
            passed_checks=0,
            duration_seconds=0.01,
        )
        # With blocking_severity="error" and only warning violations,
        # should_promote returns True because no blocking violations exist
        assert engine.should_promote(result=lr) is True

    # A9: should_promote with FAILED verdict and error violations
    def test_should_promote_failed_with_blocking_violations(self) -> None:
        engine = QualityGateEngine()
        lr = LayerResult(
            layer=QualityLevel.LAYER1_SERVICE,
            verdict=GateVerdict.FAILED,
            violations=[_violation("E001", "error")],
            total_checks=1,
            passed_checks=0,
            duration_seconds=0.01,
        )
        assert engine.should_promote(result=lr) is False

    # A10: L1 SKIPPED -> everything skipped
    async def test_l1_skipped_skips_all(self, tmp_path: Path) -> None:
        engine = QualityGateEngine()

        report = await engine.run_all_layers(
            builder_results=[],
            integration_report=_integration_report(),
            target_dir=tmp_path,
        )

        assert report.layers[QualityLevel.LAYER1_SERVICE].verdict == GateVerdict.SKIPPED
        assert report.layers[QualityLevel.LAYER2_CONTRACT].verdict == GateVerdict.SKIPPED


# ===========================================================================
# PART B: ScanAggregator Deduplication and Verdict
# ===========================================================================


class TestScanAggregatorVerification:
    """Extended ScanAggregator verification."""

    def test_dedup_same_code_file_line(self) -> None:
        """Same (code, file_path, line) should be deduplicated."""
        agg = ScanAggregator()
        v1 = _violation("SEC-001", "warning", "jwt", "a.py", 10)
        v2 = _violation("SEC-001", "warning", "jwt", "a.py", 10)  # dup
        v3 = _violation("SEC-001", "warning", "jwt", "b.py", 10)  # different file

        lr = {
            "l1": _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED, [v1, v3]),
            "l2": _layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED, [v2]),
        }
        report = agg.aggregate(lr)
        assert report.total_violations == 2  # v1 and v3 kept, v2 deduped

    def test_overall_all_passed(self) -> None:
        """All PASSED layers -> PASSED overall."""
        agg = ScanAggregator()
        lr = {
            "l1": _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED),
            "l2": _layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.PASSED),
            "l3": _layer(QualityLevel.LAYER3_SYSTEM, GateVerdict.PASSED),
            "l4": _layer(QualityLevel.LAYER4_ADVERSARIAL, GateVerdict.PASSED),
        }
        report = agg.aggregate(lr)
        assert report.overall_verdict == GateVerdict.PASSED

    def test_overall_any_failed(self) -> None:
        """Any FAILED -> FAILED overall."""
        agg = ScanAggregator()
        lr = {
            "l1": _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED),
            "l2": _layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.FAILED),
        }
        report = agg.aggregate(lr)
        assert report.overall_verdict == GateVerdict.FAILED

    def test_overall_mixed_partial(self) -> None:
        """Any PARTIAL (no FAILED) -> PARTIAL overall."""
        agg = ScanAggregator()
        lr = {
            "l1": _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED),
            "l2": _layer(QualityLevel.LAYER2_CONTRACT, GateVerdict.PARTIAL),
        }
        report = agg.aggregate(lr)
        assert report.overall_verdict == GateVerdict.PARTIAL

    def test_blocking_violations_excludes_advisory(self) -> None:
        """Blocking violations count only severity='error', not advisory."""
        agg = ScanAggregator()
        v_error = _violation("E001", "error", "sec", "a.py", 1)
        v_warning = _violation("W001", "warning", "obs", "b.py", 2)
        v_info = _violation("I001", "info", "adv", "c.py", 3)

        lr = {
            "l1": _layer(QualityLevel.LAYER1_SERVICE, GateVerdict.PASSED,
                         [v_error, v_warning, v_info]),
        }
        report = agg.aggregate(lr)
        assert report.blocking_violations == 1
        assert report.total_violations == 3

    def test_empty_results_skipped(self) -> None:
        """Empty layer_results -> SKIPPED."""
        agg = ScanAggregator()
        report = agg.aggregate({})
        assert report.overall_verdict == GateVerdict.SKIPPED
        assert report.total_violations == 0
        assert report.blocking_violations == 0


# ===========================================================================
# PART C: All 40 Scan Code Verification
# ===========================================================================


class TestAllScanCodesExist:
    """Verify constants define exactly 40 scan codes."""

    def test_total_scan_codes_is_40(self) -> None:
        assert len(ALL_SCAN_CODES) == 40

    def test_all_codes_unique(self) -> None:
        assert len(set(ALL_SCAN_CODES)) == 40


# ---------------------------------------------------------------------------
# SEC-001 through SEC-006: JWT Security
# ---------------------------------------------------------------------------


class TestSEC001Verification:
    """SEC-001: Route without auth decorator."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/users")
            def list_users():
                return []
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-001" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @login_required
            @app.get("/users")
            def list_users():
                return []
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-001" not in _codes(violations)


class TestSEC002Verification:
    """SEC-002: Hardcoded JWT secret."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "auth.py", """\
            import jwt
            token = jwt.encode(payload, key="my-super-secret", algorithm="RS256")
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-002" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "auth.py", """\
            import jwt
            import os
            token = jwt.encode(payload, key=os.environ["JWT_KEY"], algorithm="RS256")
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-002" not in _codes(violations)


class TestSEC003Verification:
    """SEC-003: JWT encode without exp claim."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "token.py", """\
            import jwt
            payload = {"sub": "user123"}
            token = jwt.encode(payload, secret, algorithm="RS256")
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-003" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "token.py", """\
            import jwt
            import datetime
            payload = {
                "sub": "user123",
                "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1),
            }
            token = jwt.encode(payload, secret, algorithm="RS256")
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-003" not in _codes(violations)


class TestSEC004Verification:
    """SEC-004: Weak JWT signing algorithm."""

    async def test_detection_hs256(self, tmp_path: Path) -> None:
        _write(tmp_path, "enc.py", """\
            import jwt
            token = jwt.encode(payload, secret, algorithm='HS256')
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-004" in _codes(violations)

    async def test_detection_none(self, tmp_path: Path) -> None:
        _write(tmp_path, "enc.py", """\
            import jwt
            token = jwt.encode(payload, "", algorithm='none')
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-004" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "enc.py", """\
            import jwt
            token = jwt.encode(payload, secret, algorithm='RS256')
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-004" not in _codes(violations)


class TestSEC005Verification:
    """SEC-005: JWT decode without audience."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "verify.py", """\
            import jwt
            data = jwt.decode(token, secret, algorithms=["RS256"])
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-005" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "verify.py", """\
            import jwt
            data = jwt.decode(
                token,
                secret,
                algorithms=["RS256"],
                audience="my-app",
            )
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-005" not in _codes(violations)


class TestSEC006Verification:
    """SEC-006: JWT decode without issuer."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "verify.py", """\
            import jwt
            data = jwt.decode(token, secret, algorithms=["RS256"])
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-006" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "verify.py", """\
            import jwt
            data = jwt.decode(
                token,
                secret,
                algorithms=["RS256"],
                issuer="https://auth.example.com",
            )
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-006" not in _codes(violations)


# ---------------------------------------------------------------------------
# CORS-001 through CORS-003
# ---------------------------------------------------------------------------


class TestCORS001Verification:
    """CORS-001: Wildcard origin."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "main.py", """\
            from fastapi.middleware.cors import CORSMiddleware
            app.add_middleware(CORSMiddleware, allow_origins=["*"])
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "CORS-001" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "main.py", """\
            from fastapi.middleware.cors import CORSMiddleware
            app.add_middleware(CORSMiddleware, allow_origins=["https://example.com"])
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "CORS-001" not in _codes(violations)


class TestCORS002Verification:
    """CORS-002: Routes without CORS config."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "api.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/items")
            def list_items():
                return []
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "CORS-002" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "api.py", """\
            from fastapi import FastAPI
            from fastapi.middleware.cors import CORSMiddleware
            app = FastAPI()
            app.add_middleware(CORSMiddleware, allow_origins=["https://example.com"])

            @app.get("/items")
            def list_items():
                return []
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "CORS-002" not in _codes(violations)


class TestCORS003Verification:
    """CORS-003: Credentials with wildcard origin."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "cors.py", """\
            from fastapi.middleware.cors import CORSMiddleware
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
            )
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "CORS-003" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "cors.py", """\
            from fastapi.middleware.cors import CORSMiddleware
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["https://example.com"],
                allow_credentials=True,
            )
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "CORS-003" not in _codes(violations)


# ---------------------------------------------------------------------------
# SEC-SECRET-001 through SEC-SECRET-012
# ---------------------------------------------------------------------------


class TestSECSECRET001Verification:
    """SEC-SECRET-001: API key in source."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", 'api_key = "sk_live_abcdef1234567890"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-001" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", """\
            import os
            api_key = os.environ.get("API_KEY", "")
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-001" not in _codes(violations)


class TestSECSECRET002Verification:
    """SEC-SECRET-002: Password in source."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "db.py", 'password = "SuperSecret123!"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-002" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "db.py", """\
            import os
            password = os.environ["DB_PASSWORD"]
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-002" not in _codes(violations)


class TestSECSECRET003Verification:
    """SEC-SECRET-003: Private key block."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "keys.py", '-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-003" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "keys.py", """\
            # Load private key from file
            key_path = "/etc/ssl/private/key.pem"
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-003" not in _codes(violations)


class TestSECSECRET004Verification:
    """SEC-SECRET-004: AWS credentials."""

    async def test_detection_akia(self, tmp_path: Path) -> None:
        _write(tmp_path, "aws.py", 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-004" in _codes(violations)

    async def test_detection_secret_key(self, tmp_path: Path) -> None:
        _write(tmp_path, "aws.py",
               'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-004" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "aws.py", """\
            import boto3
            # Use IAM role for credentials
            client = boto3.client("s3")
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-004" not in _codes(violations)


class TestSECSECRET005Verification:
    """SEC-SECRET-005: Database connection string."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "db.py",
               'DB_URL = "postgresql://admin:password@localhost:5432/mydb"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-005" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "db.py", """\
            import os
            DB_URL = os.environ["DATABASE_URL"]
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-005" not in _codes(violations)


class TestSECSECRET006Verification:
    """SEC-SECRET-006: JWT secret in source."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "settings.py", 'JWT_SECRET = "my-jwt-secret-value-that-is-long"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-006" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "settings.py", """\
            import os
            JWT_SECRET = os.environ["JWT_SECRET"]
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-006" not in _codes(violations)


class TestSECSECRET007Verification:
    """SEC-SECRET-007: OAuth client secret."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "oauth.py", 'client_secret = "oauth-secret-value-here-long"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-007" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "oauth.py", """\
            import os
            client_secret = os.environ["OAUTH_SECRET"]
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-007" not in _codes(violations)


class TestSECSECRET008Verification:
    """SEC-SECRET-008: Encryption key in source."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "crypto.py", 'encryption_key = "aes256-key-value-long-enough"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-008" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "crypto.py", """\
            from kms import get_key
            encryption_key = get_key("data-key")
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-008" not in _codes(violations)


class TestSECSECRET009Verification:
    """SEC-SECRET-009: Token in source."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "token.py",
               'access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefghijk"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-009" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "token.py", """\
            def get_token(request):
                return request.headers.get("Authorization")
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-009" not in _codes(violations)


class TestSECSECRET010Verification:
    """SEC-SECRET-010: Certificate / EC private key."""

    async def test_detection_cert(self, tmp_path: Path) -> None:
        _write(tmp_path, "cert.py",
               '-----BEGIN CERTIFICATE-----\nMIIE...\n-----END CERTIFICATE-----\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-010" in _codes(violations)

    async def test_detection_ec_key(self, tmp_path: Path) -> None:
        _write(tmp_path, "ec.py",
               '-----BEGIN EC PRIVATE KEY-----\nMHQCAQEEIO...\n-----END EC PRIVATE KEY-----\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-010" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "cert.py", """\
            # Certificate loaded from file
            cert_path = "/etc/ssl/certs/ca.pem"
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-010" not in _codes(violations)


class TestSECSECRET011Verification:
    """SEC-SECRET-011: Service account key (GCP)."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "sa.json", """\
            {
              "type": "service_account",
              "project_id": "my-project"
            }
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-011" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "sa.json", """\
            {
              "type": "user_credentials",
              "project_id": "my-project"
            }
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-011" not in _codes(violations)


class TestSECSECRET012Verification:
    """SEC-SECRET-012: Webhook secret."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "webhooks.py", 'webhook_secret = "whsec_abcdefghijklmnop"\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-012" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "webhooks.py", """\
            import os
            webhook_secret = os.environ["WEBHOOK_SECRET"]
        """)
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-012" not in _codes(violations)


# ---------------------------------------------------------------------------
# LOG-001, LOG-004, LOG-005
# ---------------------------------------------------------------------------


class TestLOG001Verification:
    """LOG-001: Missing structured logging (print/console.log)."""

    async def test_detection_python_print(self, tmp_path: Path) -> None:
        _write(tmp_path, "service.py", """\
            def handle():
                print("debug info")
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "LOG-001" in _codes(violations)

    async def test_detection_js_console(self, tmp_path: Path) -> None:
        _write(tmp_path, "handler.ts", """\
            function process() {
              console.log("debug");
            }
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "LOG-001" in _codes(violations)

    async def test_no_false_positive_comment(self, tmp_path: Path) -> None:
        _write(tmp_path, "clean.py", """\
            # print("this is a comment")
            x = 42
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "LOG-001" not in _codes(violations)


class TestLOG004Verification:
    """LOG-004: Sensitive data in logs."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "auth.py", """\
            def login(username, password):
                print(f"Login attempt with password={password}")
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "LOG-004" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "orders.py", """\
            def process(order_id):
                print(f"Processing order {order_id}")
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "LOG-004" not in _codes(violations)


class TestLOG005Verification:
    """LOG-005: Missing request ID logging."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "routes.py", """\
            from fastapi import FastAPI

            app = FastAPI()

            @app.get('/users')
            async def list_users():
                return []
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "LOG-005" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "routes.py", """\
            from fastapi import FastAPI, Request

            app = FastAPI()

            @app.get('/users')
            async def list_users(request: Request):
                request_id = request.headers.get("x-request-id")
                return []
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "LOG-005" not in _codes(violations)


# ---------------------------------------------------------------------------
# TRACE-001
# ---------------------------------------------------------------------------


class TestTRACE001Verification:
    """TRACE-001: Missing trace context propagation."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "client.py", """\
            import httpx

            async def fetch_user(uid):
                return httpx.get(f"http://svc/users/{uid}")
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "TRACE-001" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "client.py", """\
            import httpx
            from opentelemetry import propagate

            async def fetch_user(uid):
                headers = {}
                propagate.inject(headers)
                return httpx.get(f"http://svc/users/{uid}", headers=headers)
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "TRACE-001" not in _codes(violations)


# ---------------------------------------------------------------------------
# HEALTH-001
# ---------------------------------------------------------------------------


class TestHEALTH001Verification:
    """HEALTH-001: Missing health endpoint."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "main.py", """\
            from fastapi import FastAPI

            app = FastAPI()

            @app.get('/users')
            async def list_users():
                return []
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "HEALTH-001" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "main.py", """\
            from fastapi import FastAPI

            app = FastAPI()

            @app.get('/health')
            async def health():
                return {"status": "ok"}

            @app.get('/users')
            async def list_users():
                return []
        """)
        violations = await ObservabilityChecker().scan(tmp_path)
        assert "HEALTH-001" not in _codes(violations)


# ---------------------------------------------------------------------------
# DOCKER-001 through DOCKER-008
# ---------------------------------------------------------------------------


class TestDOCKER001Verification:
    """DOCKER-001: Running as root."""

    async def test_detection_no_user(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python:3.12-slim
            RUN pip install app
            CMD ["python", "main.py"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-001" in _codes(violations)

    async def test_detection_user_root(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python:3.12-slim
            USER appuser
            RUN pip install app
            USER root
            CMD ["python", "main.py"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-001" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python:3.12-slim
            RUN adduser --disabled-password appuser
            USER appuser
            HEALTHCHECK CMD true
            CMD ["python", "main.py"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-001" not in _codes(violations)


class TestDOCKER002Verification:
    """DOCKER-002: No HEALTHCHECK."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python:3.12-slim
            USER appuser
            CMD ["python", "main.py"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-002" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python:3.12-slim
            USER appuser
            HEALTHCHECK --interval=30s CMD curl -f http://localhost/ || exit 1
            CMD ["python", "main.py"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-002" not in _codes(violations)


class TestDOCKER003Verification:
    """DOCKER-003: Using :latest tag."""

    async def test_detection_latest(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python:latest
            USER appuser
            HEALTHCHECK CMD true
            CMD ["python"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-003" in _codes(violations)

    async def test_detection_no_tag(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python
            USER appuser
            HEALTHCHECK CMD true
            CMD ["python"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-003" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python:3.12-slim
            USER appuser
            HEALTHCHECK CMD true
            CMD ["python"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-003" not in _codes(violations)


class TestDOCKER004Verification:
    """DOCKER-004: Exposing debug/sensitive ports."""

    async def test_detection_debug_port(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python:3.12-slim
            USER appuser
            HEALTHCHECK CMD true
            EXPOSE 8080 9229
            CMD ["python", "main.py"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-004" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "Dockerfile", """\
            FROM python:3.12-slim
            USER appuser
            HEALTHCHECK CMD true
            EXPOSE 8080
            CMD ["python", "main.py"]
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-004" not in _codes(violations)


class TestDOCKER005Verification:
    """DOCKER-005: Missing resource limits in compose."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "docker-compose.yml", """\
            version: "3.8"
            services:
              api:
                image: myapp:1.0
                ports:
                  - "8080:8080"
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-005" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "docker-compose.yml", """\
            version: "3.8"
            services:
              api:
                image: myapp:1.0
                deploy:
                  resources:
                    limits:
                      cpus: "0.5"
                      memory: 256M
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-005" not in _codes(violations)


class TestDOCKER006Verification:
    """DOCKER-006: Privileged container."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "docker-compose.yml", """\
            version: "3.8"
            services:
              worker:
                image: worker:1.0
                privileged: true
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-006" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "docker-compose.yml", """\
            version: "3.8"
            services:
              worker:
                image: worker:1.0
                deploy:
                  resources:
                    limits:
                      cpus: "0.5"
                      memory: 256M
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-006" not in _codes(violations)


class TestDOCKER007Verification:
    """DOCKER-007: Writable root filesystem."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "docker-compose.yml", """\
            version: "3.8"
            services:
              api-service:
                image: myapi:1.0
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-007" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "docker-compose.yml", """\
            version: "3.8"
            services:
              api-service:
                image: myapi:1.0
                read_only: true
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-007" not in _codes(violations)


class TestDOCKER008Verification:
    """DOCKER-008: Missing security opts."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "docker-compose.yml", """\
            version: "3.8"
            services:
              backend:
                image: backend:1.0
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-008" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "docker-compose.yml", """\
            version: "3.8"
            services:
              backend:
                image: backend:1.0
                security_opt:
                  - "no-new-privileges:true"
        """)
        violations = await DockerSecurityScanner().scan(tmp_path)
        assert "DOCKER-008" not in _codes(violations)


# ---------------------------------------------------------------------------
# ADV-001 through ADV-006
# ---------------------------------------------------------------------------


class TestADV001Verification:
    """ADV-001: Dead event handlers."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "handlers.py", """\
            from events import event_handler

            @event_handler("user.created")
            def on_user_created(event):
                print("User created:", event)
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-001" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "handlers.py", """\
            from events import event_handler

            @event_handler("user.created")
            def on_user_created(event):
                print("User created:", event)
        """)
        _write(tmp_path, "wiring.py", """\
            from handlers import on_user_created
            bus.register(on_user_created)
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-001" not in _codes(violations)


class TestADV002Verification:
    """ADV-002: Dead contracts."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "specs/orphan_api.yaml", """\
            openapi: "3.0.0"
            info:
              title: Orphan
              version: "1.0.0"
            paths: {}
        """)
        _write(tmp_path, "app.py", """\
            def main():
                print("no reference to the spec")
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-002" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "specs/user_api.yaml", """\
            openapi: "3.0.0"
            info:
              title: User API
              version: "1.0.0"
            paths: {}
        """)
        _write(tmp_path, "loader.py", """\
            spec = load("specs/user_api.yaml")
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-002" not in _codes(violations)


class TestADV003Verification:
    """ADV-003: Orphan services."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "service_a/main.py", """\
            def run():
                print("A")
        """)
        _write(tmp_path, "service_b/main.py", """\
            def run():
                print("B")
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-003" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "service_a/main.py", """\
            from service_b import helper
            def run():
                helper.do_thing()
        """)
        _write(tmp_path, "service_b/main.py", """\
            def do_thing():
                pass
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        # service_a references service_b, service_b is referenced by service_a
        # Neither should be orphan
        adv003 = [v for v in violations if v.code == "ADV-003"]
        assert len(adv003) == 0


class TestADV004Verification:
    """ADV-004: Naming inconsistency (camelCase in Python)."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "utils.py", """\
            def getUserName(uid):
                return f"user_{uid}"
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-004" in _codes(violations)

    async def test_no_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "utils.py", """\
            def get_user_name(uid):
                return f"user_{uid}"

            total_count = 0
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-004" not in _codes(violations)


class TestADV005Verification:
    """ADV-005: Missing error handling (bare except)."""

    async def test_detection_bare_except(self, tmp_path: Path) -> None:
        _write(tmp_path, "risky.py", """\
            def do_work():
                try:
                    result = 1 / 0
                except:
                    pass
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-005" in _codes(violations)

    async def test_detection_broad_except_no_reraise(self, tmp_path: Path) -> None:
        _write(tmp_path, "broad.py", """\
            def process():
                try:
                    do_something()
                except Exception as e:
                    log(e)
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-005" in _codes(violations)

    async def test_no_false_positive_specific_except(self, tmp_path: Path) -> None:
        _write(tmp_path, "safe.py", """\
            def parse(value):
                try:
                    return int(value)
                except ValueError:
                    return None
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-005" not in _codes(violations)


class TestADV006Verification:
    """ADV-006: Potential race conditions."""

    async def test_detection(self, tmp_path: Path) -> None:
        _write(tmp_path, "shared.py", """\
            CACHE: dict = {}

            def update(key, value):
                global CACHE
                CACHE[key] = value
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-006" in _codes(violations)

    async def test_no_false_positive_with_lock(self, tmp_path: Path) -> None:
        _write(tmp_path, "safe_shared.py", """\
            import threading

            _lock = threading.Lock()
            REGISTRY: dict = {}

            def register(name, handler):
                with _lock:
                    REGISTRY[name] = handler
        """)
        violations = await AdversarialScanner().scan(tmp_path)
        assert "ADV-006" not in _codes(violations)


# ===========================================================================
# PART D: Layer-Specific Edge Cases
# ===========================================================================


class TestLayer1EdgeCases:
    """Layer1Scanner additional edge cases."""

    def test_exactly_at_pass_threshold(self) -> None:
        """90% pass rate + 90% convergence -> PASSED."""
        scanner = Layer1Scanner()
        builders = [_builder(f"s{i}", True, 0.9) for i in range(9)]
        builders.append(_builder("sfail", False, 0.9, "oops"))
        result = scanner.evaluate(builders)
        assert result.verdict == GateVerdict.PASSED

    def test_just_below_partial_threshold(self) -> None:
        """Below 70% pass rate AND below 70% convergence -> FAILED."""
        scanner = Layer1Scanner()
        # 6 pass, 4 fail = 60%, convergence 0.5
        builders = [_builder(f"ok{i}", True, 0.5) for i in range(6)]
        builders += [_builder(f"bad{i}", False, 0.5, "fail") for i in range(4)]
        result = scanner.evaluate(builders)
        assert result.verdict == GateVerdict.FAILED

    def test_convergence_below_threshold_produces_warning(self) -> None:
        """Low convergence adds an L1-CONVERGENCE warning violation."""
        scanner = Layer1Scanner()
        builders = [_builder(f"s{i}", True, 0.5) for i in range(10)]
        result = scanner.evaluate(builders)
        convergence_v = [v for v in result.violations if v.code == "L1-CONVERGENCE"]
        assert len(convergence_v) == 1
        assert convergence_v[0].severity == "warning"


class TestLayer2EdgeCases:
    """Layer2Scanner additional edge cases."""

    def test_non_blocking_low_integration_tests(self) -> None:
        """Low integration tests add a warning but don't change verdict."""
        scanner = Layer2Scanner()
        report = _integration_report(
            contract_passed=10,
            contract_total=10,
            integration_passed=3,
            integration_total=10,
        )
        result = scanner.evaluate(report)
        assert result.verdict == GateVerdict.PASSED  # Only contract tests determine verdict
        low_warnings = [v for v in result.violations if v.code == "L2-LOW-INTEGRATION"]
        assert len(low_warnings) == 1
        assert low_warnings[0].severity == "warning"

    def test_contract_violations_converted(self) -> None:
        """ContractViolations in the report are converted to ScanViolations."""
        scanner = Layer2Scanner()
        report = _integration_report(contract_passed=9, contract_total=10)
        report.violations = [
            ContractViolation(
                code="CV-001",
                severity="error",
                service="auth",
                endpoint="/login",
                message="Schema mismatch",
                expected="200",
                actual="500",
                file_path="contracts/auth.yaml",
            )
        ]
        result = scanner.evaluate(report)
        cv_violations = [v for v in result.violations if v.code == "CV-001"]
        assert len(cv_violations) == 1
        assert cv_violations[0].category == "layer2"

    def test_exactly_at_70_percent_is_partial(self) -> None:
        """70% contract pass rate -> PARTIAL."""
        scanner = Layer2Scanner()
        report = _integration_report(contract_passed=7, contract_total=10)
        result = scanner.evaluate(report)
        assert result.verdict == GateVerdict.PARTIAL


class TestLayer3EdgeCases:
    """Layer3Scanner category extraction and verdict."""

    def test_get_category_sec_secret(self) -> None:
        assert Layer3Scanner._get_category("SEC-SECRET-001") == "SEC-SECRET"

    def test_get_category_sec(self) -> None:
        assert Layer3Scanner._get_category("SEC-001") == "SEC"

    def test_get_category_cors(self) -> None:
        assert Layer3Scanner._get_category("CORS-002") == "CORS"

    def test_get_category_docker(self) -> None:
        assert Layer3Scanner._get_category("DOCKER-005") == "DOCKER"

    def test_get_category_log(self) -> None:
        assert Layer3Scanner._get_category("LOG-001") == "LOG"

    def test_get_category_trace(self) -> None:
        assert Layer3Scanner._get_category("TRACE-001") == "TRACE"

    def test_get_category_health(self) -> None:
        assert Layer3Scanner._get_category("HEALTH-001") == "HEALTH"

    async def test_concurrent_scanner_execution(self, tmp_path: Path) -> None:
        """All three sub-scanners run concurrently via asyncio.gather."""
        scanner = Layer3Scanner()
        # An empty directory => all sub-scanners return empty => PASSED
        result = await scanner.evaluate(tmp_path)
        assert result.verdict == GateVerdict.PASSED
        assert len(result.violations) == 0


class TestLayer4AlwaysPassed:
    """Layer4Scanner verdict is ALWAYS PASSED."""

    async def test_with_violations_still_passed(self, tmp_path: Path) -> None:
        _write(tmp_path, "bad.py", """\
            def broken():
                try:
                    x = 1 / 0
                except:
                    pass
        """)
        layer4 = Layer4Scanner()
        result = await layer4.evaluate(tmp_path)
        assert result.verdict == GateVerdict.PASSED
        assert len(result.violations) >= 1

    async def test_empty_dir_still_passed(self, tmp_path: Path) -> None:
        layer4 = Layer4Scanner()
        result = await layer4.evaluate(tmp_path)
        assert result.verdict == GateVerdict.PASSED
        assert result.violations == []

    async def test_all_adversarial_severities_are_advisory(self, tmp_path: Path) -> None:
        """No adversarial violation should have severity 'error'."""
        _write(tmp_path, "multi.py", """\
            ITEMS: list = []

            def processItem(item):
                global ITEMS
                try:
                    ITEMS.append(item)
                except:
                    pass
        """)
        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)
        assert len(violations) >= 1
        for v in violations:
            assert v.severity in ("warning", "info"), (
                f"{v.code} has non-advisory severity '{v.severity}'"
            )


# ===========================================================================
# PART E: Nosec / Suppression Verification
# ===========================================================================


class TestNosecSuppression:
    """Verify that nosec and noqa suppress specific scan codes."""

    async def test_bare_nosec_suppresses(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", 'password = "SuperSecret123!"  # nosec\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-002" not in _codes(violations)

    async def test_noqa_specific_code_suppresses(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", 'api_key = "sk_live_abcdef1234567890"  # noqa: SEC-SECRET-001\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-001" not in _codes(violations)

    async def test_noqa_wrong_code_does_not_suppress(self, tmp_path: Path) -> None:
        _write(tmp_path, "config.py", 'password = "SuperSecret123!"  # noqa: CORS-001\n')
        violations = await SecurityScanner().scan(tmp_path)
        assert "SEC-SECRET-002" in _codes(violations)


# ===========================================================================
# PART F: classify_violations
# ===========================================================================


class TestClassifyViolations:
    """QualityGateEngine.classify_violations groups by severity."""

    def test_groups_by_severity(self) -> None:
        engine = QualityGateEngine()
        violations = [
            _violation("A", "error"),
            _violation("B", "warning"),
            _violation("C", "info"),
            _violation("D", "unknown_severity"),
        ]
        grouped = engine.classify_violations(violations)
        assert len(grouped["error"]) == 1
        assert len(grouped["warning"]) == 1
        # "unknown_severity" and "info" both go in info bucket
        assert len(grouped["info"]) == 2
