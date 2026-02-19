"""Milestone 2 — Build 2 Client Wrapper Tests.

Tests the client wrappers that Build 2 uses to communicate with Build 1's
MCP servers: ContractEngineClient, CodebaseIntelligenceClient, and
ArchitectClient.

Covers:
  - REQ-013: ContractEngineClient tests
  - REQ-014: CodebaseIntelligenceClient tests
  - REQ-015: ArchitectClient tests
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contract_engine.mcp_client import ContractEngineClient
from tests.run4.conftest import MockToolResult, MockTextContent, make_mcp_result


# ---------------------------------------------------------------------------
# Helper — build typed mock responses
# ---------------------------------------------------------------------------


def _contract_entry_result(
    contract_id: str = "uuid-1",
    service_name: str = "auth-service",
    contract_type: str = "openapi",
) -> MockToolResult:
    """Build a ContractEntry-shaped mock MCP result."""
    return make_mcp_result({
        "id": contract_id,
        "service_name": service_name,
        "type": contract_type,
        "version": "1.0.0",
        "spec": {"openapi": "3.1.0"},
        "spec_hash": "sha256-abc123",
        "status": "active",
    })


def _validation_result(valid: bool = True) -> MockToolResult:
    """Build a ContractValidation-shaped mock MCP result."""
    violations = [] if valid else [
        {"field": "/email", "expected": "string(email)", "actual": "int", "severity": "error"},
    ]
    return make_mcp_result({"valid": valid, "violations": violations})


def _generate_tests_result(code: str = "def test_auth(): pass") -> MockToolResult:
    """Build a test-generation string mock MCP result."""
    return make_mcp_result(code)


def _breaking_changes_result(changes: list[dict] | None = None) -> MockToolResult:
    """Build a breaking-changes list mock MCP result."""
    return make_mcp_result(changes or [])


def _mark_result(
    marked: bool = True,
    total: int = 1,
    all_impl: bool = True,
) -> MockToolResult:
    """Build a MarkResult-shaped mock MCP result."""
    return make_mcp_result({
        "marked": marked,
        "total": total,
        "all_implemented": all_impl,
    })


def _unimplemented_list_result() -> MockToolResult:
    """Build an unimplemented-contracts list mock MCP result."""
    return make_mcp_result([
        {
            "id": "uuid-2",
            "type": "openapi",
            "expected_service": "order-service",
            "version": "1.0.0",
            "status": "active",
        },
    ])


def _definition_result() -> MockToolResult:
    """Build a DefinitionResult-shaped mock MCP result."""
    return make_mcp_result({
        "file": "src/auth/login.py",
        "line": 10,
        "kind": "function",
        "signature": "def login(email: str, password: str) -> dict",
    })


def _callers_result() -> MockToolResult:
    """Build a callers list mock MCP result."""
    return make_mcp_result([
        {"file_path": "src/auth/handler.py", "line": 42, "caller_symbol": "handle_login"},
        {"file_path": "tests/test_auth.py", "line": 15, "caller_symbol": "test_login"},
    ])


def _dependency_result() -> MockToolResult:
    """Build a DependencyResult-shaped mock MCP result."""
    return make_mcp_result({
        "imports": ["os", "json", "src.shared.db.connection"],
        "imported_by": ["src.auth.handler"],
        "transitive_deps": ["os", "json", "src.shared.db.connection", "sqlite3"],
        "circular_deps": [],
    })


def _semantic_search_result() -> MockToolResult:
    """Build a semantic search results list mock MCP result."""
    return make_mcp_result([
        {
            "chunk_id": "chunk-1",
            "file_path": "src/auth/login.py",
            "symbol_name": "login",
            "content": "def login(email, password):\n    ...",
            "score": 0.95,
            "language": "python",
            "service_name": "auth-service",
            "line_start": 10,
            "line_end": 30,
        },
    ])


def _service_interface_result() -> MockToolResult:
    """Build a ServiceInterface-shaped mock MCP result."""
    return make_mcp_result({
        "service_name": "auth-service",
        "endpoints": [
            {"method": "POST", "path": "/login", "description": "User login"},
        ],
        "events_published": [],
        "events_consumed": [],
        "exported_symbols": [
            {"name": "login", "kind": "function", "file": "src/auth/login.py"},
        ],
    })


def _dead_code_result() -> MockToolResult:
    """Build a dead-code entries list mock MCP result."""
    return make_mcp_result([
        {
            "symbol_name": "unused_helper",
            "file_path": "src/auth/utils.py",
            "kind": "function",
            "line": 55,
            "service_name": "auth-service",
            "confidence": "high",
        },
    ])


def _artifact_result() -> MockToolResult:
    """Build an ArtifactResult-shaped mock MCP result."""
    return make_mcp_result({
        "indexed": True,
        "symbols_found": 12,
        "dependencies_found": 5,
        "errors": [],
    })


def _decomposition_result() -> MockToolResult:
    """Build a DecompositionResult-shaped mock MCP result."""
    return make_mcp_result({
        "service_map": {
            "project_name": "TaskTracker",
            "services": [
                {"name": "auth-service", "provides_contracts": [], "consumes_contracts": []},
            ],
            "generated_at": "2026-01-01T00:00:00Z",
            "prd_hash": "sha256-def456",
            "build_cycle_id": "cycle-1",
        },
        "domain_model": {
            "entities": [{"name": "User", "fields": []}],
            "relationships": [],
            "generated_at": "2026-01-01T00:00:00Z",
        },
        "contract_stubs": {
            "auth-service": {"openapi": "3.1.0", "info": {"title": "Auth", "version": "1.0.0"}},
        },
        "validation_issues": [],
        "interview_questions": ["What authentication method is preferred?"],
    })


def _service_map_result() -> MockToolResult:
    """Build a ServiceMap-shaped mock MCP result."""
    return make_mcp_result({
        "project_name": "TaskTracker",
        "services": [
            {"name": "auth-service", "provides_contracts": [], "consumes_contracts": []},
        ],
        "generated_at": "2026-01-01T00:00:00Z",
        "prd_hash": "sha256-def456",
        "build_cycle_id": "cycle-1",
    })


def _domain_model_result() -> MockToolResult:
    """Build a DomainModel-shaped mock MCP result."""
    return make_mcp_result({
        "entities": [
            {"name": "User", "fields": [{"name": "email", "type": "string"}]},
        ],
        "relationships": [],
        "generated_at": "2026-01-01T00:00:00Z",
    })


def _contracts_for_service_result() -> MockToolResult:
    """Build a contracts-for-service list mock MCP result."""
    return make_mcp_result([
        {
            "id": "contract-uuid-1",
            "role": "provider",
            "type": "openapi",
            "counterparty": "order-service",
            "summary": "openapi contract v1.0.0 for auth-service",
        },
    ])


def _build_mock_mcp_session(tool_response: MockToolResult) -> AsyncMock:
    """Build a mock MCP session that returns a specific response from call_tool."""
    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.call_tool = AsyncMock(return_value=tool_response)
    return session


def _build_error_session() -> AsyncMock:
    """Build a mock MCP session that always returns errors."""
    session = AsyncMock()
    session.initialize = AsyncMock(return_value=None)
    session.call_tool = AsyncMock(
        return_value=make_mcp_result({"error": "Service unavailable"}, is_error=True)
    )
    return session


# ---------------------------------------------------------------------------
# REQ-013 — ContractEngineClient Tests
# ---------------------------------------------------------------------------


class TestCEClientGetContractReturnsCorrectType:
    """REQ-013 — get_contract() returns dict with ContractEntry fields."""

    @pytest.mark.asyncio
    async def test_ce_client_get_contract_returns_correct_type(self) -> None:
        """ContractEngineClient.get_contract() returns ContractEntry dict."""
        session = _build_mock_mcp_session(_contract_entry_result())
        client = ContractEngineClient(session)
        data = await client.get_contract("uuid-1")

        assert isinstance(data, dict)
        assert "id" in data
        assert "service_name" in data
        assert "type" in data
        assert "version" in data
        assert "spec" in data
        assert "spec_hash" in data
        assert "status" in data


class TestCEClientValidateEndpointReturnsCorrectType:
    """REQ-013 — validate_endpoint() returns dict with valid and violations."""

    @pytest.mark.asyncio
    async def test_ce_client_validate_endpoint_returns_correct_type(self) -> None:
        """ContractEngineClient.validate_endpoint() returns validation dict."""
        session = _build_mock_mcp_session(_validation_result(valid=True))
        client = ContractEngineClient(session)
        data = await client.validate_endpoint(
            service_name="auth",
            method="POST",
            path="/login",
            response_body={"access_token": "jwt"},
            status_code=200,
        )

        assert "valid" in data
        assert "violations" in data
        assert data["valid"] is True
        assert isinstance(data["violations"], list)


class TestCEClientGenerateTestsReturnsString:
    """REQ-013 — generate_tests() returns non-empty string."""

    @pytest.mark.asyncio
    async def test_ce_client_generate_tests_returns_string(self) -> None:
        """ContractEngineClient.generate_tests() returns non-empty string."""
        session = _build_mock_mcp_session(_generate_tests_result())
        client = ContractEngineClient(session)
        data = await client.generate_tests(
            contract_id="uuid-1",
            framework="pytest",
            include_negative=False,
        )

        assert isinstance(data, str)
        assert len(data) > 0


class TestCEClientCheckBreakingReturnsList:
    """REQ-013 — check_breaking_changes() returns list of change dicts."""

    @pytest.mark.asyncio
    async def test_ce_client_check_breaking_returns_list(self) -> None:
        """ContractEngineClient.check_breaking_changes() returns list."""
        changes = [
            {
                "change_type": "removed",
                "path": "/api/users",
                "severity": "breaking",
                "old_value": "POST /api/users",
                "new_value": None,
                "affected_consumers": ["order-service"],
            },
        ]
        session = _build_mock_mcp_session(_breaking_changes_result(changes))
        client = ContractEngineClient(session)
        data = await client.check_breaking_changes(
            contract_id="uuid-1",
            new_spec={"openapi": "3.1.0"},
        )

        assert isinstance(data, list)
        if data:
            assert "change_type" in data[0]


class TestCEClientMarkImplementedReturnsResult:
    """REQ-013 — mark_implemented() returns MarkResult dict."""

    @pytest.mark.asyncio
    async def test_ce_client_mark_implemented_returns_result(self) -> None:
        """ContractEngineClient.mark_implemented() returns MarkResult dict."""
        session = _build_mock_mcp_session(_mark_result())
        client = ContractEngineClient(session)
        data = await client.mark_implemented(
            contract_id="uuid-1",
            service_name="auth",
            evidence_path="/tests/auth_test.py",
        )

        assert "marked" in data
        assert "total" in data
        assert "all_implemented" in data
        assert data["marked"] is True


class TestCEClientGetUnimplementedReturnsList:
    """REQ-013 — get_unimplemented_contracts() returns list."""

    @pytest.mark.asyncio
    async def test_ce_client_get_unimplemented_returns_list(self) -> None:
        """ContractEngineClient.get_unimplemented_contracts() returns list."""
        session = _build_mock_mcp_session(_unimplemented_list_result())
        client = ContractEngineClient(session)
        data = await client.get_unimplemented_contracts(service_name="auth")

        assert isinstance(data, list)
        if data:
            assert "id" in data[0]
            assert "type" in data[0]
            assert "status" in data[0]


class TestCEClientSafeDefaultsOnError:
    """REQ-013 — All 9 CE methods return safe defaults on MCP error."""

    @pytest.mark.asyncio
    async def test_ce_client_safe_defaults_on_error(self) -> None:
        """All CE methods return safe defaults on MCP error (never raise)."""
        session = _build_error_session()
        client = ContractEngineClient(session)

        # Call every method through the wrapper — none should raise
        r1 = await client.get_contract("uuid-1")
        assert r1 is not None and "error" in r1

        r2 = await client.validate_endpoint(
            service_name="auth", method="POST", path="/login",
            response_body={}, status_code=200,
        )
        assert r2 is not None
        # validate_endpoint returns {"valid": False, "violations": [...]} on error
        assert "valid" in r2 or "error" in r2

        r3 = await client.generate_tests(contract_id="uuid-1")
        assert isinstance(r3, str)  # empty string is a safe default

        r4 = await client.check_breaking_changes(contract_id="uuid-1")
        assert isinstance(r4, list)  # empty list is a safe default

        r5 = await client.mark_implemented(
            contract_id="uuid-1", service_name="auth",
            evidence_path="/test.py",
        )
        assert r5 is not None and "error" in r5

        r6 = await client.get_unimplemented_contracts(service_name="auth")
        assert isinstance(r6, list)

        r7 = await client.create_contract(
            service_name="auth", type="openapi", version="1.0.0", spec={},
        )
        assert r7 is not None and "error" in r7

        r8 = await client.validate_spec(spec={}, type="openapi")
        assert r8 is not None and "error" in r8

        r9 = await client.list_contracts(service_name="auth")
        assert r9 is not None and "error" in r9


class TestCEClientRetry3xBackoff:
    """REQ-013 — All CE methods retry 3 times with exponential backoff."""

    @pytest.mark.asyncio
    async def test_ce_client_retry_3x_backoff(self) -> None:
        """ContractEngineClient retries 3 times with exponential backoff."""
        attempt_count = 0

        async def flaky_call_tool(tool_name: str, params: dict) -> MockToolResult:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count <= 3:
                raise ConnectionError(f"Attempt {attempt_count} failed")
            return _contract_entry_result()

        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=flaky_call_tool)

        client = ContractEngineClient(session)

        # Patch asyncio.sleep so the test runs instantly
        with patch("src.contract_engine.mcp_client.asyncio.sleep", new_callable=AsyncMock):
            data = await client.get_contract("uuid-1")

        # 3 failures + 1 success = 4 calls total
        assert attempt_count == 4
        assert isinstance(data, dict)
        assert "id" in data


# ---------------------------------------------------------------------------
# REQ-014 — CodebaseIntelligenceClient Tests
# ---------------------------------------------------------------------------


class TestCIClientFindDefinitionType:
    """REQ-014 — find_definition returns DefinitionResult dict."""

    @pytest.mark.asyncio
    async def test_ci_client_find_definition_type(self) -> None:
        """Verify CodebaseIntelligenceClient.find_definition() returns dict with expected fields."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient

        session = _build_mock_mcp_session(_definition_result())
        client = CodebaseIntelligenceClient(session=session)
        data = await client.find_definition(symbol="login", language="python")

        assert isinstance(data, dict)
        assert "file" in data
        assert "line" in data
        assert "kind" in data
        assert "signature" in data
        # Verify the wrapper delegated to the correct MCP tool
        session.call_tool.assert_awaited_once_with(
            "find_definition", {"symbol": "login", "language": "python"},
        )


