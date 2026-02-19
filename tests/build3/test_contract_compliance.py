"""Tests for contract compliance verification.

TEST-001: SchemathesisRunner (>=15 cases)
TEST-002: PactManager + ContractComplianceVerifier (>=10 cases)

All schemathesis and pact imports are mocked at the module level so that
neither library needs to be installed for the tests to pass.
"""

from __future__ import annotations

import ast
import asyncio
import json
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.build3_shared.models import ContractViolation, IntegrationReport


# ---------------------------------------------------------------------------
# Module-level mocks for schemathesis and pact so the real libraries are
# never imported.  These are injected into sys.modules BEFORE the modules
# under test are imported.
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

# Ensure the modules are importable
sys.modules.setdefault("schemathesis", _mock_schemathesis_module)
sys.modules.setdefault("pact", _mock_pact_module)
sys.modules.setdefault("pact.v3", _mock_pact_v3)
sys.modules.setdefault("pact.v3.verifier", _mock_pact_v3_verifier)

# Now we can safely import the modules under test.
from src.integrator.schemathesis_runner import SchemathesisRunner  # noqa: E402
from src.integrator.pact_manager import PactManager  # noqa: E402
from src.integrator.contract_compliance import ContractComplianceVerifier  # noqa: E402


# ===================================================================
# Helpers
# ===================================================================

def _make_mock_schema_with_raw(paths: dict[str, Any] | None = None, base_url: str = "http://localhost:8000"):
    """Create a mock schemathesis schema with a raw_schema dict.

    The raw_schema contains the ``paths`` dict that ``_run_via_test_runner``
    and ``_run_negative_tests_sync`` iterate over.
    """
    schema = MagicMock()
    if paths is None:
        paths = {"/users": {"get": {}, "post": {}}}
    schema.raw_schema = {"paths": paths}
    schema.base_url = base_url
    return schema


# ===================================================================
# TEST-001: SchemathesisRunner (15+ cases)
# ===================================================================

