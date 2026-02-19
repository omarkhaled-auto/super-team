"""Comprehensive test suite for Milestone 3 cross-service modules.

Covers:
    - CrossServiceTestGenerator  (TEST-001: 12 tests)
    - CrossServiceTestRunner     (TEST-002: 10 tests)
    - BoundaryTester             (TEST-003: 9 tests)
    - DataFlowTracer             (TEST-004: 10 tests)

Total: 41 test cases.

Run with:
    pytest tests/build3/test_cross_service.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.build3_shared.models import ContractViolation
from src.integrator.boundary_tester import BoundaryTester
from src.integrator.cross_service_test_generator import CrossServiceTestGenerator
from src.integrator.cross_service_test_runner import CrossServiceTestRunner
from src.integrator.data_flow_tracer import DataFlowTracer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _datetime_service_endpoints() -> dict[str, Any]:
    """Endpoints with datetime fields for boundary tests."""
    return {
        "/api/events": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "created_at": {
                                        "type": "string",
                                        "format": "date-time",
                                    },
                                    "description": {
                                        "type": "string",
                                        "nullable": True,
                                    },
                                },
                                "required": ["title"],
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
                                        "id": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    }


# ===========================================================================
# TEST-001: CrossServiceTestGenerator (12 tests)
# ===========================================================================


class TestCrossServiceTestGenerator:
    """Tests for CrossServiceTestGenerator."""

    @pytest.mark.asyncio
    async def test_generate_flow_tests_empty_registry(self, tmp_dir: Path) -> None:
        """Empty registry directory returns an empty flow list."""
        registry = tmp_dir / "empty_registry"
        registry.mkdir()

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        flows = await gen.generate_flow_tests()

        assert flows == []

    @pytest.mark.asyncio
    async def test_generate_flow_tests_single_service(self, tmp_dir: Path) -> None:
        """A single service cannot form a chain, so flows should be empty."""
        registry = tmp_dir / "single"
        registry.mkdir()

        write_openapi_spec(
            registry / "user-service.json",
            "user-service",
            _user_service_endpoints(),
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        flows = await gen.generate_flow_tests()

        assert flows == []

    @pytest.mark.asyncio
    async def test_generate_flow_tests_two_services_with_overlap(
        self, tmp_dir: Path,
    ) -> None:
        """Two services with >=2 overlapping fields produce at least one flow."""
        registry = tmp_dir / "overlap"
        registry.mkdir()

        # user-service responds with user_id, name, email
        write_openapi_spec(
            registry / "user-service.json",
            "user-service",
            _user_service_endpoints(),
        )
        # order-service requests user_id and email (2 fields overlap)
        write_openapi_spec(
            registry / "order-service.json",
            "order-service",
            _order_service_endpoints(),
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        flows = await gen.generate_flow_tests()

        assert len(flows) >= 1
        # Every flow must have flow_id, description, steps
        for flow in flows:
            assert "flow_id" in flow
            assert "description" in flow
            assert "steps" in flow
            assert len(flow["steps"]) >= 2

    @pytest.mark.asyncio
    async def test_generate_flow_tests_no_overlap(self, tmp_dir: Path) -> None:
        """Two services with <2 overlapping fields produce no flows."""
        registry = tmp_dir / "no_overlap"
        registry.mkdir()

        write_openapi_spec(
            registry / "alpha.json",
            "alpha",
            {
                "/api/a": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "foo": {"type": "string"},
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
                                                "bar": {"type": "string"},
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
        write_openapi_spec(
            registry / "beta.json",
            "beta",
            {
                "/api/b": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "baz": {"type": "string"},
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
                                                "qux": {"type": "string"},
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
    async def test_generate_flow_tests_deterministic(self, tmp_dir: Path) -> None:
        """Same input always produces the same output (TECH-015)."""
        registry = tmp_dir / "deterministic"
        registry.mkdir()

        write_openapi_spec(
            registry / "user-service.json",
            "user-service",
            _user_service_endpoints(),
        )
        write_openapi_spec(
            registry / "order-service.json",
            "order-service",
            _order_service_endpoints(),
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        flows_a = await gen.generate_flow_tests()
        flows_b = await gen.generate_flow_tests()

        assert flows_a == flows_b

    @pytest.mark.asyncio
    async def test_generate_boundary_tests_creates_all_types(
        self, tmp_dir: Path,
    ) -> None:
        """Boundary tests include case_sensitivity, timezone_handling, null_handling."""
        registry = tmp_dir / "boundary_all"
        registry.mkdir()

        write_openapi_spec(
            registry / "events.json",
            "event-service",
            _datetime_service_endpoints(),
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        boundary = await gen.generate_boundary_tests()

        assert len(boundary) > 0
        types_found = {bt["test_type"] for bt in boundary}
        # The spec has: title (string, required), created_at (datetime), description (nullable string)
        # -> case_sensitivity for title and description (non-datetime strings)
        # -> timezone_handling for created_at
        # -> null_handling for created_at (not required) and description (nullable)
        assert "case_sensitivity" in types_found
        assert "timezone_handling" in types_found
        assert "null_handling" in types_found

    @pytest.mark.asyncio
    async def test_generate_boundary_tests_datetime_fields(
        self, tmp_dir: Path,
    ) -> None:
        """Datetime fields produce timezone_handling boundary tests."""
        registry = tmp_dir / "boundary_dt"
        registry.mkdir()

        write_openapi_spec(
            registry / "ts.json",
            "timestamp-service",
            _datetime_service_endpoints(),
        )

        gen = CrossServiceTestGenerator(contract_registry_path=registry)
        boundary = await gen.generate_boundary_tests()

        tz_tests = [bt for bt in boundary if bt["test_type"] == "timezone_handling"]
        assert len(tz_tests) >= 1
        # The timezone test data should contain datetime field and variants
        for tz in tz_tests:
            assert "field" in tz["test_data"]
            assert "variants" in tz["test_data"]

    def test_generate_test_file_valid_python(self) -> None:
        """Generated code must be compilable Python."""
        gen = CrossServiceTestGenerator(contract_registry_path=Path("."))
        flows = [
            {
                "flow_id": "flow_001",
                "description": "user-service -> order-service",
                "steps": [
                    {
                        "service": "user-service",
                        "method": "POST",
                        "path": "/api/users",
                        "request_template": {"name": "test"},
                        "expected_status": 201,
                    },
                    {
                        "service": "order-service",
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
                "service": "user-service",
                "endpoint": "/api/users",
                "test_data": {"method": "POST", "field": "name", "variants": []},
            }
        ]

        code = gen.generate_test_file(flows, boundary_tests)
        # Must compile without SyntaxError
        compile(code, "<generated>", "exec")

    def test_generate_test_file_empty_inputs(self) -> None:
        """Empty flows and boundary lists still produce valid Python."""
        gen = CrossServiceTestGenerator(contract_registry_path=Path("."))
        code = gen.generate_test_file([], [])
        compile(code, "<generated>", "exec")
        assert "import" in code  # Should at least contain imports

    @pytest.mark.asyncio
    async def test_chain_detection_depth_limit(self, tmp_dir: Path) -> None:
        """Chains must not exceed depth 5."""
        registry = tmp_dir / "depth"
        registry.mkdir()

        # Create 7 services that chain linearly: a->b->c->d->e->f->g
        # via overlapping fields (x, y).
        shared_props = {
            "x": {"type": "string"},
            "y": {"type": "string"},
        }
        service_names = ["svc-a", "svc-b", "svc-c", "svc-d", "svc-e", "svc-f", "svc-g"]
        for svc in service_names:
            write_openapi_spec(
                registry / f"{svc}.json",
                svc,
                {
                    "/api/data": {
                        "post": {
                            "requestBody": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": shared_props,
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
                                                "properties": shared_props,
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

        for flow in flows:
            assert len(flow["steps"]) <= 5, (
                f"Flow {flow['flow_id']} has {len(flow['steps'])} steps, "
                f"exceeding the depth limit of 5"
            )

    def test_to_camel_case_conversion(self) -> None:
        """_to_camel_case converts snake_case to camelCase."""
        gen = CrossServiceTestGenerator(contract_registry_path=Path("."))
        assert gen._to_camel_case("my_field") == "myField"
        assert gen._to_camel_case("already") == "already"
        assert gen._to_camel_case("a_b_c") == "aBC"

    def test_to_snake_case_conversion(self) -> None:
        """_to_snake_case converts camelCase to snake_case."""
        gen = CrossServiceTestGenerator(contract_registry_path=Path("."))
        assert gen._to_snake_case("myField") == "my_field"
        assert gen._to_snake_case("already") == "already"
        assert gen._to_snake_case("MyPascalCase") == "my_pascal_case"


# ===========================================================================
# TEST-002: CrossServiceTestRunner (10 tests)
# ===========================================================================


class TestCrossServiceTestRunner:
    """Tests for CrossServiceTestRunner."""

    @pytest.mark.asyncio
    async def test_run_single_flow_success(self) -> None:
        """All steps pass -> success=True, no violations."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_001",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "GET",
                    "path": "/api/data",
                    "request_template": {},
                    "expected_status": 200,
                },
            ],
        }
        service_urls = {"svc-a": "http://localhost:8001"}

        mock_resp = make_mock_response(200, {"id": 1})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is True
        assert errors == []

    @pytest.mark.asyncio
    async def test_run_single_flow_status_mismatch(self) -> None:
        """Wrong status code creates FLOW-001 violation."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_002",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "POST",
                    "path": "/api/items",
                    "request_template": {"name": "test"},
                    "expected_status": 201,
                },
            ],
        }
        service_urls = {"svc-a": "http://localhost:8001"}

        mock_resp = make_mock_response(400, {"error": "bad request"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is False
        assert len(errors) >= 1
        assert "Status mismatch" in errors[0]

    @pytest.mark.asyncio
    async def test_run_single_flow_missing_service_url(self) -> None:
        """Missing service URL creates FLOW-002 violation."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_003",
            "steps": [
                {
                    "service": "nonexistent-svc",
                    "method": "GET",
                    "path": "/api/data",
                    "request_template": {},
                    "expected_status": 200,
                },
            ],
        }
        service_urls = {}  # no URLs at all

        success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is False
        assert len(errors) >= 1
        assert "not found" in errors[0]

    @pytest.mark.asyncio
    async def test_run_single_flow_connection_error(self) -> None:
        """httpx error creates FLOW-002 violation."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_004",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "GET",
                    "path": "/api/data",
                    "request_template": {},
                    "expected_status": 200,
                },
            ],
        }
        service_urls = {"svc-a": "http://localhost:9999"}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused"),
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is False
        assert len(errors) >= 1

    @pytest.mark.asyncio
    async def test_run_single_flow_template_resolution(self) -> None:
        """{step_0_response.id} is resolved correctly from prior step."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_005",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "POST",
                    "path": "/api/users",
                    "request_template": {"name": "alice"},
                    "expected_status": 201,
                },
                {
                    "service": "svc-b",
                    "method": "POST",
                    "path": "/api/orders",
                    "request_template": {
                        "user_id": "{step_0_response.id}",
                    },
                    "expected_status": 201,
                },
            ],
        }
        service_urls = {
            "svc-a": "http://localhost:8001",
            "svc-b": "http://localhost:8002",
        }

        resp_step0 = make_mock_response(201, {"id": "user-123", "name": "alice"})
        resp_step1 = make_mock_response(201, {"order_id": "order-456"})

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_step0
            return resp_step1

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=side_effect)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is True

        # Verify the second request was called with the resolved body
        second_call = mock_client.request.call_args_list[1]
        # The json kwarg should have the resolved user_id
        if second_call.kwargs.get("json"):
            assert second_call.kwargs["json"]["user_id"] == "user-123"

    @pytest.mark.asyncio
    async def test_run_single_flow_template_missing_field(self) -> None:
        """Missing field in step response creates FLOW-003 violation."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_006",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "GET",
                    "path": "/api/data",
                    "request_template": {},
                    "expected_status": 200,
                },
                {
                    "service": "svc-b",
                    "method": "POST",
                    "path": "/api/other",
                    "request_template": {
                        "val": "{step_0_response.nonexistent_field}",
                    },
                    "expected_status": 200,
                },
            ],
        }
        service_urls = {
            "svc-a": "http://localhost:8001",
            "svc-b": "http://localhost:8002",
        }

        resp_step0 = make_mock_response(200, {"id": 1})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=resp_step0)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is False
        assert len(errors) >= 1
        assert "Template resolution failed" in errors[0]

    @pytest.mark.asyncio
    async def test_run_flow_tests_multiple_flows(self) -> None:
        """run_flow_tests executes all flows and returns results for each."""
        runner = CrossServiceTestRunner()
        flows = [
            {
                "flow_id": f"flow_{i:03d}",
                "steps": [
                    {
                        "service": "svc-a",
                        "method": "GET",
                        "path": "/api/data",
                        "request_template": {},
                        "expected_status": 200,
                    },
                ],
            }
            for i in range(3)
        ]
        service_urls = {"svc-a": "http://localhost:8001"}

        mock_resp = make_mock_response(200, {"ok": True})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            report = await runner.run_flow_tests(flows, service_urls)

        assert report.integration_tests_total == 3
        assert report.integration_tests_passed == 3

    @pytest.mark.asyncio
    async def test_run_single_flow_empty_steps(self) -> None:
        """A flow with no steps returns success."""
        runner = CrossServiceTestRunner()
        flow = {"flow_id": "empty_flow", "steps": []}
        service_urls = {}

        success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is True
        assert errors == []

    @pytest.mark.asyncio
    async def test_run_single_flow_non_json_response(self) -> None:
        """Non-JSON response is handled gracefully (stored as empty dict)."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_nonjson",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "GET",
                    "path": "/api/html",
                    "request_template": {},
                    "expected_status": 200,
                },
            ],
        }
        service_urls = {"svc-a": "http://localhost:8001"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_resp.text = "<html>hello</html>"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is True

    @pytest.mark.asyncio
    async def test_template_resolution_preserves_types(self) -> None:
        """Numeric values stay numeric after template resolution."""
        runner = CrossServiceTestRunner()
        flow = {
            "flow_id": "flow_types",
            "steps": [
                {
                    "service": "svc-a",
                    "method": "GET",
                    "path": "/api/data",
                    "request_template": {},
                    "expected_status": 200,
                },
                {
                    "service": "svc-b",
                    "method": "POST",
                    "path": "/api/process",
                    "request_template": {
                        "count": "{step_0_response.count}",
                    },
                    "expected_status": 200,
                },
            ],
        }
        service_urls = {
            "svc-a": "http://localhost:8001",
            "svc-b": "http://localhost:8002",
        }

        resp_step0 = make_mock_response(200, {"count": 42})
        resp_step1 = make_mock_response(200, {"result": "ok"})

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_step0
            return resp_step1

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=side_effect)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            success, errors = await runner.run_single_flow(flow, service_urls)

        assert success is True
        # Verify the resolved template sent to step 2 preserved the numeric type
        second_call = mock_client.request.call_args_list[1]
        if second_call.kwargs.get("json"):
            assert second_call.kwargs["json"]["count"] == 42
            assert isinstance(second_call.kwargs["json"]["count"], int)