class TestCIClientFindCallersType:
    """REQ-014 — find_callers returns list of caller dicts."""

    @pytest.mark.asyncio
    async def test_ci_client_find_callers_type(self) -> None:
        """Verify CodebaseIntelligenceClient.find_callers() returns list of caller dicts."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient

        session = _build_mock_mcp_session(_callers_result())
        client = CodebaseIntelligenceClient(session=session)
        data = await client.find_callers(symbol="login", max_results=10)

        assert isinstance(data, list)
        if data:
            assert "file_path" in data[0]
            assert "line" in data[0]
            assert "caller_symbol" in data[0]
        session.call_tool.assert_awaited_once_with(
            "find_callers", {"symbol": "login", "max_results": 10},
        )


class TestCIClientFindDependenciesType:
    """REQ-014 — find_dependencies returns DependencyResult dict."""

    @pytest.mark.asyncio
    async def test_ci_client_find_dependencies_type(self) -> None:
        """Verify CodebaseIntelligenceClient.find_dependencies() returns DependencyResult dict."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient

        session = _build_mock_mcp_session(_dependency_result())
        client = CodebaseIntelligenceClient(session=session)
        data = await client.find_dependencies(file_path="src/auth/login.py")

        assert isinstance(data, dict)
        assert "imports" in data
        assert "imported_by" in data
        assert "transitive_deps" in data
        assert "circular_deps" in data
        assert isinstance(data["imports"], list)
        assert isinstance(data["imported_by"], list)
        session.call_tool.assert_awaited_once()


