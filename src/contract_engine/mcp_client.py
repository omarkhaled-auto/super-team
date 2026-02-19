"""MCP client for Build 1 Contract Engine service.

Provides both bare-function helpers (backward-compatible) and a
``ContractEngineClient`` class that wraps all 9 Contract Engine MCP
tools with retry, safe-default, and session-management logic.

Also provides ``run_api_contract_scan()`` — a filesystem-based fallback that
produces contract validation results without requiring the CE MCP server, and
``get_contracts_with_fallback()`` which tries CE MCP first and falls back
to ``run_api_contract_scan()`` when the server is unavailable (WIRE-009).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WIRE-009 — Filesystem fallback: run_api_contract_scan()
# ---------------------------------------------------------------------------

# Recognised contract file extensions for the fallback scanner.
_CONTRACT_EXTENSIONS: set[str] = {".json", ".yaml", ".yml"}


def run_api_contract_scan(
    project_root: str | Path,
    *,
    extensions: set[str] | None = None,
) -> dict[str, Any]:
    """Scan the filesystem for API contract files as a CE MCP fallback.

    This is the **fallback** used by Build 2 when the Contract Engine MCP
    server is unavailable (WIRE-009).  It walks *project_root* looking for
    contract specification files (JSON/YAML) in common locations such as
    ``contracts/``, ``specs/``, and ``api/`` directories.

    Args:
        project_root: Root directory of the project to scan.
        extensions: Optional set of file extensions to include (e.g.
            ``{".json", ".yaml"}``).  Defaults to ``_CONTRACT_EXTENSIONS``.

    Returns:
        A dict with keys ``project_root``, ``contracts`` (list of contract
        file info dicts), ``total_contracts``, and ``fallback`` flag set to
        ``True``.
    """
    root = Path(project_root)
    if extensions is None:
        extensions = _CONTRACT_EXTENSIONS

    contracts: list[dict[str, Any]] = []
    contract_dirs = {"contracts", "specs", "api", "openapi", "asyncapi"}

    if root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden dirs & common non-source dirs
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".")
                and d not in {"node_modules", "__pycache__", ".venv", "venv"}
            ]
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext in extensions:
                    fpath = Path(dirpath) / fname
                    relative = fpath.relative_to(root)
                    # Only include files in contract-related dirs or at root
                    parent_parts = {p.lower() for p in relative.parts[:-1]}
                    if parent_parts & contract_dirs or not parent_parts:
                        try:
                            content_text = fpath.read_text(encoding="utf-8")
                            spec = json.loads(content_text) if ext == ".json" else {}
                        except Exception:
                            spec = {}
                        contracts.append({
                            "file_path": str(fpath),
                            "relative_path": str(relative),
                            "extension": ext,
                            "spec": spec,
                            "valid": bool(spec),
                        })

    return {
        "project_root": str(root),
        "contracts": contracts,
        "total_contracts": len(contracts),
        "fallback": True,
    }


async def get_contracts_with_fallback(
    project_root: str | Path,
    client: "ContractEngineClient | None" = None,
) -> dict[str, Any]:
    """Obtain contract scan results, trying CE MCP first with fallback.

    Implements the WIRE-009 requirement: when the Contract Engine MCP
    server is unavailable, Build 2 falls back to ``run_api_contract_scan()``.

    Args:
        project_root: Root directory of the project.
        client: Optional ``ContractEngineClient`` instance.  When
            *None*, the function skips MCP and goes straight to fallback.

    Returns:
        A contract scan result dict.  When produced by MCP the dict follows
        the CE server's schema; when produced by fallback it contains a
        ``"fallback": True`` marker.
    """
    if client is not None:
        try:
            result = await client.list_contracts()
            if result and "error" not in result:
                logger.info("CE MCP available; using MCP-based contract data")
                return {"project_root": str(project_root), "fallback": False, **result}
        except (ConnectionError, ImportError, OSError, Exception) as exc:
            logger.warning(
                "CE MCP unavailable (%s); falling back to run_api_contract_scan()",
                exc,
            )

    # Fallback: filesystem-based contract scan
    logger.info("Using filesystem fallback: run_api_contract_scan()")
    return run_api_contract_scan(project_root)


# ---------------------------------------------------------------------------
# Retry / backoff constants
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BACKOFF_BASE = 1  # seconds


async def _retry_call(
    session: Any,
    tool_name: str,
    params: dict,
    *,
    max_retries: int = _MAX_RETRIES,
    backoff_base: float = _BACKOFF_BASE,
) -> Any:
    """Call ``session.call_tool`` with exponential-backoff retry.

    Returns the parsed JSON result on success.  On exhausted retries
    the last exception is re-raised.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            result = await session.call_tool(tool_name, params)
            if result.content:
                return json.loads(result.content[0].text)
            return {}
        except (ConnectionError, OSError, EOFError) as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = backoff_base * (2 ** attempt)
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ContractEngineClient class
# ---------------------------------------------------------------------------