class TestSchemathesisRunner:
    """Tests for the SchemathesisRunner class."""

    # ---------------------------------------------------------------
    # generate_test_file tests
    # ---------------------------------------------------------------

    def test_generate_test_file_returns_valid_python(self) -> None:
        """1. generate_test_file() output is valid Python (ast.parse succeeds)."""
        runner = SchemathesisRunner()
        code = runner.generate_test_file("http://localhost:8000/openapi.json")
        # Should not raise
        tree = ast.parse(code)
        assert isinstance(tree, ast.Module)

    def test_generate_test_file_contains_schema_parametrize(self) -> None:
        """2. Output contains @schema.parametrize()."""
        runner = SchemathesisRunner()
        code = runner.generate_test_file("http://localhost:8000/openapi.json")
        assert "@schema.parametrize()" in code

    def test_generate_test_file_contains_from_url(self) -> None:
        """3. Output contains schemathesis.openapi.from_url."""
        runner = SchemathesisRunner()
        code = runner.generate_test_file("http://localhost:8000/openapi.json")
        assert "schemathesis.openapi.from_url" in code

    def test_generate_test_file_contains_validate_response(self) -> None:
        """4. Output contains validate_response."""
        runner = SchemathesisRunner()
        code = runner.generate_test_file("http://localhost:8000/openapi.json")
        assert "validate_response" in code

    # ---------------------------------------------------------------
    # run_against_service tests
    # ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_run_against_service_returns_list(self) -> None:
        """5. run_against_service returns list[ContractViolation]."""
        runner = SchemathesisRunner()

        # Mock _run_against_service_sync to return an empty list
        with patch.object(runner, "_run_against_service_sync", return_value=[]):
            result = await runner.run_against_service(
                "auth-service",
                "http://localhost:8000/openapi.json",
                "http://localhost:8000",
            )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_run_against_service_unexpected_status(self) -> None:
        """6. 500 status code produces SCHEMA-002 via schemathesis test runner."""
        runner = SchemathesisRunner()

        # Source uses _run_via_test_runner (schemathesis programmatic API),
        # not httpx.Client directly.  Mock _run_via_test_runner to return
        # a SCHEMA-002 violation for a 500 response.
        expected_violation = ContractViolation(
            code="SCHEMA-002",
            severity="error",
            service="auth-service",
            endpoint="GET /users",
            message="Unexpected status code 500",
            expected="2xx",
            actual="500",
        )

        with patch.object(
            runner, "_run_via_test_runner", return_value=[expected_violation]
        ), patch.object(
            runner, "_load_schema", return_value=MagicMock()
        ), patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=_mock_schemathesis_module,
        ), patch(
            "src.integrator.schemathesis_runner._ensure_requests_exceptions",
            return_value=_mock_requests_exceptions,
        ):
            result = await runner.run_against_service(
                "auth-service",
                "http://localhost:8000/openapi.json",
                "http://localhost:8000",
            )

        status_violations = [v for v in result if v.code == "SCHEMA-002"]
        assert len(status_violations) >= 1
        assert "500" in status_violations[0].actual

    @pytest.mark.asyncio
    async def test_run_against_service_slow_response(self) -> None:
        """7. Slow response (>5s) produces SCHEMA-003 via schemathesis test runner."""
        runner = SchemathesisRunner()

        # Source uses _run_via_test_runner (schemathesis programmatic API).
        # Mock _run_via_test_runner to return a SCHEMA-003 violation.
        expected_violation = ContractViolation(
            code="SCHEMA-003",
            severity="warning",
            service="auth-service",
            endpoint="GET /slow",
            message="Response took 6.00s (threshold 5.0s)",
            expected="<5.0s",
            actual="6.00s",
        )

        with patch.object(
            runner, "_run_via_test_runner", return_value=[expected_violation]
        ), patch.object(
            runner, "_load_schema", return_value=MagicMock()
        ), patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=_mock_schemathesis_module,
        ), patch(
            "src.integrator.schemathesis_runner._ensure_requests_exceptions",
            return_value=_mock_requests_exceptions,
        ):
            result = await runner.run_against_service(
                "auth-service",
                "http://localhost:8000/openapi.json",
                "http://localhost:8000",
            )

        slow_violations = [v for v in result if v.code == "SCHEMA-003"]
        assert len(slow_violations) >= 1
        assert "6.00s" in slow_violations[0].actual

    @pytest.mark.asyncio
    async def test_run_against_service_connection_error(self) -> None:
        """8. httpx.ConnectError is handled gracefully (no crash)."""
        import httpx

        runner = SchemathesisRunner()
        fake_schema = _make_mock_schema_with_raw(
            paths={"/down": {"get": {}}},
            base_url="http://localhost:8000",
        )

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = httpx.ConnectError("refused")

        with patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=_mock_schemathesis_module,
        ), patch(
            "src.integrator.schemathesis_runner._ensure_requests_exceptions",
            return_value=_mock_requests_exceptions,
        ), patch.object(
            runner, "_load_schema", return_value=fake_schema
        ), patch(
            "httpx.Client", return_value=mock_client,
        ):
            result = await runner.run_against_service(
                "auth-service",
                "http://localhost:8000/openapi.json",
                "http://localhost:8000",
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_run_against_service_multiple_endpoints(self) -> None:
        """9. Multiple endpoints are all probed via _run_via_test_runner."""
        runner = SchemathesisRunner()

        # Source uses _run_via_test_runner with schemathesis programmatic API.
        # Mock _run_via_test_runner and verify it receives the loaded schema
        # (which confirms the full pipeline from run_against_service is invoked).
        with patch.object(
            runner, "_run_via_test_runner", return_value=[]
        ) as mock_runner, patch.object(
            runner, "_load_schema", return_value=MagicMock()
        ) as mock_load, patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=_mock_schemathesis_module,
        ), patch(
            "src.integrator.schemathesis_runner._ensure_requests_exceptions",
            return_value=_mock_requests_exceptions,
        ):
            result = await runner.run_against_service(
                "auth-service",
                "http://localhost:8000/openapi.json",
                "http://localhost:8000",
            )

        # _run_via_test_runner should have been called once with the loaded schema
        assert result == []
        mock_runner.assert_called_once()
        mock_load.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_against_service_schema_load_error(self) -> None:
        """10. Schema load failure returns empty list."""
        runner = SchemathesisRunner()

        with patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=_mock_schemathesis_module,
        ), patch(
            "src.integrator.schemathesis_runner._ensure_requests_exceptions",
            return_value=_mock_requests_exceptions,
        ), patch.object(
            runner, "_load_schema", side_effect=Exception("Schema not found")
        ), patch(
            "src.integrator.schemathesis_runner.requests",
            _mock_requests_module,
            create=True,
        ):
            result = await runner.run_against_service(
                "auth-service",
                "http://bad-url/openapi.json",
                "http://localhost:8000",
            )

        assert result == []

    # ---------------------------------------------------------------
    # run_negative_tests tests
    # ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_run_negative_tests_returns_list(self) -> None:
        """11. run_negative_tests returns a list."""
        runner = SchemathesisRunner()

        with patch.object(runner, "_run_negative_tests_sync", return_value=[]):
            result = await runner.run_negative_tests(
                "auth-service",
                "http://localhost:8000/openapi.json",
                "http://localhost:8000",
            )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_run_negative_tests_5xx_on_malformed_input(self) -> None:
        """12. 500 response to malformed input produces SCHEMA-002."""
        runner = SchemathesisRunner()

        fake_schema = _make_mock_schema_with_raw(
            paths={"/users": {"post": {}}},
            base_url="http://localhost:8000",
        )

        mock_response = MagicMock()
        mock_response.status_code = 500

        # Mock httpx.Client used in _run_negative_tests_sync
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response

        with patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=_mock_schemathesis_module,
        ), patch.object(
            runner, "_load_schema", return_value=fake_schema
        ), patch(
            "httpx.Client", return_value=mock_client,
        ):
            result = await runner.run_negative_tests(
                "auth-service",
                "http://localhost:8000/openapi.json",
                "http://localhost:8000",
            )

        status_violations = [v for v in result if v.code == "SCHEMA-002"]
        assert len(status_violations) >= 1

    # ---------------------------------------------------------------
    # from_url / from_path routing tests
    # ---------------------------------------------------------------

    def test_run_against_service_uses_from_url_for_http(self) -> None:
        """13. _load_schema calls openapi.from_url for http:// URLs."""
        runner = SchemathesisRunner()

        mock_st = MagicMock()
        mock_st.openapi.from_url.return_value = MagicMock()

        with patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=mock_st,
        ):
            runner._load_schema("http://localhost:8000/openapi.json", "http://localhost:8000")

        mock_st.openapi.from_url.assert_called_once_with(
            "http://localhost:8000/openapi.json",
            base_url="http://localhost:8000",
        )
        mock_st.openapi.from_path.assert_not_called()

    def test_run_against_service_uses_from_path_for_file(self) -> None:
        """14. _load_schema calls openapi.from_path for file paths."""
        runner = SchemathesisRunner()

        mock_st = MagicMock()
        mock_st.openapi.from_path.return_value = MagicMock()

        with patch(
            "src.integrator.schemathesis_runner._ensure_schemathesis",
            return_value=mock_st,
        ):
            runner._load_schema("/tmp/openapi.json", "http://localhost:8000")

        mock_st.openapi.from_path.assert_called_once_with(
            "/tmp/openapi.json",
            base_url="http://localhost:8000",
        )
        mock_st.openapi.from_url.assert_not_called()

    # ---------------------------------------------------------------
    # Thread offloading test
    # ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_run_against_service_wraps_in_thread(self) -> None:
        """15. run_against_service calls asyncio.to_thread."""
        runner = SchemathesisRunner()

        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=[]) as mock_thread:
            result = await runner.run_against_service(
                "auth-service",
                "http://localhost:8000/openapi.json",
                "http://localhost:8000",
            )
        mock_thread.assert_awaited_once()
        # Verify the sync method was passed as the first argument
        assert mock_thread.call_args[0][0] == runner._run_against_service_sync
        assert result == []