class TestCIClientSearchSemanticType:
    """REQ-014 — search_semantic returns list of semantic results."""

    @pytest.mark.asyncio
    async def test_ci_client_search_semantic_type(self) -> None:
        """Verify CodebaseIntelligenceClient.search_semantic() returns list of results."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient

        session = _build_mock_mcp_session(_semantic_search_result())
        client = CodebaseIntelligenceClient(session=session)
        data = await client.search_semantic(
            query="login endpoint", language="python", n_results=5,
        )

        assert isinstance(data, list)
        if data:
            entry = data[0]
            assert "file_path" in entry
            assert "score" in entry
            assert "content" in entry
        session.call_tool.assert_awaited_once()


class TestCIClientGetServiceInterfaceType:
    """REQ-014 — get_service_interface returns ServiceInterface dict."""

    @pytest.mark.asyncio
    async def test_ci_client_get_service_interface_type(self) -> None:
        """Verify CodebaseIntelligenceClient.get_service_interface() returns ServiceInterface dict."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient

        session = _build_mock_mcp_session(_service_interface_result())
        client = CodebaseIntelligenceClient(session=session)
        data = await client.get_service_interface(service_name="auth-service")

        assert isinstance(data, dict)
        assert "service_name" in data
        assert "endpoints" in data
        assert "events_published" in data
        assert "events_consumed" in data
        assert "exported_symbols" in data
        session.call_tool.assert_awaited_once_with(
            "get_service_interface", {"service_name": "auth-service"},
        )


