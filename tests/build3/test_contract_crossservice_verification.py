"""Contract compliance and cross-service integration verification tests.

Verification tests for Build 3 of the super-team project, covering:
  - Contract Compliance: Schemathesis API routing, ContractComplianceVerifier,
    ContractViolation construction, graceful degradation
  - ContractFixLoop: FIX_INSTRUCTIONS.md, severity grouping, builder subprocess
  - CrossServiceTestGenerator: chain detection, code generation, boundary tests
  - CrossServiceTestRunner: success/failure flow execution, data propagation
  - BoundaryTester: case sensitivity, null vs missing field
  - DataFlowTracer: multi-hop trace, single-hop fallback, trace IDs,
    verify_data_transformations
  - Integration Report: required sections, manageable output for many violations

Run with:
    pytest tests/build3/test_contract_crossservice_verification.py -v
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import sys
import types
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.build3_shared.models import ContractViolation, IntegrationReport

# ---------------------------------------------------------------------------
# Module-level mocks -- ensure schemathesis/pact never truly imported
# ---------------------------------------------------------------------------

_mock_schemathesis_module = MagicMock()
_mock_schemathesis_module.__name__ = "schemathesis"
_mock_schemathesis_module.from_url = MagicMock()
_mock_schemathesis_module.from_path = MagicMock()

_mock_requests_module = MagicMock()
_mock_requests_exceptions = MagicMock()
_mock_requests_module.exceptions = _mock_requests_exceptions
_mock_requests_exceptions.ConnectionError = ConnectionError

_mock_pact_module = types.ModuleType("pact")
_mock_pact_v3 = types.ModuleType("pact.v3")
_mock_pact_v3_verifier = types.ModuleType("pact.v3.verifier")
_mock_pact_v3_verifier.Verifier = MagicMock()  # type: ignore[attr-defined]
_mock_pact_module.v3 = _mock_pact_v3  # type: ignore[attr-defined]
_mock_pact_v3.verifier = _mock_pact_v3_verifier  # type: ignore[attr-defined]

sys.modules.setdefault("schemathesis", _mock_schemathesis_module)
sys.modules.setdefault("pact", _mock_pact_module)
sys.modules.setdefault("pact.v3", _mock_pact_v3)
sys.modules.setdefault("pact.v3.verifier", _mock_pact_v3_verifier)

# Now import the modules under test
from src.integrator.schemathesis_runner import SchemathesisRunner  # noqa: E402
from src.integrator.pact_manager import PactManager  # noqa: E402
from src.integrator.contract_compliance import ContractComplianceVerifier  # noqa: E402
from src.integrator.fix_loop import ContractFixLoop  # noqa: E402
from src.integrator.cross_service_test_generator import CrossServiceTestGenerator  # noqa: E402
from src.integrator.cross_service_test_runner import CrossServiceTestRunner  # noqa: E402
from src.integrator.boundary_tester import BoundaryTester  # noqa: E402
from src.integrator.data_flow_tracer import DataFlowTracer  # noqa: E402
from src.integrator.report import generate_integration_report  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================


def make_mock_response(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a fake httpx.Response with the given status and JSON body."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.text = json.dumps(json_data or {})
    return response


def write_openapi_spec(
    path: Path,
    service_name: str,
    endpoints: dict[str, Any],
    *,
    components: dict[str, Any] | None = None,
) -> None:
    """Write a minimal OpenAPI 3.0 spec JSON file."""
    spec: dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {"title": service_name, "version": "1.0.0"},
        "paths": endpoints,
    }
    if components:
        spec["components"] = components
    path.write_text(json.dumps(spec), encoding="utf-8")


def _user_service_endpoints() -> dict[str, Any]:
    """Endpoints for a 'user-service' with user_id and email response fields."""
    return {
        "/api/users": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "email": {"type": "string", "format": "email"},
                                },
                                "required": ["name", "email"],
                            }
                        }
                    }
                },
                "responses": {
                    "201": {
                        "description": "Created",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "user_id": {"type": "string"},
                                        "name": {"type": "string"},
                                        "email": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    }


def _order_service_endpoints() -> dict[str, Any]:
    """Endpoints for an 'order-service' that accepts user_id and email."""
    return {
        "/api/orders": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "user_id": {"type": "string"},
                                    "email": {"type": "string"},
                                    "product": {"type": "string"},
                                },
                                "required": ["user_id", "product"],
                            }
                        }
                    }
                },
                "responses": {
                    "201": {
                        "description": "Created",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "order_id": {"type": "string"},
                                        "status": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    }


def _write_state_json(
    builder_dir: Path, total_cost: float = 0.0, success: bool = True,
) -> None:
    """Write a minimal STATE.json for the builder."""
    state_dir = builder_dir / ".agent-team"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_data = {
        "health": "green",
        "completed_phases": [],
        "total_cost": total_cost,
        "summary": {
            "success": success,
            "test_passed": 5,
            "test_total": 5,
            "convergence_ratio": 1.0,
        },
    }
    (state_dir / "STATE.json").write_text(
        json.dumps(state_data), encoding="utf-8"
    )


def _mock_process(returncode: int = 0) -> MagicMock:
    """Return a mock subprocess whose .communicate() is an awaitable."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    return proc


# ===========================================================================
# SECTION 1: Contract Compliance Verification
# ===========================================================================


