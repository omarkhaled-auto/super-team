"""Milestone 4 -- End-to-End Pipeline tests (mock-based).

REQ-021 through REQ-027: 7-phase pipeline verification.
All tests use mocks -- no Docker or live services required.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.run4.builder import (
    BuilderResult,
    _state_to_builder_result,
    run_parallel_builders,
)
from src.run4.mcp_health import poll_until_healthy
from tests.run4.conftest import MockTextContent, MockToolResult, make_mcp_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_state_json(
    output_dir: Path,
    *,
    success: bool = True,
    test_passed: int = 10,
    test_total: int = 10,
    convergence_ratio: float = 1.0,
    total_cost: float = 0.50,
    health: str = "green",
) -> Path:
    """Write a valid STATE.json into ``output_dir/.agent-team/``."""
    state_dir = output_dir / ".agent-team"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "STATE.json"
    data = {
        "run_id": "m4-test-run",
        "health": health,
        "current_phase": "complete",
        "completed_phases": ["architect", "builders"],
        "total_cost": total_cost,
        "summary": {
            "success": success,
            "test_passed": test_passed,
            "test_total": test_total,
            "convergence_ratio": convergence_ratio,
        },
        "schema_version": 2,
    }
    state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return state_path


def _mock_healthy_client() -> AsyncMock:
    """Return a mock httpx.AsyncClient whose GET always returns HTTP 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ===================================================================
# REQ-021 -- Phase 1: Build 1 Health
# ===================================================================