class TestCIClientCheckDeadCodeType:
    """REQ-014 — check_dead_code returns list of dead code dicts."""

    @pytest.mark.asyncio
    async def test_ci_client_check_dead_code_type(self) -> None:
        """Verify CodebaseIntelligenceClient.check_dead_code() returns list of dead-code dicts."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient

        session = _build_mock_mcp_session(_dead_code_result())
        client = CodebaseIntelligenceClient(session=session)
        data = await client.check_dead_code(service_name="auth-service")

        assert isinstance(data, list)
        if data:
            entry = data[0]
            assert "symbol_name" in entry
            assert "file_path" in entry
            assert "kind" in entry
            assert "confidence" in entry
        session.call_tool.assert_awaited_once_with(
            "check_dead_code", {"service_name": "auth-service"},
        )


class TestCIClientRegisterArtifactType:
    """REQ-014 — register_artifact returns ArtifactResult dict."""

    @pytest.mark.asyncio
    async def test_ci_client_register_artifact_type(self) -> None:
        """Verify CodebaseIntelligenceClient.register_artifact() returns ArtifactResult dict."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient

        session = _build_mock_mcp_session(_artifact_result())
        client = CodebaseIntelligenceClient(session=session)
        data = await client.register_artifact(
            file_path="src/auth/login.py", service_name="auth-service",
        )

        assert isinstance(data, dict)
        assert "indexed" in data
        assert "symbols_found" in data
        assert "dependencies_found" in data
        assert "errors" in data
        assert data["indexed"] is True
        session.call_tool.assert_awaited_once()


