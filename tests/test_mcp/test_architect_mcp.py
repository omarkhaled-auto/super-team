"""Integration tests for the Architect MCP server.

Tests the MCP tool functions exposed by ``src.architect.mcp_server`` by
patching module-level database and store instances with temporary ones so
each test runs against an isolated SQLite database.
"""
from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_architect_db
from src.architect.storage.service_map_store import ServiceMapStore
from src.architect.storage.domain_model_store import DomainModelStore

# ---------------------------------------------------------------------------
# Sample PRD text used across multiple tests
# ---------------------------------------------------------------------------

SAMPLE_PRD = """
# E-Commerce Platform PRD

## Overview
Build a modern e-commerce platform with user management, product catalog,
and order processing.  The backend will be built in Python using the FastAPI
framework with a PostgreSQL database.

## Services

### User Service
- Manages user accounts and authentication
- Stores user profiles and preferences

### Product Service
- Manages product catalog and inventory
- Handles product search and filtering

### Order Service
- Processes customer orders
- Manages order lifecycle and fulfillment

## Entities

### User
- id: uuid
- email: string
- name: string
- status: string

### Product
- id: uuid
- name: string
- price: number
- stock: integer

### Order
- id: uuid
- user_id: uuid
- total: number
- status: string

## Relationships
- User has many Orders
- Order references Product
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def architect_mcp(tmp_path, monkeypatch):
    """Set up the Architect MCP server with a temporary database.

    Patches the module-level connection pool and store objects so that all
    tool functions operate against an isolated, ephemeral SQLite file.
    """
    db_path = str(tmp_path / "architect_test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    import src.architect.mcp_server as mod

    pool = ConnectionPool(db_path)
    init_architect_db(pool)

    monkeypatch.setattr(mod, "pool", pool)
    monkeypatch.setattr(mod, "service_map_store", ServiceMapStore(pool))
    monkeypatch.setattr(mod, "domain_model_store", DomainModelStore(pool))

    yield mod

    pool.close()


# ---------------------------------------------------------------------------
# MCP instance sanity checks
# ---------------------------------------------------------------------------


class TestArchitectMCPInstance:
    """Verify the FastMCP instance is correctly wired."""

    def test_mcp_is_fastmcp_instance(self, architect_mcp):
        assert isinstance(architect_mcp.mcp, FastMCP)

    def test_mcp_has_registered_tools(self, architect_mcp):
        tools = architect_mcp.mcp._tool_manager._tools
        assert "decompose" in tools
        assert "get_service_map" in tools
        assert "get_domain_model" in tools
        assert "get_contracts_for_service" in tools

    def test_mcp_name_is_architect(self, architect_mcp):
        assert architect_mcp.mcp.name == "Architect"


# ---------------------------------------------------------------------------
# decompose_prd tool
# ---------------------------------------------------------------------------


class TestDecomposePrd:
    """Tests for the ``decompose_prd`` MCP tool."""

    def test_valid_prd_returns_expected_keys(self, architect_mcp):
        result = architect_mcp.decompose_prd(SAMPLE_PRD)

        assert isinstance(result, dict)
        assert "error" not in result
        assert "service_map" in result
        assert "domain_model" in result
        assert "contract_stubs" in result
        assert "validation_issues" in result
        assert "interview_questions" in result

    def test_valid_prd_service_map_is_dict(self, architect_mcp):
        result = architect_mcp.decompose_prd(SAMPLE_PRD)
        assert isinstance(result["service_map"], dict)

    def test_valid_prd_domain_model_is_dict(self, architect_mcp):
        result = architect_mcp.decompose_prd(SAMPLE_PRD)
        assert isinstance(result["domain_model"], dict)

    def test_valid_prd_contract_stubs_is_list(self, architect_mcp):
        result = architect_mcp.decompose_prd(SAMPLE_PRD)
        assert isinstance(result["contract_stubs"], list)
        assert len(result["contract_stubs"]) > 0

    def test_valid_prd_validation_issues_is_list(self, architect_mcp):
        result = architect_mcp.decompose_prd(SAMPLE_PRD)
        assert isinstance(result["validation_issues"], list)

    def test_valid_prd_interview_questions_is_list(self, architect_mcp):
        result = architect_mcp.decompose_prd(SAMPLE_PRD)
        assert isinstance(result["interview_questions"], list)

    def test_invalid_prd_too_short_returns_error(self, architect_mcp):
        result = architect_mcp.decompose_prd("abc")
        assert isinstance(result, dict)
        assert "error" in result

    def test_invalid_prd_empty_string_returns_error(self, architect_mcp):
        result = architect_mcp.decompose_prd("")
        assert isinstance(result, dict)
        assert "error" in result

    def test_service_map_contains_project_name(self, architect_mcp):
        result = architect_mcp.decompose_prd(SAMPLE_PRD)
        service_map = result["service_map"]
        assert "project_name" in service_map

    def test_domain_model_contains_entities(self, architect_mcp):
        result = architect_mcp.decompose_prd(SAMPLE_PRD)
        domain_model = result["domain_model"]
        assert "entities" in domain_model


# ---------------------------------------------------------------------------
# get_service_map tool
# ---------------------------------------------------------------------------


class TestGetServiceMap:
    """Tests for the ``get_service_map`` MCP tool."""

    def test_empty_db_returns_error(self, architect_mcp):
        result = architect_mcp.get_service_map()
        assert isinstance(result, dict)
        assert result == {"error": "No service map found"}

    def test_returns_service_map_after_decompose(self, architect_mcp):
        architect_mcp.decompose_prd(SAMPLE_PRD)

        result = architect_mcp.get_service_map()
        assert isinstance(result, dict)
        assert "error" not in result
        assert "project_name" in result

    def test_filter_by_project_name_no_match(self, architect_mcp):
        architect_mcp.decompose_prd(SAMPLE_PRD)

        result = architect_mcp.get_service_map(project_name="NonExistentProject")
        assert isinstance(result, dict)
        assert result == {"error": "No service map found"}

    def test_filter_by_correct_project_name(self, architect_mcp):
        decomposed = architect_mcp.decompose_prd(SAMPLE_PRD)
        project_name = decomposed["service_map"]["project_name"]

        result = architect_mcp.get_service_map(project_name=project_name)
        assert isinstance(result, dict)
        assert "error" not in result
        assert result["project_name"] == project_name


# ---------------------------------------------------------------------------
# get_domain_model tool
# ---------------------------------------------------------------------------


class TestGetDomainModel:
    """Tests for the ``get_domain_model`` MCP tool."""

    def test_empty_db_returns_error(self, architect_mcp):
        result = architect_mcp.get_domain_model()
        assert isinstance(result, dict)
        assert result == {"error": "No domain model found"}

    def test_returns_domain_model_after_decompose(self, architect_mcp):
        architect_mcp.decompose_prd(SAMPLE_PRD)

        result = architect_mcp.get_domain_model()
        assert isinstance(result, dict)
        assert "error" not in result
        assert "entities" in result

    def test_filter_by_project_name_no_match(self, architect_mcp):
        architect_mcp.decompose_prd(SAMPLE_PRD)

        result = architect_mcp.get_domain_model(project_name="NonExistentProject")
        assert isinstance(result, dict)
        assert result == {"error": "No domain model found"}

    def test_filter_by_correct_project_name(self, architect_mcp):
        decomposed = architect_mcp.decompose_prd(SAMPLE_PRD)
        project_name = decomposed["service_map"]["project_name"]

        result = architect_mcp.get_domain_model(project_name=project_name)
        assert isinstance(result, dict)
        assert "error" not in result
        assert "entities" in result


# ---------------------------------------------------------------------------
# get_contracts_for_service tool
# ---------------------------------------------------------------------------


class TestGetContractsForService:
    """Tests for the ``get_contracts_for_service`` MCP tool."""

    def test_no_service_map_returns_error(self, architect_mcp):
        result = architect_mcp.get_contracts_for_service("any-service")
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    def test_service_not_found_returns_error(self, architect_mcp):
        architect_mcp.decompose_prd(SAMPLE_PRD)

        result = architect_mcp.get_contracts_for_service("nonexistent")
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    def test_service_with_no_contracts_returns_empty_or_results(self, architect_mcp):
        decomposed = architect_mcp.decompose_prd(SAMPLE_PRD)
        services = decomposed["service_map"]["services"]
        assert len(services) > 0
        first_service_name = services[0]["name"]

        result = architect_mcp.get_contracts_for_service(first_service_name)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tool registration count
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify expected number of tools are registered."""

    def test_mcp_tool_count_is_4(self, architect_mcp):
        tools = architect_mcp.mcp._tool_manager._tools
        assert len(tools) == 4