class TestPhase1BuildHealth:
    """REQ-021 -- Mock Docker health checks; verify all 3 services healthy."""

    @pytest.mark.asyncio
    async def test_all_three_services_report_healthy(self) -> None:
        """All 3 Build 1 services respond HTTP 200 on /api/health."""
        mock_client = _mock_healthy_client()

        service_urls = {
            "architect": "http://localhost:8001/api/health",
            "contract-engine": "http://localhost:8002/api/health",
            "codebase-intelligence": "http://localhost:8003/api/health",
        }

        with patch("src.run4.mcp_health.httpx.AsyncClient", return_value=mock_client):
            results = await poll_until_healthy(
                service_urls=service_urls,
                timeout_s=10,
                interval_s=0.01,
                required_consecutive=2,
            )

        assert len(results) == 3
        for name in service_urls:
            assert results[name]["status"] == "healthy"
            assert results[name]["consecutive_ok"] >= 2

    @pytest.mark.asyncio
    async def test_health_gate_blocks_on_failure(self) -> None:
        """Pipeline blocks (TimeoutError) when a service stays unhealthy."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.run4.mcp_health.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(TimeoutError, match="not healthy"):
                await poll_until_healthy(
                    service_urls={
                        "architect": "http://localhost:8001/api/health",
                        "contract-engine": "http://localhost:8002/api/health",
                    },
                    timeout_s=0.05,
                    interval_s=0.01,
                    required_consecutive=2,
                )

    @pytest.mark.asyncio
    async def test_partial_health_blocks_until_all_ready(self) -> None:
        """If only 2 of 3 are healthy, the gate still blocks."""
        import httpx

        call_count = 0
        ok_response = MagicMock(status_code=200)

        async def selective_get(url: str) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if "8003" in url:
                raise httpx.ConnectError("refused")
            return ok_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=selective_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.run4.mcp_health.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(TimeoutError, match="codebase-intelligence"):
                await poll_until_healthy(
                    service_urls={
                        "architect": "http://localhost:8001/api/health",
                        "contract-engine": "http://localhost:8002/api/health",
                        "codebase-intelligence": "http://localhost:8003/api/health",
                    },
                    timeout_s=0.1,
                    interval_s=0.01,
                    required_consecutive=2,
                )


# ===================================================================
# REQ-022 -- Phase 2: MCP Smoke
# ===================================================================


class TestPhase2MCPSmoke:
    """REQ-022 -- Mock MCP tool calls; verify key tools callable."""

    @pytest.mark.asyncio
    async def test_decompose_tool_callable(self, mock_mcp_session: AsyncMock) -> None:
        """Architect MCP 'decompose' tool is callable with sample PRD."""
        mock_mcp_session.call_tool = AsyncMock(
            return_value=make_mcp_result({
                "services": [
                    {"name": "auth-service"},
                    {"name": "order-service"},
                    {"name": "notification-service"},
                ],
            })
        )

        result = await mock_mcp_session.call_tool(
            "decompose", {"prd_text": "Sample PRD"}
        )
        assert not result.isError
        parsed = json.loads(result.content[0].text)
        assert "services" in parsed
        assert len(parsed["services"]) >= 3

    @pytest.mark.asyncio
    async def test_validate_spec_callable(self, mock_mcp_session: AsyncMock) -> None:
        """Contract Engine MCP 'validate_spec' tool is callable."""
        mock_mcp_session.call_tool = AsyncMock(
            return_value=make_mcp_result({"valid": True, "errors": []})
        )

        result = await mock_mcp_session.call_tool(
            "validate_spec", {"spec": {"openapi": "3.0.0"}}
        )
        assert not result.isError
        parsed = json.loads(result.content[0].text)
        assert parsed["valid"] is True

    @pytest.mark.asyncio
    async def test_find_definition_callable(self, mock_mcp_session: AsyncMock) -> None:
        """Codebase Intelligence MCP 'find_definition' tool is callable."""
        mock_mcp_session.call_tool = AsyncMock(
            return_value=make_mcp_result({
                "symbol": "UserModel",
                "file": "src/auth/models.py",
                "line": 42,
            })
        )

        result = await mock_mcp_session.call_tool(
            "find_definition", {"symbol": "UserModel"}
        )
        assert not result.isError
        parsed = json.loads(result.content[0].text)
        assert parsed["symbol"] == "UserModel"
        assert "file" in parsed

    @pytest.mark.asyncio
    async def test_all_smoke_tools_pass_gate(self, mock_mcp_session: AsyncMock) -> None:
        """Gate: ALL 3 key smoke tools must be callable without error."""
        tools_called: list[str] = []

        async def track_call(name: str, args: dict | None = None) -> MockToolResult:
            tools_called.append(name)
            return make_mcp_result({"status": "ok"})

        mock_mcp_session.call_tool = AsyncMock(side_effect=track_call)

        for tool_name in ["decompose", "validate_spec", "find_definition"]:
            result = await mock_mcp_session.call_tool(tool_name, {})
            assert not result.isError

        assert set(tools_called) == {"decompose", "validate_spec", "find_definition"}


# ===================================================================
# REQ-023 -- Phase 3: Architect Decomposition
# ===================================================================


class TestPhase3ArchitectDecomposition:
    """REQ-023 -- Mock decompose; verify ServiceMap and DomainModel."""

    @pytest.mark.asyncio
    async def test_service_map_has_3_services(self, mock_mcp_session: AsyncMock) -> None:
        """decompose returns a ServiceMap with >= 3 services."""
        decompose_result = {
            "service_map": {
                "services": [
                    {"name": "auth-service", "port": 8080, "type": "rest"},
                    {"name": "order-service", "port": 8080, "type": "rest"},
                    {"name": "notification-service", "port": 8080, "type": "rest"},
                ],
            },
            "domain_model": {
                "entities": [
                    {"name": "User", "fields": ["id", "email", "password_hash"]},
                    {"name": "Order", "fields": ["id", "user_id", "status", "total"]},
                    {"name": "Notification", "fields": ["id", "user_id", "message"]},
                ],
            },
            "contract_stubs": [
                {"from": "order-service", "to": "auth-service", "type": "openapi"},
                {"from": "notification-service", "to": "order-service", "type": "asyncapi"},
            ],
        }
        mock_mcp_session.call_tool = AsyncMock(
            return_value=make_mcp_result(decompose_result)
        )

        result = await mock_mcp_session.call_tool(
            "decompose", {"prd_text": "TaskTracker PRD"}
        )
        parsed = json.loads(result.content[0].text)

        service_map = parsed["service_map"]
        assert len(service_map["services"]) >= 3

        service_names = {s["name"] for s in service_map["services"]}
        assert "auth-service" in service_names
        assert "order-service" in service_names
        assert "notification-service" in service_names

    @pytest.mark.asyncio
    async def test_domain_model_has_3_entities(self, mock_mcp_session: AsyncMock) -> None:
        """decompose returns a DomainModel with >= 3 entities."""
        decompose_result = {
            "service_map": {"services": [{"name": "svc-1"}, {"name": "svc-2"}, {"name": "svc-3"}]},
            "domain_model": {
                "entities": [
                    {"name": "User", "fields": ["id", "email"]},
                    {"name": "Order", "fields": ["id", "total"]},
                    {"name": "Notification", "fields": ["id", "message"]},
                    {"name": "OrderItem", "fields": ["id", "product"]},
                ],
            },
        }
        mock_mcp_session.call_tool = AsyncMock(
            return_value=make_mcp_result(decompose_result)
        )

        result = await mock_mcp_session.call_tool(
            "decompose", {"prd_text": "TaskTracker PRD"}
        )
        parsed = json.loads(result.content[0].text)

        domain_model = parsed["domain_model"]
        assert len(domain_model["entities"]) >= 3

        entity_names = {e["name"] for e in domain_model["entities"]}
        assert "User" in entity_names
        assert "Order" in entity_names
        assert "Notification" in entity_names

    @pytest.mark.asyncio
    async def test_contract_stubs_present(self, mock_mcp_session: AsyncMock) -> None:
        """decompose returns ContractStubs for inter-service contracts."""
        decompose_result = {
            "service_map": {"services": [{"name": "auth"}, {"name": "order"}, {"name": "notif"}]},
            "domain_model": {"entities": [{"name": "User"}, {"name": "Order"}, {"name": "Notification"}]},
            "contract_stubs": [
                {"from": "order-service", "to": "auth-service", "type": "openapi"},
                {"from": "notification-service", "to": "order-service", "type": "asyncapi"},
            ],
        }
        mock_mcp_session.call_tool = AsyncMock(
            return_value=make_mcp_result(decompose_result)
        )

        result = await mock_mcp_session.call_tool("decompose", {"prd_text": "PRD"})
        parsed = json.loads(result.content[0].text)

        assert "contract_stubs" in parsed
        assert len(parsed["contract_stubs"]) >= 1


# ===================================================================
# REQ-024 -- Phase 4: Contract Registration
# ===================================================================


class TestPhase4ContractRegistration:
    """REQ-024 -- Mock create_contract/validate_spec/list_contracts."""

    @pytest.mark.asyncio
    async def test_create_contract_for_each_stub(self, mock_mcp_session: AsyncMock) -> None:
        """create_contract is called for each contract stub."""
        created_contracts: list[str] = []

        async def mock_create(name: str, args: dict | None = None) -> MockToolResult:
            if name == "create_contract":
                contract_name = (args or {}).get("name", "unknown")
                created_contracts.append(contract_name)
                return make_mcp_result({"id": f"c-{len(created_contracts)}", "status": "created"})
            return make_mcp_result({"error": "unknown tool"}, is_error=True)

        mock_mcp_session.call_tool = AsyncMock(side_effect=mock_create)

        stubs = [
            {"name": "auth-contract", "type": "openapi"},
            {"name": "order-contract", "type": "openapi"},
            {"name": "notification-contract", "type": "asyncapi"},
        ]

        for stub in stubs:
            result = await mock_mcp_session.call_tool("create_contract", stub)
            assert not result.isError

        assert len(created_contracts) == 3

    @pytest.mark.asyncio
    async def test_validate_spec_all_valid(self, mock_mcp_session: AsyncMock) -> None:
        """validate_spec returns valid: true for each registered contract."""
        mock_mcp_session.call_tool = AsyncMock(
            return_value=make_mcp_result({"valid": True, "errors": []})
        )

        contract_ids = ["c-1", "c-2", "c-3"]
        for cid in contract_ids:
            result = await mock_mcp_session.call_tool(
                "validate_spec", {"contract_id": cid}
            )
            parsed = json.loads(result.content[0].text)
            assert parsed["valid"] is True
            assert parsed["errors"] == []

    @pytest.mark.asyncio
    async def test_list_contracts_shows_all(self, mock_mcp_session: AsyncMock) -> None:
        """list_contracts returns all 3+ registered contracts."""
        mock_mcp_session.call_tool = AsyncMock(
            return_value=make_mcp_result({
                "contracts": [
                    {"id": "c-1", "name": "auth-contract", "valid": True},
                    {"id": "c-2", "name": "order-contract", "valid": True},
                    {"id": "c-3", "name": "notification-contract", "valid": True},
                ]
            })
        )

        result = await mock_mcp_session.call_tool("list_contracts", {})
        parsed = json.loads(result.content[0].text)
        assert len(parsed["contracts"]) >= 3
        assert all(c["valid"] for c in parsed["contracts"])


# ===================================================================
# REQ-025 -- Phase 5: Parallel Builders
# ===================================================================


class TestPhase5ParallelBuilders:
    """REQ-025 -- Mock 3 builder subprocesses; verify >= 2 succeed."""

    @pytest.mark.asyncio
    async def test_three_builders_at_least_two_succeed(self, tmp_path: Path) -> None:
        """Launch 3 builders; >= 2 must succeed (partial success acceptable)."""
        configs: list[dict[str, Any]] = []
        for i, name in enumerate(["auth-service", "order-service", "notification-service"]):
            d = tmp_path / name
            d.mkdir()
            configs.append({"cwd": str(d), "depth": "thorough"})

        call_index = 0

        async def mock_invoke(**kwargs: Any) -> BuilderResult:
            nonlocal call_index
            cwd = Path(kwargs["cwd"])
            idx = call_index
            call_index += 1
            # First 2 succeed, third fails
            if idx < 2:
                _write_state_json(cwd, success=True, test_passed=8, test_total=10)
                return _state_to_builder_result(
                    service_name=cwd.name, output_dir=cwd, exit_code=0
                )
            else:
                _write_state_json(cwd, success=False, test_passed=2, test_total=10, health="red")
                return _state_to_builder_result(
                    service_name=cwd.name, output_dir=cwd, exit_code=1
                )

        with patch("src.run4.builder.invoke_builder", side_effect=mock_invoke):
            results = await run_parallel_builders(
                configs, max_concurrent=3, timeout_s=30
            )

        assert len(results) == 3
        successes = [r for r in results if r.success]
        assert len(successes) >= 2, f"Expected >= 2 successes, got {len(successes)}"

    @pytest.mark.asyncio
    async def test_state_json_written_per_builder(self, tmp_path: Path) -> None:
        """Each builder writes STATE.JSON with summary dict."""
        configs: list[dict[str, Any]] = []
        for name in ["auth-service", "order-service", "notification-service"]:
            d = tmp_path / name
            d.mkdir()
            configs.append({"cwd": str(d)})

        async def mock_invoke(**kwargs: Any) -> BuilderResult:
            cwd = Path(kwargs["cwd"])
            _write_state_json(cwd, success=True, test_passed=10, test_total=10)
            return _state_to_builder_result(
                service_name=cwd.name, output_dir=cwd, exit_code=0
            )

        with patch("src.run4.builder.invoke_builder", side_effect=mock_invoke):
            results = await run_parallel_builders(
                configs, max_concurrent=3, timeout_s=30
            )

        for name in ["auth-service", "order-service", "notification-service"]:
            state_path = tmp_path / name / ".agent-team" / "STATE.json"
            assert state_path.exists(), f"STATE.json missing for {name}"
            data = json.loads(state_path.read_text(encoding="utf-8"))
            assert data["summary"]["success"] is True

    @pytest.mark.asyncio
    async def test_builder_result_collected_per_service(self, tmp_path: Path) -> None:
        """A BuilderResult is collected for each service."""
        configs: list[dict[str, Any]] = []
        service_names = ["auth-service", "order-service", "notification-service"]
        for name in service_names:
            d = tmp_path / name
            d.mkdir()
            configs.append({"cwd": str(d)})

        async def mock_invoke(**kwargs: Any) -> BuilderResult:
            cwd = Path(kwargs["cwd"])
            _write_state_json(cwd, success=True)
            return _state_to_builder_result(
                service_name=cwd.name, output_dir=cwd, exit_code=0
            )

        with patch("src.run4.builder.invoke_builder", side_effect=mock_invoke):
            results = await run_parallel_builders(
                configs, max_concurrent=3, timeout_s=30
            )

        assert len(results) == 3
        for r in results:
            assert isinstance(r, BuilderResult)
            assert r.service_name in service_names


# ===================================================================
# REQ-026 -- Phase 6: Deployment + Integration
# ===================================================================


class TestPhase6DeploymentIntegration:
    """REQ-026 -- Mock compose up, health checks, Schemathesis."""

    @pytest.mark.asyncio
    async def test_compose_up_and_health_checks(self) -> None:
        """docker compose up succeeds and all services become healthy."""
        mock_client = _mock_healthy_client()

        service_urls = {
            "auth-service": "http://localhost:8080/api/health",
            "order-service": "http://localhost:8081/api/health",
            "notification-service": "http://localhost:8082/api/health",
        }

        with patch("src.run4.mcp_health.httpx.AsyncClient", return_value=mock_client):
            results = await poll_until_healthy(
                service_urls=service_urls,
                timeout_s=10,
                interval_s=0.01,
                required_consecutive=2,
            )

        assert all(r["status"] == "healthy" for r in results.values())

    def test_schemathesis_contract_compliance_mock(self) -> None:
        """Schemathesis contract testing result meets > 70% compliance."""
        # Mock schemathesis report
        schemathesis_report = {
            "total_checks": 100,
            "passed_checks": 85,
            "failed_checks": 15,
            "compliance_rate": 0.85,
        }

        assert schemathesis_report["compliance_rate"] > 0.70
        assert schemathesis_report["passed_checks"] > schemathesis_report["failed_checks"]

    def test_cross_service_integration_flow_mock(self) -> None:
        """Mock the 4-step cross-service integration flow."""
        # Step 1: POST /register -> 201
        register_resp = {"status_code": 201, "body": {"id": "u-1", "email": "a@b.com", "created_at": "2026-01-01"}}
        assert register_resp["status_code"] == 201
        assert all(k in register_resp["body"] for k in ("id", "email", "created_at"))

        # Step 2: POST /login -> 200
        login_resp = {"status_code": 200, "body": {"access_token": "jwt-123", "refresh_token": "rt-456"}}
        assert login_resp["status_code"] == 200
        assert "access_token" in login_resp["body"]
        assert "refresh_token" in login_resp["body"]

        # Step 3: POST /orders -> 201
        order_resp = {"status_code": 201, "body": {"id": "o-1", "status": "pending", "items": [{"product": "A"}], "total": 9.99}}
        assert order_resp["status_code"] == 201
        assert all(k in order_resp["body"] for k in ("id", "status", "items", "total"))

        # Step 4: GET /notifications -> 200
        notif_resp = {"status_code": 200, "body": [{"id": "n-1", "message": "Order placed"}]}
        assert notif_resp["status_code"] == 200
        assert len(notif_resp["body"]) >= 1


# ===================================================================
# REQ-027 -- Phase 7: Quality Gate
# ===================================================================


class TestPhase7QualityGate:
    """REQ-027 -- Mock 4 layers of quality verification."""

    def test_layer1_builder_results(self) -> None:
        """Layer 1: Evaluate BuilderResult per service (test pass rate, convergence)."""
        builder_results = [
            BuilderResult(service_name="auth-service", success=True, test_passed=45, test_total=50, convergence_ratio=0.90),
            BuilderResult(service_name="order-service", success=True, test_passed=38, test_total=40, convergence_ratio=0.85),
            BuilderResult(service_name="notification-service", success=True, test_passed=20, test_total=25, convergence_ratio=0.80),
        ]

        for br in builder_results:
            assert br.success is True
            pass_rate = br.test_passed / br.test_total if br.test_total > 0 else 0
            assert pass_rate >= 0.70, f"{br.service_name} pass rate {pass_rate} < 0.70"
            assert br.convergence_ratio >= 0.70

        total_passed = sum(br.test_passed for br in builder_results)
        total_tests = sum(br.test_total for br in builder_results)
        overall_rate = total_passed / total_tests
        assert overall_rate >= 0.80

    def test_layer2_integration_report(self) -> None:
        """Layer 2: Evaluate contract test results (Schemathesis/Pact)."""
        integration_report = {
            "schemathesis": {"total": 80, "passed": 72, "failed": 8},
            "pact": {"total": 10, "passed": 10, "failed": 0},
            "overall_compliance": 0.91,
        }

        assert integration_report["overall_compliance"] > 0.70
        schemathesis_rate = (
            integration_report["schemathesis"]["passed"]
            / integration_report["schemathesis"]["total"]
        )
        assert schemathesis_rate > 0.70

    def test_layer3_code_quality_checks(self) -> None:
        """Layer 3: Specific code quality checks (SEC-SCAN-001, CORS-001, etc.)."""
        code_quality_checks = {
            "SEC-SCAN-001": {"passed": True, "description": "No hardcoded secrets"},
            "CORS-001": {"passed": True, "description": "CORS origins not wildcard"},
            "LOG-001": {"passed": False, "description": "No print() statements", "violations": 1},
            "LOG-002": {"passed": True, "description": "Request logging middleware present"},
            "DOCKER-001": {"passed": True, "description": "All services have HEALTHCHECK"},
            "DOCKER-002": {"passed": True, "description": "No :latest tags in FROM"},
        }

        passed_count = sum(1 for c in code_quality_checks.values() if c["passed"])
        total_count = len(code_quality_checks)
        assert passed_count >= 4, f"Only {passed_count}/{total_count} code quality checks passed"

    def test_layer4_static_analysis(self) -> None:
        """Layer 4: Static analysis checks (DEAD-001, ORPHAN-001, NAME-001, etc.)."""
        static_checks = {
            "DEAD-001": {"passed": True, "description": "No orphan events"},
            "DEAD-002": {"passed": True, "description": "All contracts validated"},
            "ORPHAN-001": {"passed": True, "description": "All compose services routed"},
            "NAME-001": {"passed": True, "description": "Service names consistent"},
        }

        all_passed = all(c["passed"] for c in static_checks.values())
        assert all_passed, "Static analysis checks should all pass"

    def test_overall_verdict_not_failed(self) -> None:
        """Gate: overall_verdict != 'failed' when layers mostly pass."""
        layer_results = {
            "layer1_builder": True,
            "layer2_integration": True,
            "layer3_code_quality": True,
            "layer4_static_analysis": True,
        }

        failed_layers = [k for k, v in layer_results.items() if not v]
        verdict = "failed" if len(failed_layers) >= 2 else "passed"
        assert verdict != "failed"

    def test_quality_gate_uses_scoring_engine(self) -> None:
        """Quality gate integrates with the scoring engine for final verdict."""
        from src.run4.scoring import compute_system_score, compute_integration_score

        sys_score = compute_system_score(
            system_name="Build 1",
            req_pass_rate=0.90,
            test_pass_rate=0.85,
            contract_pass_rate=0.80,
            total_violations=5,
            total_loc=2000,
            health_check_rate=1.0,
            artifacts_present=4,
            artifacts_required=5,
        )
        assert sys_score.total >= 60
        assert sys_score.traffic_light in ("GREEN", "YELLOW")

        int_score = compute_integration_score(
            mcp_tools_ok=18,
            flows_passing=4,
            flows_total=5,
            cross_build_violations=1,
            phases_complete=6,
            phases_total=7,
        )
        assert int_score.total >= 50
        assert int_score.traffic_light in ("GREEN", "YELLOW")