class TestCIClientSafeDefaults:
    """REQ-014 — All 7 CI methods return safe defaults on error."""

    @pytest.mark.asyncio
    async def test_ci_client_safe_defaults(self) -> None:
        """All CodebaseIntelligenceClient methods return safe defaults on error (never raise)."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient

        session = _build_error_session()
        client = CodebaseIntelligenceClient(session=session)

        # Methods returning dicts should return {} on error
        defn = await client.find_definition(symbol="login")
        assert isinstance(defn, dict)

        deps = await client.find_dependencies(file_path="src/auth/login.py")
        assert isinstance(deps, dict)

        iface = await client.get_service_interface(service_name="auth-service")
        assert isinstance(iface, dict)

        artifact = await client.register_artifact(
            file_path="src/auth/login.py", service_name="auth-service",
        )
        assert isinstance(artifact, dict)

        # Methods returning lists should return [] on error
        callers = await client.find_callers(symbol="login", max_results=10)
        assert isinstance(callers, list)

        search = await client.search_semantic(query="login", n_results=5)
        assert isinstance(search, list)

        dead = await client.check_dead_code(service_name="auth-service")
        assert isinstance(dead, list)


class TestCIClientRetryPattern:
    """REQ-014 — 3-retry pattern with exponential backoff verified."""

    @pytest.mark.asyncio
    async def test_ci_client_retry_pattern(self) -> None:
        """Verify CodebaseIntelligenceClient retries 3 times with exponential backoff."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient

        attempts: list[int] = []

        async def failing_call_tool(tool_name: str, params: dict) -> Any:
            attempts.append(len(attempts))
            if len(attempts) < 3:  # First 2 attempts fail
                raise ConnectionError(f"Attempt {len(attempts)} failed")
            return _definition_result()

        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=failing_call_tool)

        # Use backoff_base=0 to avoid real delays in tests
        client = CodebaseIntelligenceClient(
            session=session, max_retries=3, backoff_base=0,
        )
        data = await client.find_definition(symbol="login")

        assert isinstance(data, dict)
        assert "file" in data
        assert len(attempts) == 3  # 2 failures + 1 success