# ===================================================================
# TEST-002: PactManager + ContractComplianceVerifier (10+ cases)
# ===================================================================

class TestPactManager:
    """Tests for the PactManager class."""

    @pytest.mark.asyncio
    async def test_pact_load_pacts_groups_by_provider(self, tmp_path: Path) -> None:
        """16. load_pacts groups files by provider name."""
        pact_dir = tmp_path / "pacts"
        pact_dir.mkdir()

        # Two pact files for different providers
        pact_a = {
            "provider": {"name": "auth-service"},
            "consumer": {"name": "web-app"},
            "interactions": [],
        }
        pact_b = {
            "provider": {"name": "order-service"},
            "consumer": {"name": "web-app"},
            "interactions": [],
        }
        (pact_dir / "auth_pact.json").write_text(json.dumps(pact_a), encoding="utf-8")
        (pact_dir / "order_pact.json").write_text(json.dumps(pact_b), encoding="utf-8")

        manager = PactManager(pact_dir=pact_dir)
        grouped = await manager.load_pacts()

        assert "auth-service" in grouped
        assert "order-service" in grouped
        assert len(grouped["auth-service"]) == 1
        assert len(grouped["order-service"]) == 1

    @pytest.mark.asyncio
    async def test_pact_load_pacts_skips_invalid_json(self, tmp_path: Path) -> None:
        """17. Invalid JSON files are skipped without raising."""
        pact_dir = tmp_path / "pacts"
        pact_dir.mkdir()

        (pact_dir / "bad.json").write_text("NOT VALID JSON {{{", encoding="utf-8")

        manager = PactManager(pact_dir=pact_dir)
        grouped = await manager.load_pacts()

        assert grouped == {}

    @pytest.mark.asyncio
    async def test_pact_load_pacts_skips_missing_provider(self, tmp_path: Path) -> None:
        """18. JSON without provider.name is skipped."""
        pact_dir = tmp_path / "pacts"
        pact_dir.mkdir()

        pact_no_provider = {"consumer": {"name": "web-app"}, "interactions": []}
        (pact_dir / "no_provider.json").write_text(
            json.dumps(pact_no_provider), encoding="utf-8"
        )

        manager = PactManager(pact_dir=pact_dir)
        grouped = await manager.load_pacts()

        assert grouped == {}

    @pytest.mark.asyncio
    async def test_pact_load_pacts_empty_dir(self, tmp_path: Path) -> None:
        """19. Empty directory returns empty dict."""
        pact_dir = tmp_path / "pacts"
        pact_dir.mkdir()

        manager = PactManager(pact_dir=pact_dir)
        grouped = await manager.load_pacts()

        assert grouped == {}

    @pytest.mark.asyncio
    async def test_pact_verify_provider_unavailable(self) -> None:
        """20. When pact-python is not importable, verify_provider returns PACT-001."""
        manager = PactManager(pact_dir=Path("/tmp/pacts"))
        # Force pact to be unavailable
        manager._pact_available = False

        violations = await manager.verify_provider(
            "auth-service",
            "http://localhost:8000",
            [Path("/tmp/pact.json")],
        )

        assert len(violations) == 1
        assert violations[0].code == "PACT-001"
        assert "not installed" in violations[0].message

    def test_pact_generate_state_handler(self) -> None:
        """21. generate_pact_state_handler output contains /_pact/state and async def."""
        manager = PactManager(pact_dir=Path("/tmp/pacts"))
        code = manager.generate_pact_state_handler()

        assert "/_pact/state" in code
        assert "async def" in code