class TestSchemathesisAPIRouting:
    """Verify Schemathesis integration uses correct API (from_path or from_url)."""

    def test_load_schema_uses_from_url_for_http_urls(self) -> None:
        """V-CC-1a: _load_schema routes http:// URLs to openapi.from_url."""
        runner = SchemathesisRunner()
        mock_st = MagicMock()
        mock_st.openapi.from_url.return_value = MagicMock()

        with patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=mock_st,
        ):
            runner._load_schema(
                "http://localhost:8000/openapi.json",
                "http://localhost:8000",
            )

        mock_st.openapi.from_url.assert_called_once_with(
            "http://localhost:8000/openapi.json",
            base_url="http://localhost:8000",
        )
        mock_st.openapi.from_path.assert_not_called()

    def test_load_schema_uses_from_url_for_https_urls(self) -> None:
        """V-CC-1b: _load_schema routes https:// URLs to openapi.from_url."""
        runner = SchemathesisRunner()
        mock_st = MagicMock()
        mock_st.openapi.from_url.return_value = MagicMock()

        with patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=mock_st,
        ):
            runner._load_schema(
                "https://api.example.com/openapi.json",
                "https://api.example.com",
            )

        mock_st.openapi.from_url.assert_called_once()
        mock_st.openapi.from_path.assert_not_called()

    def test_load_schema_uses_from_path_for_file_paths(self) -> None:
        """V-CC-1c: _load_schema routes file paths to openapi.from_path."""
        runner = SchemathesisRunner()
        mock_st = MagicMock()
        mock_st.openapi.from_path.return_value = MagicMock()

        with patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=mock_st,
        ):
            runner._load_schema(
                "/tmp/specs/service-a.json",
                "http://localhost:8000",
            )

        mock_st.openapi.from_path.assert_called_once_with(
            "/tmp/specs/service-a.json",
            base_url="http://localhost:8000",
        )
        mock_st.openapi.from_url.assert_not_called()

    def test_generate_test_file_uses_from_url_in_generated_code(self) -> None:
        """V-CC-1d: generate_test_file output references schemathesis.openapi.from_url."""
        runner = SchemathesisRunner()
        code = runner.generate_test_file("http://example.com/openapi.json")
        assert "schemathesis.openapi.from_url" in code


class TestContractComplianceVerifierStructure:
    """Verify ContractComplianceVerifier.verify_all_services() structure."""

    @pytest.mark.asyncio
    async def test_verify_all_services_returns_integration_report(
        self, tmp_path: Path,
    ) -> None:
        """V-CC-2a: verify_all_services returns IntegrationReport instance."""
        verifier = ContractComplianceVerifier(
            contract_registry_path=tmp_path, services={},
        )
        report = await verifier.verify_all_services([], {}, tmp_path)
        assert isinstance(report, IntegrationReport)

    @pytest.mark.asyncio
    async def test_verify_all_services_populates_test_counts(
        self, tmp_path: Path,
    ) -> None:
        """V-CC-2b: Each service with openapi_url increments contract_tests_total by 2
        (positive + negative)."""
        verifier = ContractComplianceVerifier(
            contract_registry_path=tmp_path, services={},
        )
        services = [
            {"service_id": "svc-a", "openapi_url": "http://a/openapi.json"},
        ]
        service_urls = {"svc-a": "http://a"}

        with patch.object(
            verifier._schemathesis, "run_against_service",
            new_callable=AsyncMock, return_value=[],
        ), patch.object(
            verifier._schemathesis, "run_negative_tests",
            new_callable=AsyncMock, return_value=[],
        ):
            report = await verifier.verify_all_services(
                services, service_urls, tmp_path,
            )

        # One service with openapi_url -> 2 tests (positive + negative)
        assert report.contract_tests_total == 2
        assert report.contract_tests_passed == 2

    @pytest.mark.asyncio
    async def test_verify_all_services_skips_service_without_url(
        self, tmp_path: Path,
    ) -> None:
        """V-CC-2c: Service without URL in service_urls is skipped entirely."""
        verifier = ContractComplianceVerifier(
            contract_registry_path=tmp_path, services={},
        )
        services = [
            {"service_id": "ghost-svc", "openapi_url": "http://ghost/openapi.json"},
        ]
        # No URL for ghost-svc
        service_urls: dict[str, str] = {}

        with patch.object(
            verifier._schemathesis, "run_against_service",
            new_callable=AsyncMock, return_value=[],
        ) as mock_schema:
            report = await verifier.verify_all_services(
                services, service_urls, tmp_path,
            )

        mock_schema.assert_not_awaited()
        assert report.contract_tests_total == 0

    @pytest.mark.asyncio
    async def test_verify_all_services_determines_health_correctly(
        self, tmp_path: Path,
    ) -> None:
        """V-CC-2d: No violations + all tests pass = 'passed' health."""
        verifier = ContractComplianceVerifier(
            contract_registry_path=tmp_path, services={},
        )
        services = [
            {"service_id": "svc-a", "openapi_url": "http://a/openapi.json"},
        ]
        service_urls = {"svc-a": "http://a"}

        with patch.object(
            verifier._schemathesis, "run_against_service",
            new_callable=AsyncMock, return_value=[],
        ), patch.object(
            verifier._schemathesis, "run_negative_tests",
            new_callable=AsyncMock, return_value=[],
        ):
            report = await verifier.verify_all_services(
                services, service_urls, tmp_path,
            )

        assert report.overall_health == "passed"


class TestContractViolationConstruction:
    """Verify ContractViolation entries are constructed correctly from findings."""

    def test_violation_from_schema_mismatch(self) -> None:
        """V-CC-3a: ContractViolation for schema mismatch has correct fields."""
        v = ContractViolation(
            code="SCHEMA-001",
            severity="error",
            service="auth-service",
            endpoint="GET /users",
            message="Response missing field 'token'",
            expected="Schema-compliant response",
            actual="400",
        )
        assert v.code == "SCHEMA-001"
        assert v.severity == "error"
        assert v.service == "auth-service"
        assert v.endpoint == "GET /users"
        assert v.message == "Response missing field 'token'"

    def test_violation_from_status_code(self) -> None:
        """V-CC-3b: ContractViolation for unexpected status code."""
        v = ContractViolation(
            code="SCHEMA-002",
            severity="error",
            service="order-service",
            endpoint="POST /orders",
            message="Unexpected status code 500",
            expected="2xx",
            actual="500",
        )
        assert v.code == "SCHEMA-002"
        assert v.expected == "2xx"
        assert v.actual == "500"

    def test_violation_from_slow_response(self) -> None:
        """V-CC-3c: ContractViolation for slow response."""
        v = ContractViolation(
            code="SCHEMA-003",
            severity="warning",
            service="search-service",
            endpoint="GET /search",
            message="Response took 6.00s (threshold 5.0s)",
            expected="<5.0s",
            actual="6.00s",
        )
        assert v.severity == "warning"
        assert "5.0s" in v.expected

    @pytest.mark.asyncio
    async def test_violation_constructed_on_task_exception(
        self, tmp_path: Path,
    ) -> None:
        """V-CC-3d: When a verification task raises, an INTERNAL-001 violation is created."""
        verifier = ContractComplianceVerifier(
            contract_registry_path=tmp_path, services={},
        )
        services = [
            {"service_id": "svc-a", "openapi_url": "http://a/openapi.json"},
        ]
        service_urls = {"svc-a": "http://a"}

        with patch.object(
            verifier._schemathesis, "run_against_service",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection pooled out"),
        ), patch.object(
            verifier._schemathesis, "run_negative_tests",
            new_callable=AsyncMock, return_value=[],
        ):
            report = await verifier.verify_all_services(
                services, service_urls, tmp_path,
            )

        internal = [v for v in report.violations if v.code == "INTERNAL-001"]
        assert len(internal) >= 1
        assert "connection pooled out" in internal[0].message
        assert internal[0].service == "svc-a"


