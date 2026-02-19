"""MCP server for the Architect service.

Exposes the Architect's decomposition pipeline and query capabilities as
MCP tools over stdio transport.  Each tool delegates to the real service
functions -- no mock data is ever returned.

Environment variables (typically set via .mcp.json):
    DATABASE_PATH       -- Path to the SQLite database file.
    CONTRACT_ENGINE_URL -- URL of the Contract Engine service.

Usage:
    python -m src.architect.mcp_server
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_architect_db
from src.shared.errors import AppError, ParsingError

from src.architect.services.prd_parser import parse_prd
from src.architect.services.service_boundary import identify_boundaries, build_service_map
from src.architect.services.domain_modeler import build_domain_model
from src.architect.services.validator import validate_decomposition
from src.architect.services.contract_generator import generate_contract_stubs
from src.architect.storage.service_map_store import ServiceMapStore
from src.architect.storage.domain_model_store import DomainModelStore

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("architect.mcp")

# ---------------------------------------------------------------------------
# Module-level initialisation
# ---------------------------------------------------------------------------

_database_path: str = os.environ.get("DATABASE_PATH", "./data/architect.db")

pool = ConnectionPool(_database_path)
init_architect_db(pool)

service_map_store = ServiceMapStore(pool)
domain_model_store = DomainModelStore(pool)

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("Architect")


@mcp.tool(name="decompose")
def decompose_prd(prd_text: str) -> dict[str, Any]:
    """Decompose a Product Requirements Document into services, domain model, and contracts.

    Runs the full Architect decomposition pipeline:
      1. Parse the PRD text into structured data.
      2. Identify service boundaries using aggregate-root analysis.
      3. Build a service map with technology stack hints.
      4. Build a domain model with entities, relationships, and state machines.
      5. Validate the decomposition for structural issues.
      6. Generate OpenAPI 3.1 contract stubs for each service.
      7. Persist the service map and domain model to the database.

    Args:
        prd_text: The full text of the PRD document (Markdown or plain text).

    Returns:
        A dictionary containing:
          - service_map: The decomposed service map.
          - domain_model: The domain model with entities and relationships.
          - contract_stubs: OpenAPI 3.1 specs for each service.
          - validation_issues: List of detected structural issues (may be empty).
          - interview_questions: Clarification questions for ambiguous requirements.
    """
    try:
        # Step 1: Parse PRD
        parsed = parse_prd(prd_text)

        # Step 2: Identify service boundaries
        boundaries = identify_boundaries(parsed)

        # Step 3: Build service map with real PRD hash
        prd_hash = hashlib.sha256(prd_text.encode("utf-8")).hexdigest()
        service_map = build_service_map(parsed, boundaries)
        service_map = service_map.model_copy(update={"prd_hash": prd_hash})

        # Step 4: Build domain model
        domain_model = build_domain_model(parsed, boundaries)

        # Step 5: Validate decomposition
        validation_issues = validate_decomposition(service_map, domain_model)

        # Step 6: Generate contract stubs
        contract_stubs = generate_contract_stubs(service_map, domain_model)

        # Step 7: Persist results
        service_map_store.save(service_map)
        domain_model_store.save(domain_model, service_map.project_name)

        return {
            "service_map": service_map.model_dump(mode="json"),
            "domain_model": domain_model.model_dump(mode="json"),
            "contract_stubs": contract_stubs,
            "validation_issues": validation_issues,
            "interview_questions": parsed.interview_questions,
        }

    except ParsingError as exc:
        logger.warning("PRD parsing failed: %s", exc)
        return {"error": str(exc)}
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error during decomposition")
        return {"error": str(exc)}


@mcp.tool()
def get_service_map(project_name: str | None = None) -> dict[str, Any]:
    """Retrieve the most recent service map, optionally filtered by project name.

    Args:
        project_name: Optional project name to filter by.  When omitted the
                      latest service map across all projects is returned.

    Returns:
        The service map as a JSON-serialisable dictionary, or an error dict
        if no service map is found.
    """
    try:
        result = service_map_store.get_latest(project_name)
        if result is None:
            return {"error": "No service map found"}
        return result.model_dump(mode="json")
    except AppError as exc:
        logger.warning("Error retrieving service map: %s", exc)
        return {"error": str(exc)}
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error retrieving service map")
        return {"error": str(exc)}


@mcp.tool()
def get_domain_model(project_name: str | None = None) -> dict[str, Any]:
    """Retrieve the most recent domain model, optionally filtered by project name.

    Args:
        project_name: Optional project name to filter by.  When omitted the
                      latest domain model across all projects is returned.

    Returns:
        The domain model as a JSON-serialisable dictionary, or an error dict
        if no domain model is found.
    """
    try:
        result = domain_model_store.get_latest(project_name)
        if result is None:
            return {"error": "No domain model found"}
        return result.model_dump(mode="json")
    except AppError as exc:
        logger.warning("Error retrieving domain model: %s", exc)
        return {"error": str(exc)}
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error retrieving domain model")
        return {"error": str(exc)}


@mcp.tool(name="get_contracts_for_service")
def get_contracts_for_service(service_name: str) -> list[dict[str, Any]]:
    """Query service map for contracts associated with a specific service.

    Looks up the service in the latest service map, then queries the Contract
    Engine for each contract referenced by the service.

    Args:
        service_name: Name of the service to query contracts for.

    Returns:
        A list of contract dicts with id, role, type, counterparty, summary.
    """
    try:
        # 1. Get the latest service map
        latest_map = service_map_store.get_latest()
        if latest_map is None:
            return [{"error": "No service map found"}]

        # 2. Find the service by name
        target_service = None
        for svc in latest_map.services:
            if svc.name == service_name:
                target_service = svc
                break

        if target_service is None:
            return [{"error": f"Service {service_name!r} not found in service map"}]

        # 3. Collect provides_contracts and consumes_contracts
        contract_refs: list[tuple[str, str]] = []  # (contract_id, role)
        for cid in target_service.provides_contracts:
            contract_refs.append((cid, "provider"))
        for cid in target_service.consumes_contracts:
            contract_refs.append((cid, "consumer"))

        if not contract_refs:
            return []

        # 4. For each contract ID, call Contract Engine via httpx
        contract_engine_url = os.environ.get(
            "CONTRACT_ENGINE_URL", "http://localhost:8002"
        )
        results: list[dict[str, Any]] = []

        with httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0),
        ) as client:
            for contract_id, role in contract_refs:
                try:
                    resp = client.get(
                        f"{contract_engine_url}/api/contracts/{contract_id}"
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        # Determine counterparty: for provider contracts, consumers
                        # are the counterparty; for consumer contracts, the owning
                        # service is the counterparty.
                        counterparty = (
                            data.get("service_name", "unknown")
                            if role == "consumer"
                            else service_name
                        )
                        results.append({
                            "id": data.get("id", contract_id),
                            "role": role,
                            "type": data.get("type", "unknown"),
                            "counterparty": counterparty,
                            "summary": (
                                f"{data.get('type', 'unknown')} contract "
                                f"v{data.get('version', '?')} for "
                                f"{data.get('service_name', 'unknown')}"
                            ),
                        })
                    else:
                        results.append({
                            "id": contract_id,
                            "role": role,
                            "type": "unknown",
                            "counterparty": "unknown",
                            "summary": f"Contract {contract_id} not found (HTTP {resp.status_code})",
                        })
                except httpx.HTTPError as http_exc:
                    logger.warning(
                        "Failed to fetch contract %s: %s", contract_id, http_exc
                    )
                    results.append({
                        "id": contract_id,
                        "role": role,
                        "type": "unknown",
                        "counterparty": "unknown",
                        "summary": f"Failed to fetch contract: {http_exc}",
                    })

        return results

    except AppError as exc:
        logger.warning("Error fetching contracts for service: %s", exc)
        return [{"error": str(exc)}]
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error fetching contracts for service")
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
