"""MCP server for the Contract Engine service.

Exposes contract management, validation, breaking-change detection,
implementation tracking, test generation, and compliance checking as
MCP tools over stdio transport.  All tools delegate to the real service
layer -- no mock data.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db
from src.shared.errors import (
    AppError,
    ContractNotFoundError,
    SchemaError,
    ValidationError,
)
from src.shared.models.contracts import ContractCreate, ContractType, ValidateRequest

from src.contract_engine.services.contract_store import ContractStore
from src.contract_engine.services.openapi_validator import validate_openapi
from src.contract_engine.services.asyncapi_validator import validate_asyncapi
from src.contract_engine.services.breaking_change_detector import (
    detect_breaking_changes as _detect_breaking_changes,
)
from src.contract_engine.services.implementation_tracker import ImplementationTracker
from src.contract_engine.services.version_manager import VersionManager
from src.contract_engine.services.test_generator import ContractTestGenerator
from src.contract_engine.services.compliance_checker import ComplianceChecker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP application
# ---------------------------------------------------------------------------
mcp = FastMCP("Contract Engine")

# ---------------------------------------------------------------------------
# Module-level initialisation (database + services)
# ---------------------------------------------------------------------------
_db_path = os.environ.get("DATABASE_PATH", "./data/contracts.db")
_pool = ConnectionPool(_db_path)
init_contracts_db(_pool)

_contract_store = ContractStore(_pool)
_implementation_tracker = ImplementationTracker(_pool)
_version_manager = VersionManager(_pool)
_test_generator = ContractTestGenerator(_pool)
_compliance_checker = ComplianceChecker(_pool)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
def create_contract(
    service_name: str,
    type: str,
    version: str,
    spec: dict,
    build_cycle_id: str | None = None,
) -> dict:
    """Create or update an API contract.

    Validates the contract type, persists the specification via upsert,
    and returns the stored contract entry.

    Args:
        service_name: Name of the service that owns this contract.
        type: Contract type -- one of "openapi", "asyncapi", or "json_schema".
        version: Semantic version string (e.g. "1.0.0").
        spec: The full specification document as a JSON-compatible dict.
        build_cycle_id: Optional build cycle identifier for immutability tracking.

    Returns:
        The persisted contract entry as a JSON-serialisable dict, or an
        ``{"error": "..."}`` dict on validation / schema errors.
    """
    try:
        if type not in ("openapi", "asyncapi", "json_schema"):
            return {"error": f"Invalid contract type: {type!r}. Must be one of: openapi, asyncapi, json_schema"}

        create_obj = ContractCreate(
            service_name=service_name,
            type=ContractType(type),
            version=version,
            spec=spec,
            build_cycle_id=build_cycle_id,
        )
        result = _contract_store.upsert(create_obj)
        return result.model_dump(mode="json")
    except (SchemaError, ValidationError) as exc:
        return {"error": str(exc)}
    except AppError as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_contracts(
    page: int = 1,
    page_size: int = 20,
    service_name: str | None = None,
    contract_type: str | None = None,
    status: str | None = None,
) -> dict:
    """List contracts with optional filtering and pagination.

    Args:
        page: Page number (1-based).
        page_size: Number of items per page (max 100).
        service_name: Filter by owning service name.
        contract_type: Filter by contract type (openapi / asyncapi / json_schema).
        status: Filter by contract status (active / deprecated / draft).

    Returns:
        A paginated response dict containing ``items``, ``total``, ``page``,
        and ``page_size``.
    """
    try:
        result = _contract_store.list(
            page=page,
            page_size=page_size,
            service_name=service_name,
            contract_type=contract_type,
            status=status,
        )
        return result.model_dump(mode="json")
    except AppError as exc:
        return {"error": str(exc)}


@mcp.tool()
def get_contract(contract_id: str) -> dict:
    """Retrieve a single contract by its unique identifier.

    Args:
        contract_id: UUID of the contract to retrieve.

    Returns:
        The contract entry as a JSON-serialisable dict, or
        ``{"error": "..."}`` if the contract does not exist.
    """
    try:
        result = _contract_store.get(contract_id)
        return result.model_dump(mode="json")
    except ContractNotFoundError as exc:
        return {"error": str(exc)}
    except AppError as exc:
        return {"error": str(exc)}


@mcp.tool(name="validate_spec")
def validate_contract(spec: dict, type: str) -> dict:
    """Validate a contract specification without persisting it.

    Dispatches to the appropriate validator based on ``type``:
    - ``"openapi"``  -- structural + $ref validation via openapi-spec-validator / prance
    - ``"asyncapi"`` -- structural validation of AsyncAPI 3.x documents
    - ``"json_schema"`` -- placeholder (returns a warning that validation is not yet implemented)

    Args:
        spec: The specification document to validate.
        type: Contract type -- one of "openapi", "asyncapi", or "json_schema".

    Returns:
        A validation result dict with ``valid``, ``errors``, and ``warnings``
        fields, or ``{"error": "..."}`` on unexpected failures.
    """
    try:
        if type == "openapi":
            result = validate_openapi(spec)
            return result.model_dump(mode="json")
        elif type == "asyncapi":
            result = validate_asyncapi(spec)
            return result.model_dump(mode="json")
        elif type == "json_schema":
            return {
                "valid": True,
                "errors": [],
                "warnings": ["JSON Schema validation not yet implemented"],
            }
        else:
            return {"error": f"Unknown contract type: {type!r}"}
    # Top-level handler: broad catch intentional
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(name="check_breaking_changes")
def detect_breaking_changes(
    contract_id: str,
    new_spec: dict | None = None,
) -> list:
    """Detect breaking changes for a contract.

    If ``new_spec`` is provided, compares the current contract's spec against
    ``new_spec``.  Otherwise, retrieves the version history and returns any
    breaking changes that were detected and recorded when prior versions were
    created.

    Args:
        contract_id: UUID of the contract to check.
        new_spec: Optional new specification to compare against the current one.

    Returns:
        A list of breaking-change dicts (may be empty), or
        ``[{"error": "..."}]`` if the contract is not found.
    """
    try:
        contract = _contract_store.get(contract_id)

        if new_spec is not None:
            changes = _detect_breaking_changes(contract.spec, new_spec)
            return [change.model_dump(mode="json") for change in changes]

        # No new_spec provided — aggregate all breaking changes recorded
        # across the version history.  The VersionManager stores detected
        # breaking changes at version-creation time (comparing old ↔ new
        # specs), so the records are the authoritative source.
        versions = _version_manager.get_version_history(contract_id)
        if not versions:
            return []

        all_changes: list[dict] = []
        for version in versions:
            if version.breaking_changes:
                all_changes.extend(
                    change.model_dump(mode="json")
                    for change in version.breaking_changes
                )
        return all_changes

    except ContractNotFoundError as exc:
        return [{"error": str(exc)}]
    except AppError as exc:
        return [{"error": str(exc)}]


@mcp.tool(name="mark_implemented")
def mark_implementation(
    contract_id: str,
    service_name: str,
    evidence_path: str,
) -> dict:
    """Mark a contract as implemented by a service.

    Records (or updates) an implementation entry linking the contract to the
    service, along with the path to the evidence artifact.

    Args:
        contract_id: UUID of the contract being implemented.
        service_name: Name of the implementing service.
        evidence_path: Filesystem path to the implementation evidence (e.g. test file).

    Returns:
        A response dict with ``marked``, ``total_implementations``, and
        ``all_implemented`` fields, or ``{"error": "..."}`` if the contract
        does not exist.
    """
    try:
        result = _implementation_tracker.mark_implemented(
            contract_id, service_name, evidence_path
        )
        return result.model_dump(mode="json")
    except ContractNotFoundError as exc:
        return {"error": str(exc)}
    except AppError as exc:
        return {"error": str(exc)}


@mcp.tool(name="get_unimplemented_contracts")
def get_unimplemented(service_name: str | None = None) -> list:
    """List contracts that have not yet been fully implemented.

    Args:
        service_name: Optional filter to restrict results to a single service.

    Returns:
        A list of unimplemented-contract dicts, each containing ``id``,
        ``type``, ``version``, ``expected_service``, and ``status``.
    """
    try:
        result = _implementation_tracker.get_unimplemented(service_name)
        return [item.model_dump(mode="json") for item in result]
    except AppError as exc:
        return [{"error": str(exc)}]


@mcp.tool()
def generate_tests(
    contract_id: str,
    framework: str = "pytest",
    include_negative: bool = False,
) -> str:
    """Generate a test suite from a stored contract specification.

    Produces executable test code (Schemathesis for OpenAPI, jsonschema
    validation for AsyncAPI) and caches the result until the spec changes.

    Args:
        contract_id: UUID of the contract to generate tests for.
        framework: Test framework -- ``"pytest"`` or ``"jest"``.
        include_negative: Whether to include negative / 4xx test cases.

    Returns:
        The generated test code as a string, or a JSON-encoded error
        string (e.g. ``'{"error": "..."}'``) if the contract does not exist.
    """
    try:
        result = _test_generator.generate_tests(
            contract_id, framework, include_negative
        )
        return result.test_code
    except ContractNotFoundError as exc:
        return json.dumps({"error": str(exc)})
    except AppError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def check_compliance(
    contract_id: str,
    response_data: dict | None = None,
) -> list:
    """Check runtime response data against a contract's endpoint schemas.

    Validates that the provided response payloads conform to the contracted
    schemas, reporting violations by field, expected type, and severity.

    Args:
        contract_id: UUID of the contract to check against.
        response_data: Mapping of ``"METHOD /path"`` to response body dicts.
            Defaults to an empty dict if not provided.

    Returns:
        A list of compliance-result dicts, one per endpoint checked.  Each
        contains ``endpoint_path``, ``method``, ``compliant``, and
        ``violations``.  Returns ``[{"error": "..."}]`` if the contract
        does not exist.
    """
    try:
        if response_data is None:
            response_data = {}
        result = _compliance_checker.check_compliance(contract_id, response_data)
        return [r.model_dump(mode="json") for r in result]
    except ContractNotFoundError as exc:
        return [{"error": str(exc)}]
    except AppError as exc:
        return [{"error": str(exc)}]


@mcp.tool(name="validate_endpoint")
def validate_endpoint(
    service_name: str,
    method: str,
    path: str,
    response_body: dict,
    status_code: int = 200,
) -> dict:
    """Validate an API response against the contracted schema.

    Looks up the contract for the given service, finds the endpoint matching
    the method and path, and validates the response body against the contracted
    response schema for the specified status code.

    Args:
        service_name: Service that owns the contract.
        method: HTTP method (GET, POST, PUT, PATCH, DELETE).
        path: Endpoint path (e.g. "/api/users").
        response_body: The actual response body to validate.
        status_code: HTTP status code of the response (default 200).

    Returns:
        Dict with 'valid' (bool) and 'violations' (list of violation dicts).
    """
    try:
        # Find the contract for the service
        result = _contract_store.list(service_name=service_name, contract_type="openapi")
        contracts = result.items if hasattr(result, "items") else []

        if not contracts:
            return {
                "valid": False,
                "violations": [
                    {
                        "field": "",
                        "expected": "contract exists",
                        "actual": "no contract found",
                        "severity": "error",
                    }
                ],
            }

        # Use the first active OpenAPI contract for the service
        contract = contracts[0]
        contract_id = contract.id if hasattr(contract, "id") else contract.get("id")

        # Build the response_data dict in the format ComplianceChecker expects
        endpoint_key = f"{method.upper()} {path}"
        response_data = {endpoint_key: response_body}

        # Delegate to the ComplianceChecker
        compliance_results = _compliance_checker.check_compliance(
            contract_id, response_data
        )

        # Aggregate violations from compliance results
        violations: list[dict] = []
        is_valid = True
        for cr in compliance_results:
            cr_dict = cr.model_dump(mode="json") if hasattr(cr, "model_dump") else cr
            if not cr_dict.get("compliant", True):
                is_valid = False
                for v in cr_dict.get("violations", []):
                    violations.append(v)

        return {"valid": is_valid, "violations": violations}

    except ContractNotFoundError as exc:
        return {
            "valid": False,
            "violations": [
                {
                    "field": "",
                    "expected": "contract exists",
                    "actual": str(exc),
                    "severity": "error",
                }
            ],
        }
    except AppError as exc:
        return {
            "valid": False,
            "violations": [
                {
                    "field": "",
                    "expected": "validation success",
                    "actual": str(exc),
                    "severity": "error",
                }
            ],
        }
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error during endpoint validation")
        return {
            "valid": False,
            "violations": [
                {
                    "field": "",
                    "expected": "validation success",
                    "actual": str(exc),
                    "severity": "error",
                }
            ],
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