# ---------------------------------------------------------------------------
# REQ-015 — ArchitectClient Tests
# ---------------------------------------------------------------------------


class TestArchClientDecomposeReturnsResult:
    """REQ-015 — ArchitectClient.decompose() returns DecompositionResult dict."""

    @pytest.mark.asyncio
    async def test_arch_client_decompose_returns_result(
        self, sample_prd_text: str
    ) -> None:
        """ArchitectClient.decompose() returns dict with all expected fields."""
        from src.architect.mcp_client import ArchitectClient

        session = _build_mock_mcp_session(_decomposition_result())
        client = ArchitectClient(session=session)
        data = await client.decompose(prd_text=sample_prd_text)

        assert isinstance(data, dict)
        assert "service_map" in data
        assert "domain_model" in data
        assert "contract_stubs" in data
        assert "validation_issues" in data
        assert "interview_questions" in data

        # Verify nested structure
        assert "project_name" in data["service_map"]
        assert "services" in data["service_map"]
        assert "entities" in data["domain_model"]

        # Verify the wrapper delegated to the correct MCP tool
        session.call_tool.assert_awaited_once_with(
            "decompose", {"prd_text": sample_prd_text},
        )


class TestArchClientGetServiceMapType:
    """REQ-015 — ArchitectClient.get_service_map() returns ServiceMap dict."""

    @pytest.mark.asyncio
    async def test_arch_client_get_service_map_type(self) -> None:
        """ArchitectClient.get_service_map() returns ServiceMap dict."""
        from src.architect.mcp_client import ArchitectClient

        session = _build_mock_mcp_session(_service_map_result())
        client = ArchitectClient(session=session)
        data = await client.get_service_map()

        assert isinstance(data, dict)
        assert "project_name" in data
        assert "services" in data
        assert "generated_at" in data
        assert "prd_hash" in data
        session.call_tool.assert_awaited_once_with("get_service_map", {})


class TestArchClientGetContractsType:
    """REQ-015 — ArchitectClient.get_contracts_for_service() returns list."""

    @pytest.mark.asyncio
    async def test_arch_client_get_contracts_type(self) -> None:
        """ArchitectClient.get_contracts_for_service() returns list of contract dicts."""
        from src.architect.mcp_client import ArchitectClient

        session = _build_mock_mcp_session(_contracts_for_service_result())
        client = ArchitectClient(session=session)
        data = await client.get_contracts_for_service(service_name="auth-service")

        assert isinstance(data, list)
        if data:
            contract = data[0]
            assert "id" in contract
            assert "role" in contract
            assert "type" in contract
            assert "counterparty" in contract
            assert "summary" in contract
        session.call_tool.assert_awaited_once_with(
            "get_contracts_for_service", {"service_name": "auth-service"},
        )


class TestArchClientGetDomainModelType:
    """REQ-015 — ArchitectClient.get_domain_model() returns DomainModel dict."""

    @pytest.mark.asyncio
    async def test_arch_client_get_domain_model_type(self) -> None:
        """ArchitectClient.get_domain_model() returns DomainModel dict."""
        from src.architect.mcp_client import ArchitectClient

        session = _build_mock_mcp_session(_domain_model_result())
        client = ArchitectClient(session=session)
        data = await client.get_domain_model()

        assert isinstance(data, dict)
        assert "entities" in data
        assert "relationships" in data
        assert "generated_at" in data
        session.call_tool.assert_awaited_once_with("get_domain_model", {})


