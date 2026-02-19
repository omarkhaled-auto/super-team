"""Integration tests for the Contract Engine MCP server.

Tests the MCP tool functions exposed by ``src.contract_engine.mcp_server``
by patching module-level database and service instances with temporary ones
so each test runs against an isolated SQLite database.
"""
from __future__ import annotations

import uuid

import pytest
from mcp.server.fastmcp import FastMCP

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db
from src.contract_engine.services.contract_store import ContractStore
from src.contract_engine.services.implementation_tracker import ImplementationTracker
from src.contract_engine.services.version_manager import VersionManager
from src.contract_engine.services.test_generator import ContractTestGenerator
from src.contract_engine.services.compliance_checker import ComplianceChecker

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/api/users": {
            "get": {
                "summary": "List users",
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "$ref": "#/components/schemas/User"
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["id", "name"],
            }
        }
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def contract_mcp(tmp_path, monkeypatch):
    """Set up the Contract Engine MCP server with a temporary database.

    Patches all module-level service instances so tool functions operate
    against an isolated, ephemeral SQLite file.
    """
    db_path = str(tmp_path / "contract_test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    import src.contract_engine.mcp_server as mod

    pool = ConnectionPool(db_path)
    init_contracts_db(pool)

    monkeypatch.setattr(mod, "_pool", pool)
    monkeypatch.setattr(mod, "_contract_store", ContractStore(pool))
    monkeypatch.setattr(mod, "_implementation_tracker", ImplementationTracker(pool))
    monkeypatch.setattr(mod, "_version_manager", VersionManager(pool))
    monkeypatch.setattr(mod, "_test_generator", ContractTestGenerator(pool))
    monkeypatch.setattr(mod, "_compliance_checker", ComplianceChecker(pool))

    yield mod

    pool.close()


def _create_sample_contract(mod) -> dict:
    """Helper: create and return a sample OpenAPI contract via the MCP tool."""
    return mod.create_contract(
        service_name="user-service",
        type="openapi",
        version="1.0.0",
        spec=SAMPLE_OPENAPI_SPEC,
    )


# ---------------------------------------------------------------------------
# MCP instance sanity checks
# ---------------------------------------------------------------------------


class TestContractEngineMCPInstance:
    """Verify the FastMCP instance is correctly wired."""

    def test_mcp_is_fastmcp_instance(self, contract_mcp):
        assert isinstance(contract_mcp.mcp, FastMCP)

    def test_mcp_has_registered_tools(self, contract_mcp):
        tools = contract_mcp.mcp._tool_manager._tools
        expected_tools = [
            "create_contract",
            "list_contracts",
            "get_contract",
            "validate_spec",
            "check_breaking_changes",
            "mark_implemented",
            "get_unimplemented_contracts",
            "generate_tests",
            "check_compliance",
            "validate_endpoint",
        ]
        for tool_name in expected_tools:
            assert tool_name in tools, f"Tool '{tool_name}' not registered"

    def test_mcp_name_is_contract_engine(self, contract_mcp):
        assert contract_mcp.mcp.name == "Contract Engine"

    def test_mcp_tool_count_is_10(self, contract_mcp):
        tools = contract_mcp.mcp._tool_manager._tools
        assert len(tools) == 10, f"Expected 10 tools, found {len(tools)}: {list(tools.keys())}"


# ---------------------------------------------------------------------------
# create_contract tool
# ---------------------------------------------------------------------------


class TestCreateContract:
    """Tests for the ``create_contract`` MCP tool."""

    def test_create_valid_openapi_contract(self, contract_mcp):
        result = _create_sample_contract(contract_mcp)

        assert isinstance(result, dict)
        assert "error" not in result
        assert "id" in result
        assert result["type"] == "openapi"
        assert result["version"] == "1.0.0"
        assert result["service_name"] == "user-service"
        assert "spec_hash" in result
        assert result["spec_hash"] != ""

    def test_create_contract_invalid_type_returns_error(self, contract_mcp):
        result = contract_mcp.create_contract(
            service_name="user-service",
            type="grpc",
            version="1.0.0",
            spec=SAMPLE_OPENAPI_SPEC,
        )

        assert isinstance(result, dict)
        assert "error" in result
        assert "grpc" in result["error"]

    def test_create_contract_upsert_same_service_type_version(self, contract_mcp):
        """Creating the same contract twice should upsert (not error)."""
        first = _create_sample_contract(contract_mcp)
        second = _create_sample_contract(contract_mcp)

        assert first["id"] == second["id"]


# ---------------------------------------------------------------------------
# list_contracts tool
# ---------------------------------------------------------------------------


class TestListContracts:
    """Tests for the ``list_contracts`` MCP tool."""

    def test_empty_list_initially(self, contract_mcp):
        result = contract_mcp.list_contracts()

        assert isinstance(result, dict)
        assert "items" in result
        assert result["total"] == 0
        assert result["items"] == []

    def test_list_after_creating_one(self, contract_mcp):
        _create_sample_contract(contract_mcp)

        result = contract_mcp.list_contracts()

        assert result["total"] >= 1
        assert len(result["items"]) >= 1
        assert result["items"][0]["service_name"] == "user-service"

    def test_list_filter_by_service_name(self, contract_mcp):
        _create_sample_contract(contract_mcp)

        result = contract_mcp.list_contracts(service_name="user-service")
        assert result["total"] >= 1

        result_empty = contract_mcp.list_contracts(service_name="nonexistent-service")
        assert result_empty["total"] == 0

    def test_list_pagination(self, contract_mcp):
        _create_sample_contract(contract_mcp)

        result = contract_mcp.list_contracts(page=1, page_size=5)
        assert result["page"] == 1
        assert result["page_size"] == 5


# ---------------------------------------------------------------------------
# get_contract tool
# ---------------------------------------------------------------------------


class TestGetContract:
    """Tests for the ``get_contract`` MCP tool."""

    def test_nonexistent_id_returns_error(self, contract_mcp):
        fake_id = str(uuid.uuid4())
        result = contract_mcp.get_contract(fake_id)

        assert isinstance(result, dict)
        assert "error" in result

    def test_get_contract_after_create(self, contract_mcp):
        created = _create_sample_contract(contract_mcp)
        contract_id = created["id"]

        result = contract_mcp.get_contract(contract_id)

        assert isinstance(result, dict)
        assert "error" not in result
        assert result["id"] == contract_id
        assert result["service_name"] == "user-service"


# ---------------------------------------------------------------------------
# validate_contract tool
# ---------------------------------------------------------------------------


class TestValidateContract:
    """Tests for the ``validate_contract`` MCP tool."""

    def test_validate_openapi_valid_spec(self, contract_mcp):
        result = contract_mcp.validate_contract(
            spec=SAMPLE_OPENAPI_SPEC,
            type="openapi",
        )

        assert isinstance(result, dict)
        assert "valid" in result
        assert "errors" in result
        assert "warnings" in result

    def test_validate_json_schema_returns_warning(self, contract_mcp):
        result = contract_mcp.validate_contract(
            spec={"type": "object"},
            type="json_schema",
        )

        assert isinstance(result, dict)
        assert result["valid"] is True
        assert len(result["warnings"]) > 0
        assert "not yet implemented" in result["warnings"][0].lower()

    def test_validate_unknown_type_returns_error(self, contract_mcp):
        result = contract_mcp.validate_contract(
            spec={},
            type="graphql",
        )

        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# mark_implementation tool
# ---------------------------------------------------------------------------


class TestMarkImplementation:
    """Tests for the ``mark_implementation`` MCP tool."""

    def test_mark_implementation_after_create(self, contract_mcp):
        created = _create_sample_contract(contract_mcp)
        contract_id = created["id"]

        result = contract_mcp.mark_implementation(
            contract_id=contract_id,
            service_name="user-service",
            evidence_path="/tests/test_user_api.py",
        )

        assert isinstance(result, dict)
        assert "error" not in result
        assert "marked" in result
        assert result["marked"] is True
        # SVC-005: mark_implemented returns {marked, total, all_implemented}
        assert "total" in result
        assert "all_implemented" in result

    def test_mark_implementation_nonexistent_contract(self, contract_mcp):
        fake_id = str(uuid.uuid4())

        result = contract_mcp.mark_implementation(
            contract_id=fake_id,
            service_name="user-service",
            evidence_path="/tests/test_user_api.py",
        )

        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# get_unimplemented tool
# ---------------------------------------------------------------------------


class TestGetUnimplemented:
    """Tests for the ``get_unimplemented`` MCP tool."""

    def test_unimplemented_returns_created_contract(self, contract_mcp):
        created = _create_sample_contract(contract_mcp)

        result = contract_mcp.get_unimplemented()

        assert isinstance(result, list)
        # The newly created contract should appear as unimplemented
        contract_ids = [item.get("id") for item in result]
        assert created["id"] in contract_ids

    def test_unimplemented_filter_by_service_name(self, contract_mcp):
        _create_sample_contract(contract_mcp)

        result = contract_mcp.get_unimplemented(service_name="user-service")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_unimplemented_empty_on_clean_db(self, contract_mcp):
        result = contract_mcp.get_unimplemented()
        assert isinstance(result, list)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# generate_tests tool
# ---------------------------------------------------------------------------


class TestGenerateTests:
    """Tests for the ``generate_tests`` MCP tool."""

    def test_generate_tests_for_contract(self, contract_mcp):
        """SVC-003: generate_tests returns raw string (test code), NOT dict."""
        created = _create_sample_contract(contract_mcp)
        contract_id = created["id"]

        result = contract_mcp.generate_tests(contract_id=contract_id)

        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"
        assert len(result) > 0

    def test_generate_tests_nonexistent_contract(self, contract_mcp):
        fake_id = str(uuid.uuid4())

        result = contract_mcp.generate_tests(contract_id=fake_id)

        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"
        assert "error" in result

    def test_generate_tests_with_framework_param(self, contract_mcp):
        created = _create_sample_contract(contract_mcp)
        contract_id = created["id"]

        result = contract_mcp.generate_tests(
            contract_id=contract_id,
            framework="pytest",
        )

        # SVC-003: returns raw string test code
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# check_compliance tool
# ---------------------------------------------------------------------------


class TestCheckCompliance:
    """Tests for the ``check_compliance`` MCP tool."""

    def test_check_compliance_returns_list(self, contract_mcp):
        created = _create_sample_contract(contract_mcp)
        contract_id = created["id"]

        result = contract_mcp.check_compliance(contract_id=contract_id)

        assert isinstance(result, list)

    def test_check_compliance_with_response_data(self, contract_mcp):
        created = _create_sample_contract(contract_mcp)
        contract_id = created["id"]

        response_data = {
            "GET /api/users": [{"id": "1", "name": "Alice"}],
        }
        result = contract_mcp.check_compliance(
            contract_id=contract_id,
            response_data=response_data,
        )

        assert isinstance(result, list)
        for item in result:
            assert "endpoint_path" in item
            assert "method" in item
            assert "compliant" in item
            assert "violations" in item

    def test_check_compliance_nonexistent_contract(self, contract_mcp):
        fake_id = str(uuid.uuid4())

        result = contract_mcp.check_compliance(contract_id=fake_id)

        assert isinstance(result, list)
        assert len(result) > 0
        assert "error" in result[0]


# ---------------------------------------------------------------------------
# detect_breaking_changes
# ---------------------------------------------------------------------------


class TestDetectBreakingChanges:
    """Tests for the ``detect_breaking_changes`` MCP tool."""

    def test_detect_breaking_changes_nonexistent_contract(self, contract_mcp):
        fake_id = str(uuid.uuid4())

        result = contract_mcp.detect_breaking_changes(contract_id=fake_id)

        assert isinstance(result, list)
        assert len(result) > 0
        assert "error" in result[0]

    def test_detect_breaking_changes_with_new_spec(self, contract_mcp):
        created = _create_sample_contract(contract_mcp)
        contract_id = created["id"]

        # Create a modified spec that removes a required field (breaking change)
        new_spec = {
            "openapi": "3.1.0",
            "info": {"title": "Test API", "version": "2.0.0"},
            "paths": {
                "/api/users": {
                    "get": {
                        "summary": "List users",
                        "responses": {
                            "200": {
                                "description": "Success",
                            }
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                        },
                        "required": ["id"],
                    }
                }
            },
        }

        result = contract_mcp.detect_breaking_changes(
            contract_id=contract_id,
            new_spec=new_spec,
        )

        assert isinstance(result, list)

    def test_detect_breaking_changes_no_new_spec_no_history(self, contract_mcp):
        """With a single version and no new_spec, should return empty list."""
        created = _create_sample_contract(contract_mcp)
        contract_id = created["id"]

        result = contract_mcp.detect_breaking_changes(contract_id=contract_id)

        assert isinstance(result, list)
        assert result == []


# ---------------------------------------------------------------------------
# validate_endpoint tool
# ---------------------------------------------------------------------------


class TestValidateEndpoint:
    """Tests for the ``validate_endpoint`` MCP tool."""

    def test_no_contract_returns_invalid(self, contract_mcp):
        """Calling validate_endpoint for a service with no contracts returns valid=False."""
        result = contract_mcp.validate_endpoint(
            service_name="nonexistent-service",
            method="GET",
            path="/api/users",
            response_body=[{"id": "1", "name": "Alice"}],
        )

        assert isinstance(result, dict)
        assert result["valid"] is False
        assert "violations" in result
        assert isinstance(result["violations"], list)
        assert len(result["violations"]) > 0

    def test_valid_response_after_create(self, contract_mcp):
        """Create a contract, then validate a matching response -- should be valid."""
        _create_sample_contract(contract_mcp)

        result = contract_mcp.validate_endpoint(
            service_name="user-service",
            method="GET",
            path="/api/users",
            response_body=[{"id": "1", "name": "Alice"}],
            status_code=200,
        )

        assert isinstance(result, dict)
        assert result["valid"] is True
        assert result["violations"] == []

    def test_invalid_response_returns_violations(self, contract_mcp):
        """Create a contract, then validate with wrong data type -- should report violations."""
        _create_sample_contract(contract_mcp)

        # The contract expects an array of User objects at GET /api/users.
        # Passing a string instead should trigger violations.
        result = contract_mcp.validate_endpoint(
            service_name="user-service",
            method="GET",
            path="/api/users",
            response_body="this-is-not-an-array",
            status_code=200,
        )

        assert isinstance(result, dict)
        assert result["valid"] is False
        assert isinstance(result["violations"], list)
        assert len(result["violations"]) > 0