class ContractEngineClient:
    """Build 2 client wrapper for the Contract Engine MCP server.

    Wraps all 9 MCP tools exposed by the server:
      - create_contract   (SVC-010a)
      - validate_spec     (SVC-010b)
      - list_contracts    (SVC-010c)
      - get_contract      (SVC-005)
      - validate_endpoint (SVC-006)
      - generate_tests    (SVC-007)
      - check_breaking_changes (SVC-008)
      - mark_implemented  (SVC-009)
      - get_unimplemented_contracts (SVC-010)

    Each method:
      1. Retries up to 3 times with exponential backoff on connection errors.
      2. Returns a safe default (never raises) when the server is unavailable.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    # -- SVC-010a: create_contract -----------------------------------------

    async def create_contract(
        self,
        service_name: str,
        type: str,
        version: str,
        spec: dict,
        build_cycle_id: str | None = None,
    ) -> dict:
        """Create or update an API contract."""
        params: dict[str, Any] = {
            "service_name": service_name,
            "type": type,
            "version": version,
            "spec": spec,
        }
        if build_cycle_id:
            params["build_cycle_id"] = build_cycle_id
        try:
            return await _retry_call(self._session, "create_contract", params)
        except Exception as exc:
            logger.warning("create_contract failed: %s", exc)
            return {"error": str(exc)}

    # -- SVC-010b: validate_spec -------------------------------------------

    async def validate_spec(self, spec: dict, type: str) -> dict:
        """Validate a contract specification without persisting it."""
        try:
            return await _retry_call(
                self._session, "validate_spec", {"spec": spec, "type": type},
            )
        except Exception as exc:
            logger.warning("validate_spec failed: %s", exc)
            return {"error": str(exc)}

    # -- SVC-010c: list_contracts ------------------------------------------

    async def list_contracts(
        self,
        service_name: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List contracts with optional filtering."""
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if service_name:
            params["service_name"] = service_name
        try:
            return await _retry_call(self._session, "list_contracts", params)
        except Exception as exc:
            logger.warning("list_contracts failed: %s", exc)
            return {"error": str(exc)}

    # -- SVC-005: get_contract ---------------------------------------------

    async def get_contract(self, contract_id: str) -> dict:
        """Retrieve a single contract by its unique identifier."""
        try:
            return await _retry_call(
                self._session, "get_contract", {"contract_id": contract_id},
            )
        except Exception as exc:
            logger.warning("get_contract failed: %s", exc)
            return {"error": str(exc)}

    # -- SVC-006: validate_endpoint ----------------------------------------

    async def validate_endpoint(
        self,
        service_name: str,
        method: str,
        path: str,
        response_body: dict,
        status_code: int = 200,
    ) -> dict:
        """Validate an API response against the contracted schema."""
        try:
            return await _retry_call(
                self._session,
                "validate_endpoint",
                {
                    "service_name": service_name,
                    "method": method,
                    "path": path,
                    "response_body": response_body,
                    "status_code": status_code,
                },
            )
        except Exception as exc:
            logger.warning("validate_endpoint failed: %s", exc)
            return {"valid": False, "violations": [{"error": str(exc)}]}

    # -- SVC-007: generate_tests -------------------------------------------

    async def generate_tests(
        self,
        contract_id: str,
        framework: str = "pytest",
        include_negative: bool = False,
    ) -> str:
        """Generate a test suite from a stored contract specification."""
        try:
            result = await _retry_call(
                self._session,
                "generate_tests",
                {
                    "contract_id": contract_id,
                    "framework": framework,
                    "include_negative": include_negative,
                },
            )
            if isinstance(result, str):
                return result
            if isinstance(result, dict) and "error" in result:
                return ""
            return str(result)
        except Exception as exc:
            logger.warning("generate_tests failed: %s", exc)
            return ""

    # -- SVC-008: check_breaking_changes -----------------------------------

    async def check_breaking_changes(
        self,
        contract_id: str,
        new_spec: dict | None = None,
    ) -> list:
        """Detect breaking changes for a contract."""
        params: dict[str, Any] = {"contract_id": contract_id}
        if new_spec is not None:
            params["new_spec"] = new_spec
        try:
            result = await _retry_call(
                self._session, "check_breaking_changes", params,
            )
            return result if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("check_breaking_changes failed: %s", exc)
            return []

    # -- SVC-009: mark_implemented -----------------------------------------

    async def mark_implemented(
        self,
        contract_id: str,
        service_name: str,
        evidence_path: str,
    ) -> dict:
        """Mark a contract as implemented by a service."""
        try:
            return await _retry_call(
                self._session,
                "mark_implemented",
                {
                    "contract_id": contract_id,
                    "service_name": service_name,
                    "evidence_path": evidence_path,
                },
            )
        except Exception as exc:
            logger.warning("mark_implemented failed: %s", exc)
            return {"error": str(exc)}

    # -- SVC-010: get_unimplemented_contracts ------------------------------

    async def get_unimplemented_contracts(
        self,
        service_name: str | None = None,
    ) -> list:
        """List contracts that have not yet been fully implemented."""
        params: dict[str, Any] = {}
        if service_name:
            params["service_name"] = service_name
        try:
            result = await _retry_call(
                self._session, "get_unimplemented_contracts", params,
            )
            return result if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("get_unimplemented_contracts failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Backward-compatible bare functions (original API)
# ---------------------------------------------------------------------------


async def create_contract(
    service_name: str,
    type: str,
    version: str,
    spec: dict,
    build_cycle_id: str | None = None,
) -> dict:
    """Create a contract via the Contract Engine MCP server.

    Args:
        service_name: Name of the service that owns this contract.
        type: Contract type (openapi, asyncapi, json_schema).
        version: Semantic version string.
        spec: The full specification document.
        build_cycle_id: Optional build cycle identifier.

    Returns:
        The persisted contract entry as a dict.
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.contract_engine.mcp_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            params: dict = {
                "service_name": service_name,
                "type": type,
                "version": version,
                "spec": spec,
            }
            if build_cycle_id:
                params["build_cycle_id"] = build_cycle_id
            result = await session.call_tool("create_contract", params)
            return json.loads(result.content[0].text) if result.content else {}


async def validate_spec(spec: dict, type: str) -> dict:
    """Validate a contract specification without persisting it.

    Args:
        spec: The specification document to validate.
        type: Contract type (openapi, asyncapi, json_schema).

    Returns:
        Validation result dict with valid, errors, and warnings.
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.contract_engine.mcp_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "validate_spec", {"spec": spec, "type": type},
            )
            return json.loads(result.content[0].text) if result.content else {}