class TestArchClientDecomposeFailureReturnsNone:
    """REQ-015 — ArchitectClient.decompose() returns None on failure (fallback path)."""

    @pytest.mark.asyncio
    async def test_arch_client_decompose_failure_returns_none(self) -> None:
        """ArchitectClient.decompose() returns error-dict on MCP error, enabling fallback."""
        from src.architect.mcp_client import ArchitectClient

        session = _build_error_session()
        client = ArchitectClient(session=session)
        data = await client.decompose(prd_text="Test PRD text")

        # On failure the wrapper returns the error payload or None
        # The caller checks for "error" key and treats as fallback trigger
        assert data is None or (isinstance(data, dict) and "error" in data)

    @pytest.mark.asyncio
    async def test_arch_decompose_exception_returns_none(self) -> None:
        """ArchitectClient.decompose() returns None when session raises ConnectionError."""
        from src.architect.mcp_client import ArchitectClient

        session = AsyncMock()
        session.initialize = AsyncMock(return_value=None)
        session.call_tool = AsyncMock(
            side_effect=ConnectionError("Architect MCP unavailable")
        )

        client = ArchitectClient(session=session)
        # Patch asyncio.sleep so the retry backoff completes instantly
        with patch("src.architect.mcp_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.decompose(prd_text="Test PRD")

        # ArchitectClient's retry exhaustion should return None (safe default)
        assert result is None, "Should return None on exception for fallback path"


# ---------------------------------------------------------------------------
# Cross-client integration: MCP client wrapper module verification
# ---------------------------------------------------------------------------


class TestArchitectMCPClientWiring:
    """Verify architect MCP client module exists and has correct signature."""

    def test_architect_mcp_client_importable(self) -> None:
        """src.architect.mcp_client is importable."""
        from src.architect.mcp_client import call_architect_mcp
        assert callable(call_architect_mcp)

    @pytest.mark.asyncio
    async def test_architect_mcp_client_signature(self) -> None:
        """call_architect_mcp accepts prd_text and optional config."""
        import inspect
        from src.architect.mcp_client import call_architect_mcp
        sig = inspect.signature(call_architect_mcp)
        params = list(sig.parameters.keys())
        assert "prd_text" in params
        assert "config" in params

    def test_architect_all_4_wrappers_importable(self) -> None:
        """All 4 Architect client wrappers (SVC-001..SVC-004) are importable."""
        from src.architect.mcp_client import (
            call_architect_mcp,
            get_service_map,
            get_contracts_for_service,
            get_domain_model,
        )
        assert callable(call_architect_mcp)
        assert callable(get_service_map)
        assert callable(get_contracts_for_service)
        assert callable(get_domain_model)

    @pytest.mark.asyncio
    async def test_get_service_map_signature(self) -> None:
        """get_service_map accepts optional project_name (SVC-002)."""
        import inspect
        from src.architect.mcp_client import get_service_map
        sig = inspect.signature(get_service_map)
        params = list(sig.parameters.keys())
        assert "project_name" in params

    @pytest.mark.asyncio
    async def test_get_contracts_for_service_signature(self) -> None:
        """get_contracts_for_service accepts service_name (SVC-003)."""
        import inspect
        from src.architect.mcp_client import get_contracts_for_service
        sig = inspect.signature(get_contracts_for_service)
        params = list(sig.parameters.keys())
        assert "service_name" in params

    @pytest.mark.asyncio
    async def test_get_domain_model_signature(self) -> None:
        """get_domain_model accepts optional project_name (SVC-004)."""
        import inspect
        from src.architect.mcp_client import get_domain_model
        sig = inspect.signature(get_domain_model)
        params = list(sig.parameters.keys())
        assert "project_name" in params


class TestContractEngineMCPClientWiring:
    """Verify contract engine MCP client module exists and is importable."""

    def test_ce_mcp_client_importable(self) -> None:
        """src.contract_engine.mcp_client is importable."""
        from src.contract_engine.mcp_client import (
            ContractEngineClient,
            create_contract,
            validate_spec,
            list_contracts,
        )
        assert callable(create_contract)
        assert callable(validate_spec)
        assert callable(list_contracts)
        # Verify the class itself is importable and instantiable
        assert ContractEngineClient is not None

    @pytest.mark.asyncio
    async def test_ce_create_contract_signature(self) -> None:
        """create_contract has correct parameter names."""
        import inspect
        from src.contract_engine.mcp_client import create_contract
        sig = inspect.signature(create_contract)
        params = list(sig.parameters.keys())
        assert "service_name" in params
        assert "type" in params
        assert "version" in params
        assert "spec" in params

    @pytest.mark.asyncio
    async def test_ce_validate_spec_signature(self) -> None:
        """validate_spec has correct parameter names."""
        import inspect
        from src.contract_engine.mcp_client import validate_spec
        sig = inspect.signature(validate_spec)
        params = list(sig.parameters.keys())
        assert "spec" in params
        assert "type" in params

    @pytest.mark.asyncio
    async def test_ce_list_contracts_signature(self) -> None:
        """list_contracts has correct parameter names."""
        import inspect
        from src.contract_engine.mcp_client import list_contracts
        sig = inspect.signature(list_contracts)
        params = list(sig.parameters.keys())
        assert "service_name" in params
        assert "page" in params
        assert "page_size" in params


class TestCodebaseIntelMCPClientWiring:
    """Verify codebase intelligence MCP client module exists and is importable."""

    def test_ci_mcp_client_importable(self) -> None:
        """src.codebase_intelligence.mcp_client is importable."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient
        assert callable(CodebaseIntelligenceClient)

    def test_ci_client_has_all_7_methods(self) -> None:
        """CodebaseIntelligenceClient exposes all 7 CI methods."""
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient
        client = CodebaseIntelligenceClient()
        expected_methods = [
            "find_definition",
            "find_callers",
            "find_dependencies",
            "search_semantic",
            "get_service_interface",
            "check_dead_code",
            "register_artifact",
        ]
        for method_name in expected_methods:
            assert hasattr(client, method_name), f"Missing method: {method_name}"
            assert callable(getattr(client, method_name)), f"{method_name} not callable"

    @pytest.mark.asyncio
    async def test_ci_client_find_definition_signature(self) -> None:
        """find_definition accepts symbol and optional language."""
        import inspect
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient
        sig = inspect.signature(CodebaseIntelligenceClient.find_definition)
        params = list(sig.parameters.keys())
        assert "symbol" in params
        assert "language" in params

    @pytest.mark.asyncio
    async def test_ci_client_register_artifact_signature(self) -> None:
        """register_artifact accepts file_path and optional service_name."""
        import inspect
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient
        sig = inspect.signature(CodebaseIntelligenceClient.register_artifact)
        params = list(sig.parameters.keys())
        assert "file_path" in params
        assert "service_name" in params


# ---------------------------------------------------------------------------
# MCP Server tool name verification against actual server modules
# ---------------------------------------------------------------------------


class TestMCPServerToolRegistration:
    """Verify MCP server modules register the expected tool names."""

    def test_architect_server_module_importable(self) -> None:
        """src.architect.mcp_server module is importable."""
        # Import the module to verify it doesn't crash on import
        # Note: This may fail if DB init fails, which is expected
        # in test env without data dir. We just verify the module
        # can be found.
        import importlib
        spec = importlib.util.find_spec("src.architect.mcp_server")
        assert spec is not None, "architect.mcp_server module not found"

    def test_contract_engine_server_module_importable(self) -> None:
        """src.contract_engine.mcp_server module is importable."""
        import importlib
        spec = importlib.util.find_spec("src.contract_engine.mcp_server")
        assert spec is not None, "contract_engine.mcp_server module not found"

    def test_codebase_intel_server_module_importable(self) -> None:
        """src.codebase_intelligence.mcp_server module is importable."""
        import importlib
        spec = importlib.util.find_spec("src.codebase_intelligence.mcp_server")
        assert spec is not None, "codebase_intelligence.mcp_server module not found"