# ===========================================================================
# TEST-003: BoundaryTester (9 tests)
# ===========================================================================


class TestBoundaryTester:
    """Tests for BoundaryTester."""

    @pytest.mark.asyncio
    async def test_case_sensitivity_consistent_handling(self) -> None:
        """Same status for both formats produces no violations."""
        tester = BoundaryTester()

        mock_resp = make_mock_response(200, {"ok": True})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            violations = await tester.test_case_sensitivity(
                service_name="test-svc",
                endpoint="/api/items",
                camel_body={"myField": "value"},
                snake_body={"my_field": "value"},
                service_url="http://localhost:8001",
            )

        assert violations == []

    @pytest.mark.asyncio
    async def test_case_sensitivity_crash_on_one_format(self) -> None:
        """500 on one format but not the other = error violation."""
        tester = BoundaryTester()

        resp_ok = make_mock_response(200, {"ok": True})
        resp_crash = make_mock_response(500, {"error": "internal"})

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            # First call (snake_case) succeeds, second (camelCase) crashes
            if call_count == 1:
                return resp_ok
            return resp_crash

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=side_effect)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            violations = await tester.test_case_sensitivity(
                service_name="test-svc",
                endpoint="/api/items",
                camel_body={"myField": "value"},
                snake_body={"my_field": "value"},
                service_url="http://localhost:8001",
            )

        assert len(violations) >= 1
        assert any(v.code == "BOUNDARY-CASE-001" for v in violations)
        assert any(v.severity == "error" for v in violations)

    @pytest.mark.asyncio
    async def test_case_sensitivity_different_non_500_status(self) -> None:
        """Different non-500 status codes produce a warning violation."""
        tester = BoundaryTester()

        resp_200 = make_mock_response(200, {})
        resp_404 = make_mock_response(404, {})

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_200
            return resp_404

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=side_effect)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            violations = await tester.test_case_sensitivity(
                service_name="test-svc",
                endpoint="/api/items",
                camel_body={"fieldName": "value"},
                snake_body={"field_name": "value"},
                service_url="http://localhost:8001",
            )

        assert len(violations) == 1
        assert violations[0].code == "BOUNDARY-CASE-001"
        assert violations[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_timezone_handling_consistent(self) -> None:
        """All variants accepted (< 500) produces no violations."""
        tester = BoundaryTester()

        mock_resp = make_mock_response(200, {"ok": True})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            violations = await tester.test_timezone_handling(
                service_name="test-svc",
                endpoint="/api/events",
                service_url="http://localhost:8001",
                test_data={"event_date": "2024-01-01T00:00:00Z"},
            )

        assert violations == []

    @pytest.mark.asyncio
    async def test_timezone_handling_partial_crash(self) -> None:
        """Some variants crash (500) while others pass = violation."""
        tester = BoundaryTester()

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            # First 2 calls succeed, rest crash
            if call_count <= 2:
                return make_mock_response(200, {"ok": True})
            return make_mock_response(500, {"error": "crash"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=side_effect)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            violations = await tester.test_timezone_handling(
                service_name="test-svc",
                endpoint="/api/events",
                service_url="http://localhost:8001",
                test_data={"event_date": "2024-01-01T00:00:00Z"},
            )

        assert len(violations) >= 1
        assert any(v.code == "BOUNDARY-TZ-001" for v in violations)

    @pytest.mark.asyncio
    async def test_null_handling_server_crash(self) -> None:
        """500 on null/missing/empty = BOUNDARY-NULL-001 violation."""
        tester = BoundaryTester()

        mock_resp = make_mock_response(500, {"error": "null pointer"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            violations = await tester.test_null_handling(
                service_name="test-svc",
                endpoint="/api/items",
                service_url="http://localhost:8001",
                test_data={"name": "test", "value": "data"},
            )

        assert len(violations) >= 1
        assert all(v.code == "BOUNDARY-NULL-001" for v in violations)

    @pytest.mark.asyncio
    async def test_null_handling_proper_validation(self) -> None:
        """400/422 on null input is proper behaviour, no violations."""
        tester = BoundaryTester()

        mock_resp = make_mock_response(422, {"detail": "field required"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            violations = await tester.test_null_handling(
                service_name="test-svc",
                endpoint="/api/items",
                service_url="http://localhost:8001",
                test_data={"name": "test"},
            )

        assert violations == []

    @pytest.mark.asyncio
    async def test_run_all_boundary_tests_dispatches(self) -> None:
        """run_all_boundary_tests dispatches to the correct test methods."""
        tester = BoundaryTester()

        boundary_tests = [
            {
                "test_id": "bt_001",
                "test_type": "case_sensitivity",
                "service": "svc-a",
                "endpoint": "/api/items",
                "test_data": {"field": "value"},
            },
            {
                "test_id": "bt_002",
                "test_type": "null_handling",
                "service": "svc-a",
                "endpoint": "/api/items",
                "test_data": {"field": "value"},
            },
        ]
        service_urls = {"svc-a": "http://localhost:8001"}

        mock_case_result = [
            ContractViolation(code="BOUNDARY-CASE-001", severity="warning"),
        ]
        mock_null_result: list[ContractViolation] = []

        with (
            patch.object(
                tester,
                "test_case_sensitivity",
                new_callable=AsyncMock,
                return_value=mock_case_result,
            ) as mock_case,
            patch.object(
                tester,
                "test_null_handling",
                new_callable=AsyncMock,
                return_value=mock_null_result,
            ) as mock_null,
        ):
            violations = await tester.run_all_boundary_tests(
                contracts=[],
                service_urls=service_urls,
                boundary_tests=boundary_tests,
            )

        mock_case.assert_awaited_once()
        mock_null.assert_awaited_once()
        assert len(violations) == 1
        assert violations[0].code == "BOUNDARY-CASE-001"

    @pytest.mark.asyncio
    async def test_boundary_tester_http_error_resilience(self) -> None:
        """httpx error in test_case_sensitivity returns empty list."""
        tester = BoundaryTester()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused"),
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            violations = await tester.test_case_sensitivity(
                service_name="test-svc",
                endpoint="/api/items",
                camel_body={"name": "test"},
                snake_body={"name": "test"},
                service_url="http://localhost:9999",
            )

        assert violations == []


# ===========================================================================
# TEST-004: DataFlowTracer (10 tests)
# ===========================================================================


class TestDataFlowTracer:
    """Tests for DataFlowTracer."""

    @pytest.mark.asyncio
    async def test_trace_request_single_hop(self) -> None:
        """Single service returns exactly 1 trace record."""
        tracer = DataFlowTracer()

        mock_resp = make_mock_response(200, {"user_id": "abc"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            records = await tracer.trace_request(
                service_urls={"svc-a": "http://localhost:8001"},
                method="GET",
                path="/api/users",
            )

        assert len(records) == 1
        assert records[0]["service"] == "svc-a"
        assert records[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_trace_request_multi_hop(self) -> None:
        """Multiple services return N trace records."""
        tracer = DataFlowTracer()

        mock_resp = make_mock_response(200, {"data": "ok"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            records = await tracer.trace_request(
                service_urls={
                    "svc-a": "http://localhost:8001",
                    "svc-b": "http://localhost:8002",
                    "svc-c": "http://localhost:8003",
                },
                method="POST",
                path="/api/data",
                body={"key": "value"},
            )

        assert len(records) == 3
        services = [r["service"] for r in records]
        assert services == ["svc-a", "svc-b", "svc-c"]

    @pytest.mark.asyncio
    async def test_trace_id_format(self) -> None:
        """trace_id is 32-char hex and traceparent follows W3C format."""
        tracer = DataFlowTracer()

        captured_headers: dict[str, str] = {}

        async def capture_request(
            *args: Any, **kwargs: Any,
        ) -> MagicMock:
            hdrs = kwargs.get("headers", {})
            captured_headers.update(hdrs)
            return make_mock_response(200, {"id": 1})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=capture_request)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            records = await tracer.trace_request(
                service_urls={"svc-a": "http://localhost:8001"},
                method="GET",
                path="/api/check",
            )

        # Validate trace_id is 32-char hex
        trace_id = records[0]["trace_id"]
        assert len(trace_id) == 32
        assert all(c in "0123456789abcdef" for c in trace_id)

        # Validate traceparent header format: 00-{trace_id}-0000000000000001-01
        traceparent = captured_headers.get("traceparent", "")
        assert traceparent == f"00-{trace_id}-0000000000000001-01"

    @pytest.mark.asyncio
    async def test_verify_passthrough_success(self) -> None:
        """Matching values for passthrough transform = no violations."""
        tracer = DataFlowTracer()

        trace_records = [
            {"service": "svc-a", "status": 200, "body": {"user_id": "abc"}, "trace_id": "aabb"},
            {"service": "svc-b", "status": 200, "body": {"user_id": "abc"}, "trace_id": "aabb"},
        ]
        transformations = [
            {
                "source_service": "svc-a",
                "target_service": "svc-b",
                "field": "user_id",
                "transform": "passthrough",
                "source_field": "user_id",
                "target_field": "user_id",
            }
        ]

        violations = await tracer.verify_data_transformations(
            trace_records, transformations,
        )

        assert violations == []

    @pytest.mark.asyncio
    async def test_verify_passthrough_mismatch(self) -> None:
        """Different values for passthrough = DATAFLOW-003."""
        violation = DataFlowTracer._check_transform(
            transform="passthrough",
            field_name="user_id",
            source_service="svc-a",
            target_service="svc-b",
            source_field="user_id",
            target_field="user_id",
            source_body={"user_id": "abc"},
            target_body={"user_id": "xyz"},
        )

        assert violation is not None
        assert violation.code == "DATAFLOW-003"

    @pytest.mark.asyncio
    async def test_verify_rename_success(self) -> None:
        """Rename transform with matching values = no violations."""
        violation = DataFlowTracer._check_transform(
            transform="rename",
            field_name="user_identifier",
            source_service="svc-a",
            target_service="svc-b",
            source_field="user_id",
            target_field="userId",
            source_body={"user_id": "abc"},
            target_body={"userId": "abc"},
        )

        assert violation is None

    @pytest.mark.asyncio
    async def test_verify_missing_field(self) -> None:
        """Missing field in target body = DATAFLOW-002."""
        violation = DataFlowTracer._check_transform(
            transform="passthrough",
            field_name="user_id",
            source_service="svc-a",
            target_service="svc-b",
            source_field="user_id",
            target_field="user_id",
            source_body={"user_id": "abc"},
            target_body={},
        )

        assert violation is not None
        assert violation.code == "DATAFLOW-002"

    @pytest.mark.asyncio
    async def test_verify_missing_service(self) -> None:
        """Missing service record = hop_index out of range error."""
        tracer = DataFlowTracer()

        trace_records = [
            {"service": "svc-a", "status": 200, "body": {"user_id": "abc"}, "trace_id": "aabb"},
            # svc-b is missing entirely -- only 1 hop
        ]
        transformations = [
            {
                "hop_index": 1,
                "field": "user_id",
                "expected_type": "",
                "expected_value_pattern": None,
            }
        ]

        errors = await tracer.verify_data_transformations(
            trace_records, transformations,
        )

        assert len(errors) == 1
        assert "out of range" in errors[0]

    @pytest.mark.asyncio
    async def test_verify_format_transform(self) -> None:
        """Format check: both fields present and non-null = no violations."""
        tracer = DataFlowTracer()

        trace_records = [
            {"service": "svc-a", "status": 200, "body": {"date": "2024-01-01"}, "trace_id": "aabb"},
            {"service": "svc-b", "status": 200, "body": {"formatted_date": "Jan 1, 2024"}, "trace_id": "aabb"},
        ]
        transformations = [
            {
                "source_service": "svc-a",
                "target_service": "svc-b",
                "field": "date",
                "transform": "format",
                "source_field": "date",
                "target_field": "formatted_date",
            }
        ]

        violations = await tracer.verify_data_transformations(
            trace_records, transformations,
        )

        assert violations == []

    @pytest.mark.asyncio
    async def test_verify_unknown_transform(self) -> None:
        """Unknown transform type = DATAFLOW-004 warning."""
        violation = DataFlowTracer._check_transform(
            transform="foobar_unknown",
            field_name="x",
            source_service="svc-a",
            target_service="svc-b",
            source_field="x",
            target_field="x",
            source_body={"x": 1},
            target_body={"x": 1},
        )

        assert violation is not None
        assert violation.code == "DATAFLOW-004"
        assert violation.severity == "warning"