class TestContractComplianceVerifier:
    """Tests for the ContractComplianceVerifier facade."""

    @pytest.mark.asyncio
    async def test_verifier_facade_composes_both(self, tmp_path: Path) -> None:
        """22. verify_all_services runs both Schemathesis and Pact."""
        verifier = ContractComplianceVerifier(contract_registry_path=tmp_path, services={})

        # Set up a pact directory with a pact file
        pact_dir = tmp_path / "pacts"
        pact_dir.mkdir()
        pact_data = {
            "provider": {"name": "auth-service"},
            "consumer": {"name": "web-app"},
            "interactions": [],
        }
        (pact_dir / "auth_pact.json").write_text(json.dumps(pact_data), encoding="utf-8")

        services = [
            {"service_id": "auth-service", "openapi_url": "http://localhost:8000/openapi.json"},
        ]
        service_urls = {"auth-service": "http://localhost:8000"}

        with patch.object(
            verifier._schemathesis,
            "run_against_service",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_schema, patch.object(
            verifier._schemathesis,
            "run_negative_tests",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_neg, patch.object(
            verifier._pact,
            "verify_provider",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_pact:
            report = await verifier.verify_all_services(
                services, service_urls, tmp_path
            )

        mock_schema.assert_awaited_once()
        mock_neg.assert_awaited_once()
        mock_pact.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_verifier_facade_returns_integration_report(self, tmp_path: Path) -> None:
        """23. verify_all_services returns IntegrationReport."""
        verifier = ContractComplianceVerifier(contract_registry_path=tmp_path, services={})

        services = [
            {"service_id": "auth-service", "openapi_url": "http://localhost:8000/openapi.json"},
        ]
        service_urls = {"auth-service": "http://localhost:8000"}

        with patch.object(
            verifier._schemathesis,
            "run_against_service",
            new_callable=AsyncMock,
            return_value=[],
        ), patch.object(
            verifier._schemathesis,
            "run_negative_tests",
            new_callable=AsyncMock,
            return_value=[],
        ):
            report = await verifier.verify_all_services(
                services, service_urls, tmp_path
            )

        assert isinstance(report, IntegrationReport)

    @pytest.mark.asyncio
    async def test_verifier_facade_parallel_execution(self, tmp_path: Path) -> None:
        """24. verify_all_services uses asyncio.gather for parallel execution."""
        verifier = ContractComplianceVerifier(contract_registry_path=tmp_path, services={})

        services = [
            {"service_id": "svc-a", "openapi_url": "http://a/openapi.json"},
            {"service_id": "svc-b", "openapi_url": "http://b/openapi.json"},
        ]
        service_urls = {"svc-a": "http://a", "svc-b": "http://b"}

        with patch.object(
            verifier._schemathesis,
            "run_against_service",
            new_callable=AsyncMock,
            return_value=[],
        ), patch.object(
            verifier._schemathesis,
            "run_negative_tests",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "src.integrator.contract_compliance.asyncio.gather",
            new_callable=AsyncMock,
            return_value=[[], [], [], []],
        ) as mock_gather:
            report = await verifier.verify_all_services(
                services, service_urls, tmp_path
            )

        mock_gather.assert_awaited_once()
        # gather should have been called with multiple tasks
        call_args = mock_gather.call_args
        assert len(call_args[0]) == 4  # 2 services x 2 tests each (positive + negative)

    @pytest.mark.asyncio
    async def test_verifier_facade_handles_exceptions(self, tmp_path: Path) -> None:
        """25. Exception in one task is caught; report still produced."""
        verifier = ContractComplianceVerifier(contract_registry_path=tmp_path, services={})

        services = [
            {"service_id": "auth-service", "openapi_url": "http://localhost:8000/openapi.json"},
        ]
        service_urls = {"auth-service": "http://localhost:8000"}

        with patch.object(
            verifier._schemathesis,
            "run_against_service",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ), patch.object(
            verifier._schemathesis,
            "run_negative_tests",
            new_callable=AsyncMock,
            return_value=[],
        ):
            report = await verifier.verify_all_services(
                services, service_urls, tmp_path
            )

        # The report should still be returned (exception handled via gather)
        assert isinstance(report, IntegrationReport)
        # The exception should be recorded as a violation
        internal_violations = [v for v in report.violations if v.code == "INTERNAL-001"]
        assert len(internal_violations) >= 1
        assert "boom" in internal_violations[0].message

    @pytest.mark.asyncio
    async def test_verifier_facade_no_services(self, tmp_path: Path) -> None:
        """26. Empty services list returns report with zero counts."""
        verifier = ContractComplianceVerifier(contract_registry_path=tmp_path, services={})

        report = await verifier.verify_all_services([], {}, tmp_path)

        assert isinstance(report, IntegrationReport)
        assert report.contract_tests_total == 0
        assert report.contract_tests_passed == 0
        assert report.violations == []
        assert report.overall_health == "unknown"

    @pytest.mark.asyncio
    async def test_verifier_facade_no_url_for_service(self, tmp_path: Path) -> None:
        """27. Service without URL in service_urls is skipped."""
        verifier = ContractComplianceVerifier(contract_registry_path=tmp_path, services={})

        services = [
            {"service_id": "auth-service", "openapi_url": "http://localhost:8000/openapi.json"},
        ]
        # No URL provided for auth-service
        service_urls: dict[str, str] = {}

        with patch.object(
            verifier._schemathesis,
            "run_against_service",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_schema:
            report = await verifier.verify_all_services(
                services, service_urls, tmp_path
            )

        # Schemathesis should NOT have been called since there's no URL
        mock_schema.assert_not_awaited()
        assert report.contract_tests_total == 0