class TestGracefulDegradation:
    """Verify graceful degradation when services are unavailable."""

    @pytest.mark.asyncio
    async def test_pact_unavailable_returns_pact001(self) -> None:
        """V-CC-4a: When pact-python is not installed, verify_provider returns PACT-001."""
        manager = PactManager(pact_dir=Path("/tmp/pacts"))
        manager._pact_available = False

        violations = await manager.verify_provider(
            "auth-service",
            "http://localhost:8000",
            [Path("/tmp/pact.json")],
        )

        assert len(violations) == 1
        assert violations[0].code == "PACT-001"
        assert "not installed" in violations[0].message

    @pytest.mark.asyncio
    async def test_schemathesis_schema_load_error_returns_empty(self) -> None:
        """V-CC-4b: Schema load failure returns empty list (no crash)."""
        runner = SchemathesisRunner()

        with patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=_mock_schemathesis_module,
        ), patch(
            "src.integrator.schemathesis_runner._ensure_requests_exceptions",
            return_value=_mock_requests_exceptions,
        ), patch.object(
            runner, "_load_schema", side_effect=Exception("no such host"),
        ):
            result = await runner.run_against_service(
                "svc-a", "http://unreachable/openapi.json", "http://unreachable",
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_pact_nonexistent_directory_returns_empty(self) -> None:
        """V-CC-4c: load_pacts with nonexistent directory returns empty dict."""
        manager = PactManager(pact_dir=Path("/nonexistent/pacts"))
        grouped = await manager.load_pacts()
        assert grouped == {}

    @pytest.mark.asyncio
    async def test_verifier_handles_no_services(self, tmp_path: Path) -> None:
        """V-CC-4d: Empty services list returns report with unknown health."""
        verifier = ContractComplianceVerifier(
            contract_registry_path=tmp_path, services={},
        )
        report = await verifier.verify_all_services([], {}, tmp_path)
        assert report.overall_health == "unknown"
        assert report.contract_tests_total == 0


# ===========================================================================
# SECTION 2: ContractFixLoop
# ===========================================================================


class TestFixLoopInstructions:
    """Verify FIX_INSTRUCTIONS.md writing and content."""

    @pytest.mark.asyncio
    async def test_fix_instructions_written_to_builder_dir(
        self, tmp_path: Path,
    ) -> None:
        """V-FL-1a: FIX_INSTRUCTIONS.md is written inside builder_dir."""
        loop = ContractFixLoop()
        builder_dir = tmp_path / "builder"
        builder_dir.mkdir(parents=True, exist_ok=True)
        _write_state_json(builder_dir)

        violations = [
            ContractViolation(
                code="SC-001", severity="error", service="svc-a",
                endpoint="/api/test", message="schema error",
            ),
        ]
        mock_proc = _mock_process()

        with patch(
            "src.integrator.fix_loop.asyncio.create_subprocess_exec",
            new_callable=AsyncMock, return_value=mock_proc,
        ):
            await loop.feed_violations_to_builder("svc-a", violations, builder_dir)

        fix_file = builder_dir / "FIX_INSTRUCTIONS.md"
        assert fix_file.exists()
        content = fix_file.read_text(encoding="utf-8")
        assert "SC-001" in content

    @pytest.mark.asyncio
    async def test_fix_instructions_creates_dir_if_missing(
        self, tmp_path: Path,
    ) -> None:
        """V-FL-1b: builder_dir is created if it does not exist."""
        loop = ContractFixLoop()
        builder_dir = tmp_path / "deep" / "nested" / "builder"
        assert not builder_dir.exists()

        violations = [
            ContractViolation(
                code="V001", severity="error", service="svc-a",
                endpoint="/test", message="msg",
            ),
        ]
        mock_proc = _mock_process()

        with patch(
            "src.integrator.fix_loop.asyncio.create_subprocess_exec",
            new_callable=AsyncMock, return_value=mock_proc,
        ):
            await loop.feed_violations_to_builder("svc-a", violations, builder_dir)

        assert builder_dir.exists()
        assert (builder_dir / "FIX_INSTRUCTIONS.md").exists()


class TestFixLoopSeverityGrouping:
    """Verify violations are grouped by severity with correct priority ordering."""

    def test_classify_critical_to_p0_error_to_p1_rest_to_p2(self) -> None:
        """V-FL-2a: classify_violations returns correct grouping."""
        loop = ContractFixLoop()
        violations = [
            ContractViolation(
                code="C1", severity="critical", service="s", endpoint="e",
                message="m",
            ),
            ContractViolation(
                code="E1", severity="error", service="s", endpoint="e",
                message="m",
            ),
            ContractViolation(
                code="W1", severity="warning", service="s", endpoint="e",
                message="m",
            ),
            ContractViolation(
                code="I1", severity="info", service="s", endpoint="e",
                message="m",
            ),
        ]
        classified = loop.classify_violations(violations)

        assert len(classified["critical"]) == 1
        assert len(classified["error"]) == 1
        assert len(classified["warning"]) == 1
        assert len(classified["info"]) == 1
        # Verify ordering: keys should be critical, error, warning, info
        assert list(classified.keys()) == ["critical", "error", "warning", "info"]

    @pytest.mark.asyncio
    async def test_fix_instructions_priority_mapping(
        self, tmp_path: Path,
    ) -> None:
        """V-FL-2b: FIX_INSTRUCTIONS.md maps critical->P0, error->P1, warning->P2."""
        loop = ContractFixLoop()
        builder_dir = tmp_path / "builder"
        builder_dir.mkdir(parents=True, exist_ok=True)
        _write_state_json(builder_dir)

        violations = [
            ContractViolation(
                code="C1", severity="critical", service="svc-a",
                endpoint="/api", message="critical issue",
            ),
            ContractViolation(
                code="E1", severity="error", service="svc-a",
                endpoint="/api", message="error issue",
            ),
            ContractViolation(
                code="W1", severity="warning", service="svc-a",
                endpoint="/api", message="warning issue",
            ),
        ]
        mock_proc = _mock_process()

        with patch(
            "src.integrator.fix_loop.asyncio.create_subprocess_exec",
            new_callable=AsyncMock, return_value=mock_proc,
        ):
            await loop.feed_violations_to_builder("svc-a", violations, builder_dir)

        content = (builder_dir / "FIX_INSTRUCTIONS.md").read_text(encoding="utf-8")
        assert "P0" in content  # critical -> P0
        assert "P1" in content  # error -> P1
        assert "P2" in content  # warning -> P2


class TestFixLoopBuilderSubprocess:
    """Verify builder subprocess is invoked in quick mode."""

    @pytest.mark.asyncio
    async def test_builder_invoked_with_quick_depth(
        self, tmp_path: Path,
    ) -> None:
        """V-FL-3a: subprocess called with '--depth quick' args."""
        loop = ContractFixLoop()
        builder_dir = tmp_path / "builder"
        builder_dir.mkdir(parents=True, exist_ok=True)
        _write_state_json(builder_dir)

        violations = [
            ContractViolation(
                code="V001", severity="error", service="svc-a",
                endpoint="/test", message="msg",
            ),
        ]
        mock_proc = _mock_process()

        with patch(
            "src.integrator.fix_loop.asyncio.create_subprocess_exec",
            new_callable=AsyncMock, return_value=mock_proc,
        ) as mock_exec:
            await loop.feed_violations_to_builder("svc-a", violations, builder_dir)

        call_args = mock_exec.call_args
        positional_args = call_args[0]
        assert positional_args[0] == sys.executable
        assert "-m" in positional_args
        assert "agent_team" in positional_args
        assert "--depth" in positional_args
        assert "quick" in positional_args
        assert "--cwd" in positional_args
        assert str(builder_dir) in positional_args


# ===========================================================================
# SECTION 3: CrossServiceTestGenerator
# ===========================================================================


class TestChainDetectionAlgorithm:
    """Verify chain detection: response fields matched to request fields with >= 2 overlap."""

    @pytest.mark.asyncio
    async def test_two_services_with_two_field_overlap_produces_chain(
        self, tmp_path: Path,
    ) -> None:
        """V-GEN-1a: user_id + email overlap between user-service response
        and order-service request produces at least one flow."""
        registry = tmp_path / "registry"
        registry.mkdir()

        write_openapi_spec(
            registry / "user-service.json", "user-service",
            _user_service_endpoints(),
        )
        write_openapi_spec(
            registry / "order-service.json", "order-service",
            _order_service_endpoints(),
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        flows = await gen.generate_flow_tests()

        assert len(flows) >= 1
        # Each flow should have at least 2 steps (the two chained services)
        for flow in flows:
            assert len(flow["steps"]) >= 2

    @pytest.mark.asyncio
    async def test_services_with_one_field_overlap_no_chain(
        self, tmp_path: Path,
    ) -> None:
        """V-GEN-1b: Only 1 overlapping field (<2) produces no flows."""
        registry = tmp_path / "registry"
        registry.mkdir()

        # Service A response: {shared_id}
        write_openapi_spec(
            registry / "alpha.json", "alpha",
            {
                "/api/a": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "input_a": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "shared_id": {"type": "string"},
                                                "unique_a": {"type": "string"},
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        )
        # Service B request: {shared_id} -- only 1 field overlaps
        write_openapi_spec(
            registry / "beta.json", "beta",
            {
                "/api/b": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "shared_id": {"type": "string"},
                                            "unique_b": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "result_b": {"type": "string"},
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        flows = await gen.generate_flow_tests()

        assert flows == []

    @pytest.mark.asyncio
    async def test_min_field_overlap_constant_is_two(self) -> None:
        """V-GEN-1c: The _MIN_FIELD_OVERLAP constant is 2."""
        from src.integrator.cross_service_test_generator import _MIN_FIELD_OVERLAP
        assert _MIN_FIELD_OVERLAP == 2


class TestGenerateTestFile:
    """Verify generate_test_file produces valid Python (ast.parse succeeds)."""

    def test_generated_code_compiles(self) -> None:
        """V-GEN-2a: generate_test_file output passes ast.parse."""
        gen = CrossServiceTestGenerator(contract_registry_path=Path("."))
        flows = [
            {
                "flow_id": "flow_001",
                "description": "svc-a -> svc-b",
                "steps": [
                    {
                        "service": "svc-a",
                        "method": "POST",
                        "path": "/api/users",
                        "request_template": {"name": "test"},
                        "expected_status": 201,
                    },
                    {
                        "service": "svc-b",
                        "method": "POST",
                        "path": "/api/orders",
                        "request_template": {"user_id": "1"},
                        "expected_status": 201,
                    },
                ],
            }
        ]
        boundary_tests = [
            {
                "test_id": "boundary_001",
                "test_type": "null_handling",
                "service": "svc-a",
                "endpoint": "/api/users",
                "test_data": {"method": "POST", "field": "name", "variants": []},
            },
            {
                "test_id": "boundary_002",
                "test_type": "case_sensitivity",
                "service": "svc-a",
                "endpoint": "/api/users",
                "test_data": {
                    "method": "POST",
                    "field": "name",
                    "variants": [
                        {"style": "camelCase", "key": "myName", "value": "test"},
                        {"style": "snake_case", "key": "my_name", "value": "test"},
                    ],
                },
            },
            {
                "test_id": "boundary_003",
                "test_type": "timezone_handling",
                "service": "svc-a",
                "endpoint": "/api/events",
                "test_data": {
                    "method": "POST",
                    "field": "created_at",
                    "variants": ["2024-01-15T10:30:00Z", "2024-01-15T10:30:00+00:00"],
                },
            },
        ]

        code = gen.generate_test_file(flows, boundary_tests)
        tree = ast.parse(code)
        assert isinstance(tree, ast.Module)

    def test_generated_code_empty_inputs(self) -> None:
        """V-GEN-2b: Empty inputs still produce valid Python."""
        gen = CrossServiceTestGenerator(contract_registry_path=Path("."))
        code = gen.generate_test_file([], [])
        tree = ast.parse(code)
        assert isinstance(tree, ast.Module)
        assert "import" in code

    def test_generated_code_contains_test_functions(self) -> None:
        """V-GEN-2c: Generated code contains async def test_ functions for flows."""
        gen = CrossServiceTestGenerator(contract_registry_path=Path("."))
        flows = [
            {
                "flow_id": "flow_001",
                "description": "chain test",
                "steps": [
                    {
                        "service": "svc-a",
                        "method": "GET",
                        "path": "/api/data",
                        "request_template": {},
                        "expected_status": 200,
                    },
                ],
            },
        ]
        code = gen.generate_test_file(flows, [])
        assert "async def test_flow_001" in code


class TestBoundaryTestGeneration:
    """Verify boundary test generation for camelCase/snake_case, timezone, null/missing."""

    @pytest.mark.asyncio
    async def test_generates_case_sensitivity_tests(self, tmp_path: Path) -> None:
        """V-GEN-3a: String fields (non-datetime) produce case_sensitivity tests."""
        registry = tmp_path / "reg"
        registry.mkdir()
        write_openapi_spec(
            registry / "svc.json", "my-service",
            {
                "/api/items": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "item_name": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        boundary = await gen.generate_boundary_tests()

        case_tests = [b for b in boundary if b["test_type"] == "case_sensitivity"]
        assert len(case_tests) >= 1
        assert case_tests[0]["test_data"]["field"] == "item_name"
        # Check that camelCase and snake_case variants are generated
        variants = case_tests[0]["test_data"]["variants"]
        styles = {v["style"] for v in variants}
        assert "camelCase" in styles
        assert "snake_case" in styles

    @pytest.mark.asyncio
    async def test_generates_timezone_tests_for_datetime_fields(
        self, tmp_path: Path,
    ) -> None:
        """V-GEN-3b: Date-time formatted fields produce timezone_handling tests."""
        registry = tmp_path / "reg"
        registry.mkdir()
        write_openapi_spec(
            registry / "svc.json", "event-service",
            {
                "/api/events": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "event_time": {
                                                "type": "string",
                                                "format": "date-time",
                                            },
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        boundary = await gen.generate_boundary_tests()

        tz_tests = [b for b in boundary if b["test_type"] == "timezone_handling"]
        assert len(tz_tests) >= 1
        assert tz_tests[0]["test_data"]["field"] == "event_time"

    @pytest.mark.asyncio
    async def test_generates_null_handling_tests(self, tmp_path: Path) -> None:
        """V-GEN-3c: Nullable/optional fields produce null_handling tests."""
        registry = tmp_path / "reg"
        registry.mkdir()
        write_openapi_spec(
            registry / "svc.json", "item-service",
            {
                "/api/items": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "description": {
                                                "type": "string",
                                                "nullable": True,
                                            },
                                        },
                                        "required": [],
                                    }
                                }
                            }
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        boundary = await gen.generate_boundary_tests()

        null_tests = [b for b in boundary if b["test_type"] == "null_handling"]
        assert len(null_tests) >= 1
        # Must include null_value, missing_key, empty_string variants
        variants = null_tests[0]["test_data"]["variants"]
        cases = {v["case"] for v in variants}
        assert "null_value" in cases
        assert "missing_key" in cases
        assert "empty_string" in cases


# ===========================================================================
# SECTION 4: CrossServiceTestRunner
# ===========================================================================


class TestRunSingleFlowSuccess:
    """Verify run_single_flow success case."""

    @pytest.mark.asyncio
    async def test_all_steps_pass_returns_true(self) -> None:
        """V-RUN-1a: All steps matching expected_status -> (True, [])."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_ok",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "GET",
                    "path": "/api/health",
                    "request_template": {},
                    "expected_status": 200,
                },
                {
                    "service": "svc-b",
                    "method": "POST",
                    "path": "/api/data",
                    "request_template": {"key": "value"},
                    "expected_status": 201,
                },
            ],
        }
        service_urls = {"svc-a": "http://a:8001", "svc-b": "http://b:8002"}

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_mock_response(200, {"id": "abc"})
            return make_mock_response(201, {"result": "ok"})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(side_effect=side_effect)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is True
        assert errors == []

    @pytest.mark.asyncio
    async def test_result_structure_includes_all_fields(self) -> None:
        """V-RUN-1b: run_flow_tests returns IntegrationReport with correct test counts."""
        runner = CrossServiceTestRunner()
        flows = [
            {
                "flow_id": "f1",
                "steps": [
                    {
                        "service": "svc-a",
                        "method": "GET",
                        "path": "/ok",
                        "request_template": {},
                        "expected_status": 200,
                    },
                ],
            },
            {
                "flow_id": "f2",
                "steps": [
                    {
                        "service": "svc-a",
                        "method": "GET",
                        "path": "/ok",
                        "request_template": {},
                        "expected_status": 200,
                    },
                ],
            },
        ]
        service_urls = {"svc-a": "http://a"}

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(return_value=make_mock_response(200, {}))
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            report = await runner.run_flow_tests(flows, service_urls)

        assert isinstance(report, IntegrationReport)
        assert report.integration_tests_total == 2
        assert report.integration_tests_passed == 2
        assert report.overall_health == "passed"


class TestRunSingleFlowFailure:
    """Verify run_single_flow failure case reports at correct step."""

    @pytest.mark.asyncio
    async def test_status_mismatch_at_step_reports_correct_step(self) -> None:
        """V-RUN-2a: Status mismatch error message includes step index."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_fail",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "GET",
                    "path": "/ok",
                    "request_template": {},
                    "expected_status": 200,
                },
                {
                    "service": "svc-b",
                    "method": "POST",
                    "path": "/fail",
                    "request_template": {"data": "x"},
                    "expected_status": 201,
                },
            ],
        }
        service_urls = {"svc-a": "http://a", "svc-b": "http://b"}

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_mock_response(200, {"id": "abc"})
            return make_mock_response(500, {"error": "boom"})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(side_effect=side_effect)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is False
        assert len(errors) >= 1
        assert "step 1" in errors[0]

    @pytest.mark.asyncio
    async def test_missing_service_url_reports_error(self) -> None:
        """V-RUN-2b: Missing service URL produces error at correct step."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_no_url",
            "steps": [
                {
                    "service": "missing-svc",
                    "method": "GET",
                    "path": "/data",
                    "request_template": {},
                    "expected_status": 200,
                },
            ],
        }

        success, errors = await runner.run_single_flow(flow, {})

        assert success is False
        assert "not found" in errors[0]


class TestDataPropagation:
    """Verify response from step N is available to step N+1."""

    @pytest.mark.asyncio
    async def test_step_response_available_as_template_variable(self) -> None:
        """V-RUN-3a: {step_0_response.user_id} is resolved from step 0 response."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_chain",
            "steps": [
                {
                    "service": "user-svc",
                    "method": "POST",
                    "path": "/api/users",
                    "request_template": {"name": "alice"},
                    "expected_status": 201,
                },
                {
                    "service": "order-svc",
                    "method": "POST",
                    "path": "/api/orders",
                    "request_template": {
                        "user_id": "{step_0_response.user_id}",
                    },
                    "expected_status": 201,
                },
            ],
        }
        service_urls = {"user-svc": "http://u", "order-svc": "http://o"}

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_mock_response(201, {"user_id": "usr-999", "name": "alice"})
            return make_mock_response(201, {"order_id": "ord-001"})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(side_effect=side_effect)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is True
        # Verify the second request used the resolved user_id
        second_call = mc.request.call_args_list[1]
        assert second_call.kwargs.get("json", {}).get("user_id") == "usr-999"

    @pytest.mark.asyncio
    async def test_numeric_type_preserved_through_propagation(self) -> None:
        """V-RUN-3b: Numeric values stay numeric after template resolution."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_numeric",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "GET",
                    "path": "/data",
                    "request_template": {},
                    "expected_status": 200,
                },
                {
                    "service": "svc-b",
                    "method": "POST",
                    "path": "/process",
                    "request_template": {"count": "{step_0_response.count}"},
                    "expected_status": 200,
                },
            ],
        }
        service_urls = {"svc-a": "http://a", "svc-b": "http://b"}

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_mock_response(200, {"count": 42})
            return make_mock_response(200, {"result": "ok"})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(side_effect=side_effect)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is True
        second_call = mc.request.call_args_list[1]
        resolved = second_call.kwargs.get("json", {})
        assert resolved["count"] == 42
        assert isinstance(resolved["count"], int)


# ===========================================================================
# SECTION 5: BoundaryTester
# ===========================================================================


class TestBoundaryCaseSensitivity:
    """Verify case sensitivity detection works."""

    @pytest.mark.asyncio
    async def test_same_status_no_violation(self) -> None:
        """V-BND-1a: Same status for both formats -> no violations."""
        tester = BoundaryTester()
        mock_resp = make_mock_response(200, {"ok": True})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.post = AsyncMock(return_value=mock_resp)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            violations = await tester.test_case_sensitivity(
                service_name="test-svc",
                endpoint="/api/items",
                camel_body={"myField": "val"},
                snake_body={"my_field": "val"},
                service_url="http://localhost:8001",
            )

        assert violations == []

    @pytest.mark.asyncio
    async def test_one_crashes_other_ok_produces_error(self) -> None:
        """V-BND-1b: 500 on one format only -> BOUNDARY-CASE-001 error."""
        tester = BoundaryTester()
        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_mock_response(200, {})
            return make_mock_response(500, {})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.post = AsyncMock(side_effect=side_effect)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            violations = await tester.test_case_sensitivity(
                service_name="test-svc",
                endpoint="/api/items",
                camel_body={"myField": "val"},
                snake_body={"my_field": "val"},
                service_url="http://localhost:8001",
            )

        assert len(violations) >= 1
        error_violations = [v for v in violations if v.severity == "error"]
        assert len(error_violations) >= 1
        assert error_violations[0].code == "BOUNDARY-CASE-001"


class TestBoundaryNullHandling:
    """Verify null vs missing field distinction works."""

    @pytest.mark.asyncio
    async def test_500_on_null_or_missing_produces_violation(self) -> None:
        """V-BND-2a: 500 on null/missing/empty -> BOUNDARY-NULL-001 violations."""
        tester = BoundaryTester()
        mock_resp = make_mock_response(500, {"error": "crash"})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.post = AsyncMock(return_value=mock_resp)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            violations = await tester.test_null_handling(
                service_name="test-svc",
                endpoint="/api/items",
                service_url="http://localhost:8001",
                test_data={"name": "test_value"},
            )

        # Should have at least 3 violations: null, missing, empty string
        assert len(violations) == 3
        assert all(v.code == "BOUNDARY-NULL-001" for v in violations)
        # Check distinct variant labels
        messages = [v.message for v in violations]
        assert any("null" in m for m in messages)
        assert any("missing" in m for m in messages)
        assert any("empty string" in m for m in messages)

    @pytest.mark.asyncio
    async def test_422_on_null_is_proper_no_violation(self) -> None:
        """V-BND-2b: 422 (validation error) on null input -> no violations."""
        tester = BoundaryTester()
        mock_resp = make_mock_response(422, {"detail": "field required"})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.post = AsyncMock(return_value=mock_resp)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            violations = await tester.test_null_handling(
                service_name="test-svc",
                endpoint="/api/items",
                service_url="http://localhost:8001",
                test_data={"name": "test_value"},
            )

        assert violations == []


# ===========================================================================
# SECTION 6: DataFlowTracer
# ===========================================================================


class TestMultiHopTrace:
    """Verify multi-hop trace with x-downstream-services headers."""

    @pytest.mark.asyncio
    async def test_multi_service_returns_n_records(self) -> None:
        """V-DFT-1a: Tracing across 3 services returns 3 records."""
        tracer = DataFlowTracer()
        mock_resp = make_mock_response(200, {"data": "ok"})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(return_value=mock_resp)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            records = await tracer.trace_request(
                service_urls={
                    "svc-a": "http://a:8001",
                    "svc-b": "http://b:8002",
                    "svc-c": "http://c:8003",
                },
                method="POST",
                path="/api/data",
                body={"key": "value"},
            )

        assert len(records) == 3
        assert [r["service"] for r in records] == ["svc-a", "svc-b", "svc-c"]
        # All records share the same trace_id
        trace_ids = {r["trace_id"] for r in records}
        assert len(trace_ids) == 1

    @pytest.mark.asyncio
    async def test_all_records_carry_traceparent_header(self) -> None:
        """V-DFT-1b: Each request includes a traceparent header."""
        tracer = DataFlowTracer()
        captured_headers: list[dict[str, str]] = []

        async def capture(*args: Any, **kwargs: Any) -> MagicMock:
            hdrs = kwargs.get("headers", {})
            captured_headers.append(dict(hdrs))
            return make_mock_response(200, {})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(side_effect=capture)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            await tracer.trace_request(
                service_urls={"svc-a": "http://a", "svc-b": "http://b"},
                method="GET",
                path="/api/check",
            )

        assert len(captured_headers) == 2
        for hdrs in captured_headers:
            assert "traceparent" in hdrs


class TestSingleHopFallback:
    """Verify single-hop fallback returns single-element list."""

    @pytest.mark.asyncio
    async def test_single_service_returns_one_record(self) -> None:
        """V-DFT-2a: Single service in service_urls returns 1 record."""
        tracer = DataFlowTracer()
        mock_resp = make_mock_response(200, {"user_id": "abc"})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(return_value=mock_resp)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            records = await tracer.trace_request(
                service_urls={"svc-a": "http://a:8001"},
                method="GET",
                path="/api/users",
            )

        assert len(records) == 1
        assert records[0]["service"] == "svc-a"
        assert records[0]["status"] == 200


class TestTraceIdFormat:
    """Verify trace IDs are valid UUID4 hex format."""

    @pytest.mark.asyncio
    async def test_trace_id_is_32_hex_chars(self) -> None:
        """V-DFT-3a: trace_id is a 32-character lowercase hex string."""
        tracer = DataFlowTracer()
        mock_resp = make_mock_response(200, {})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(return_value=mock_resp)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            records = await tracer.trace_request(
                service_urls={"svc-a": "http://a"},
                method="GET",
                path="/check",
            )

        trace_id = records[0]["trace_id"]
        assert len(trace_id) == 32
        assert re.fullmatch(r"[0-9a-f]{32}", trace_id) is not None

    def test_generate_trace_id_is_valid_uuid4_hex(self) -> None:
        """V-DFT-3b: _generate_trace_id produces valid UUID4 hex string."""
        trace_id = DataFlowTracer._generate_trace_id()
        assert len(trace_id) == 32
        # Should be parseable as a UUID
        reconstructed = uuid.UUID(trace_id)
        assert reconstructed.version == 4

    @pytest.mark.asyncio
    async def test_traceparent_follows_w3c_format(self) -> None:
        """V-DFT-3c: traceparent header follows 00-{trace_id}-{parent_id}-{flags}."""
        tracer = DataFlowTracer()
        captured_headers: dict[str, str] = {}

        async def capture(*args: Any, **kwargs: Any) -> MagicMock:
            hdrs = kwargs.get("headers", {})
            captured_headers.update(hdrs)
            return make_mock_response(200, {})

        with patch("httpx.AsyncClient") as mock_cls:
            mc = AsyncMock()
            mc.request = AsyncMock(side_effect=capture)
            mc.__aenter__ = AsyncMock(return_value=mc)
            mc.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mc

            records = await tracer.trace_request(
                service_urls={"svc-a": "http://a"},
                method="GET",
                path="/check",
            )

        traceparent = captured_headers["traceparent"]
        trace_id = records[0]["trace_id"]
        assert traceparent == f"00-{trace_id}-0000000000000001-01"


class TestVerifyDataTransformationsCorrect:
    """Verify verify_data_transformations returns empty errors for correct data."""

    @pytest.mark.asyncio
    async def test_correct_type_and_value_returns_no_errors(self) -> None:
        """V-DFT-4a: All fields match expected type and pattern -> empty errors."""
        tracer = DataFlowTracer()
        trace = [
            {"service": "svc-a", "status": 200, "body": {"name": "alice", "age": 30}, "trace_id": "aabb"},
        ]
        transformations = [
            {
                "hop_index": 0,
                "field": "name",
                "expected_type": "str",
                "expected_value_pattern": r"^ali",
            },
            {
                "hop_index": 0,
                "field": "age",
                "expected_type": "int",
                "expected_value_pattern": None,
            },
        ]

        errors = await tracer.verify_data_transformations(trace, transformations)
        assert errors == []

    @pytest.mark.asyncio
    async def test_no_transformations_returns_no_errors(self) -> None:
        """V-DFT-4b: Empty transformation list -> empty errors."""
        tracer = DataFlowTracer()
        trace = [
            {"service": "svc-a", "status": 200, "body": {"x": 1}, "trace_id": "aabb"},
        ]

        errors = await tracer.verify_data_transformations(trace, [])
        assert errors == []


class TestVerifyDataTransformationsWrongType:
    """Verify verify_data_transformations returns specific error for wrong type."""

    @pytest.mark.asyncio
    async def test_wrong_type_returns_type_error_message(self) -> None:
        """V-DFT-5a: Field with wrong type -> error mentioning expected and actual types."""
        tracer = DataFlowTracer()
        trace = [
            {"service": "svc-a", "status": 200, "body": {"count": "not_a_number"}, "trace_id": "aabb"},
        ]
        transformations = [
            {
                "hop_index": 0,
                "field": "count",
                "expected_type": "int",
                "expected_value_pattern": None,
            },
        ]

        errors = await tracer.verify_data_transformations(trace, transformations)
        assert len(errors) == 1
        assert "'int'" in errors[0]
        assert "'str'" in errors[0]

    @pytest.mark.asyncio
    async def test_missing_field_returns_field_not_found_error(self) -> None:
        """V-DFT-5b: Missing field -> error mentioning field name."""
        tracer = DataFlowTracer()
        trace = [
            {"service": "svc-a", "status": 200, "body": {"x": 1}, "trace_id": "aabb"},
        ]
        transformations = [
            {
                "hop_index": 0,
                "field": "nonexistent_field",
                "expected_type": "str",
                "expected_value_pattern": None,
            },
        ]

        errors = await tracer.verify_data_transformations(trace, transformations)
        assert len(errors) == 1
        assert "nonexistent_field" in errors[0]

    @pytest.mark.asyncio
    async def test_hop_index_out_of_range_returns_error(self) -> None:
        """V-DFT-5c: hop_index beyond trace length -> out of range error."""
        tracer = DataFlowTracer()
        trace = [
            {"service": "svc-a", "status": 200, "body": {"x": 1}, "trace_id": "aabb"},
        ]
        transformations = [
            {
                "hop_index": 5,
                "field": "x",
                "expected_type": "",
                "expected_value_pattern": None,
            },
        ]

        errors = await tracer.verify_data_transformations(trace, transformations)
        assert len(errors) == 1
        assert "out of range" in errors[0]

    @pytest.mark.asyncio
    async def test_value_pattern_mismatch_returns_error(self) -> None:
        """V-DFT-5d: Value not matching expected_value_pattern -> pattern error."""
        tracer = DataFlowTracer()
        trace = [
            {"service": "svc-a", "status": 200, "body": {"email": "bad-format"}, "trace_id": "aabb"},
        ]
        transformations = [
            {
                "hop_index": 0,
                "field": "email",
                "expected_type": "str",
                "expected_value_pattern": r"^[^@]+@[^@]+\.[^@]+$",
            },
        ]

        errors = await tracer.verify_data_transformations(trace, transformations)
        assert len(errors) == 1
        assert "does not match pattern" in errors[0]


# ===========================================================================
# SECTION 7: Integration Report
# ===========================================================================


class TestIntegrationReportSections:
    """Verify generate_integration_report produces markdown with required sections."""

    def test_report_contains_all_four_sections(self) -> None:
        """V-RPT-1a: Report contains summary, per-service, violations, recommendations."""
        report = IntegrationReport(
            services_deployed=2,
            services_healthy=2,
            contract_tests_passed=5,
            contract_tests_total=5,
            overall_health="passed",
        )
        output = generate_integration_report(report)

        assert "# Integration Report" in output
        assert "## Per-Service Results" in output
        assert "## Violations" in output
        assert "## Recommendations" in output

    def test_report_includes_test_results_table(self) -> None:
        """V-RPT-1b: Report includes markdown table with test categories."""
        report = IntegrationReport(
            contract_tests_passed=8,
            contract_tests_total=10,
            integration_tests_passed=3,
            integration_tests_total=5,
            data_flow_tests_passed=2,
            data_flow_tests_total=2,
            boundary_tests_passed=4,
            boundary_tests_total=6,
        )
        output = generate_integration_report(report)

        assert "Contract tests" in output
        assert "Integration tests" in output
        assert "Data flow tests" in output
        assert "Boundary tests" in output

    def test_report_with_violations_shows_details(self) -> None:
        """V-RPT-1c: Violations are listed with code, service, endpoint, message."""
        v = ContractViolation(
            code="FLOW-001",
            severity="error",
            service="order-svc",
            endpoint="/api/orders",
            message="Status mismatch",
            expected="201",
            actual="500",
        )
        report = IntegrationReport(
            violations=[v],
            overall_health="failed",
        )
        output = generate_integration_report(report)

        assert "FLOW-001" in output
        assert "order-svc" in output
        assert "/api/orders" in output
        assert "Status mismatch" in output
        assert "[ERROR]" in output


class TestReportManageableOutput:
    """Verify report with 50+ violations produces manageable output."""

    def test_50_violations_does_not_explode(self) -> None:
        """V-RPT-2a: Report with 50 violations produces output under 500 lines."""
        violations = [
            ContractViolation(
                code=f"V-{i:03d}",
                severity="error" if i % 2 == 0 else "warning",
                service=f"svc-{i % 5}",
                endpoint=f"/api/endpoint-{i}",
                message=f"Violation number {i}",
                expected="expected",
                actual="actual",
            )
            for i in range(50)
        ]
        report = IntegrationReport(
            services_deployed=5,
            services_healthy=3,
            violations=violations,
            overall_health="failed",
        )
        output = generate_integration_report(report)
        line_count = output.count("\n")

        # The report should be thorough but manageable.
        # 50 violations with ~7 lines each + headers/summary = ~400 lines.
        # Allow up to 600 lines as a reasonable ceiling.
        assert line_count < 600, (
            f"Report has {line_count} lines for 50 violations -- too verbose"
        )
        # But it should still contain all 50 violations
        assert "Total violations:** 50" in output

    def test_100_violations_still_includes_all(self) -> None:
        """V-RPT-2b: All violations are present in the output even with 100."""
        violations = [
            ContractViolation(
                code=f"X-{i:03d}",
                severity="error",
                service="svc",
                endpoint="/ep",
                message=f"msg {i}",
            )
            for i in range(100)
        ]
        report = IntegrationReport(violations=violations, overall_health="failed")
        output = generate_integration_report(report)

        assert "Total violations:** 100" in output
        # Spot-check a few specific violation codes
        assert "X-000" in output
        assert "X-050" in output
        assert "X-099" in output