async def list_contracts(
    service_name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """List contracts with optional filtering.

    Args:
        service_name: Optional filter by service name.
        page: Page number (1-based).
        page_size: Number of items per page.

    Returns:
        Paginated response dict with items, total, page, page_size.
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.contract_engine.mcp_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            params: dict = {"page": page, "page_size": page_size}
            if service_name:
                params["service_name"] = service_name
            result = await session.call_tool("list_contracts", params)
            return json.loads(result.content[0].text) if result.content else {}


async def get_contract(contract_id: str) -> dict:
    """Retrieve a single contract by its unique identifier.

    Args:
        contract_id: UUID of the contract to retrieve.

    Returns:
        The contract entry as a dict, or an error dict if not found.
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.contract_engine.mcp_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_contract", {"contract_id": contract_id},
            )
            return json.loads(result.content[0].text) if result.content else {}


async def validate_endpoint(
    service_name: str,
    method: str,
    path: str,
    response_body: dict,
    status_code: int = 200,
) -> dict:
    """Validate an API response against the contracted schema.

    Args:
        service_name: Service that owns the contract.
        method: HTTP method (GET, POST, PUT, PATCH, DELETE).
        path: Endpoint path (e.g. "/api/users").
        response_body: The actual response body to validate.
        status_code: HTTP status code of the response (default 200).

    Returns:
        Dict with 'valid' (bool) and 'violations' (list of violation dicts).
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.contract_engine.mcp_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "validate_endpoint",
                {
                    "service_name": service_name,
                    "method": method,
                    "path": path,
                    "response_body": response_body,
                    "status_code": status_code,
                },
            )
            return json.loads(result.content[0].text) if result.content else {}


async def generate_tests(
    contract_id: str,
    framework: str = "pytest",
    include_negative: bool = False,
) -> str:
    """Generate a test suite from a stored contract specification.

    Args:
        contract_id: UUID of the contract to generate tests for.
        framework: Test framework -- "pytest" or "jest".
        include_negative: Whether to include negative / 4xx test cases.

    Returns:
        The generated test code as a string, or a JSON-encoded error string.
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.contract_engine.mcp_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "generate_tests",
                {
                    "contract_id": contract_id,
                    "framework": framework,
                    "include_negative": include_negative,
                },
            )
            if result.content:
                data = json.loads(result.content[0].text)
                return data if isinstance(data, str) else json.dumps(data)
            return ""


async def check_breaking_changes(
    contract_id: str,
    new_spec: dict | None = None,
) -> list:
    """Detect breaking changes for a contract.

    If ``new_spec`` is provided, compares the current contract's spec against
    ``new_spec``.  Otherwise, returns any previously recorded breaking changes.

    Args:
        contract_id: UUID of the contract to check.
        new_spec: Optional new specification to compare against the current one.

    Returns:
        A list of breaking-change dicts (may be empty).
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.contract_engine.mcp_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            params: dict = {"contract_id": contract_id}
            if new_spec is not None:
                params["new_spec"] = new_spec
            result = await session.call_tool("check_breaking_changes", params)
            return json.loads(result.content[0].text) if result.content else []


async def mark_implemented(
    contract_id: str,
    service_name: str,
    evidence_path: str,
) -> dict:
    """Mark a contract as implemented by a service.

    Args:
        contract_id: UUID of the contract being implemented.
        service_name: Name of the implementing service.
        evidence_path: Filesystem path to the implementation evidence.

    Returns:
        A result dict with marked, total, and all_implemented fields.
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.contract_engine.mcp_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "mark_implemented",
                {
                    "contract_id": contract_id,
                    "service_name": service_name,
                    "evidence_path": evidence_path,
                },
            )
            return json.loads(result.content[0].text) if result.content else {}


async def get_unimplemented_contracts(
    service_name: str | None = None,
) -> list:
    """List contracts that have not yet been fully implemented.

    Args:
        service_name: Optional filter to restrict results to a single service.

    Returns:
        A list of unimplemented-contract dicts.
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.contract_engine.mcp_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            params: dict = {}
            if service_name is not None:
                params["service_name"] = service_name
            result = await session.call_tool(
                "get_unimplemented_contracts", params,
            )
            return json.loads(result.content[0].text) if result.content else []
