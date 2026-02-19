"""MCP client for Build 1 Architect service.

Provides both the legacy ``call_architect_mcp`` function and the
``ArchitectClient`` wrapper class required by the SVC wiring checklist:

  - SVC-001: ArchitectClient.decompose(prd_text)
  - SVC-002: ArchitectClient.get_service_map()
  - SVC-003: ArchitectClient.get_contracts_for_service(service_name)
  - SVC-004: ArchitectClient.get_domain_model()

Also provides ``decompose_prd_basic()`` — a simple heuristic-based fallback
that produces a minimal PRD decomposition without requiring the Architect MCP
server, and ``decompose_prd_with_fallback()`` which tries ``ArchitectClient``
first and falls back to ``decompose_prd_basic()`` when the server is
unavailable (WIRE-011).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 1  # seconds
_SENTINEL = object()  # sentinel for distinguishing "no default" from None


def _server_params():
    """Return StdioServerParameters for the Architect MCP server."""
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command="python",
        args=["-m", "src.architect.mcp_server"],
    )


async def _call_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Low-level helper: open a session, call a tool, return parsed JSON."""
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession

    server_params = _server_params()
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, params)
            if result.content:
                return json.loads(result.content[0].text)
            return {}


# ---------------------------------------------------------------------------
# Legacy function (kept for backward-compat)
# ---------------------------------------------------------------------------

async def call_architect_mcp(prd_text: str, config: object | None = None) -> dict:
    """Call Architect decompose via MCP stdio transport.

    Args:
        prd_text: The full PRD text to decompose.
        config: Optional configuration (unused, for forward compat).

    Returns:
        Dict with service_map, domain_model, contract_stubs, etc.
    """
    return await _call_tool("decompose", {"prd_text": prd_text})


# ---------------------------------------------------------------------------
# ArchitectClient class (SVC-001 through SVC-004)
# ---------------------------------------------------------------------------

class ArchitectClient:
    """Build 2 client wrapper for the Architect MCP server.

    Each method maps to one Architect MCP tool and includes:
    - 3-retry with exponential backoff
    - Safe-default return on error (never raises)
    """

    def __init__(self, session: Any = None) -> None:
        """Initialise with an optional pre-built MCP session.

        When *session* is provided (e.g. in tests) all tool calls are
        dispatched through it directly, bypassing stdio transport.
        """
        self._session = session

    async def _call(self, tool_name: str, params: dict[str, Any], default: Any = _SENTINEL) -> Any:
        """Call a tool with retry logic and safe defaults."""
        _default = {} if default is _SENTINEL else default

        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                if self._session is not None:
                    result = await self._session.call_tool(tool_name, params)
                    if hasattr(result, "isError") and result.isError:
                        data = json.loads(result.content[0].text) if result.content else {}
                        return data  # Return the error payload as-is
                    if result.content:
                        return json.loads(result.content[0].text)
                    return _default
                else:
                    return await _call_tool(tool_name, params)
            except (ConnectionError, OSError, Exception) as exc:
                last_err = exc
                if attempt < _MAX_RETRIES:
                    delay = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "ArchitectClient.%s attempt %d failed: %s — retrying in %ds",
                        tool_name, attempt + 1, exc, delay,
                    )
                    await asyncio.sleep(delay)
        # All retries exhausted — return safe default
        logger.error("ArchitectClient.%s failed after %d retries: %s", tool_name, _MAX_RETRIES, last_err)
        return _default

    async def decompose(self, prd_text: str) -> dict[str, Any] | None:
        """SVC-001: Decompose a PRD into services, domain model, and contracts.

        Returns:
            DecompositionResult dict, or None on failure.
        """
        result = await self._call("decompose", {"prd_text": prd_text}, default=None)
        return result

    async def get_service_map(self, project_name: str | None = None) -> dict[str, Any]:
        """SVC-002: Retrieve the most recent service map.

        Returns:
            ServiceMap dict with project_name, services, generated_at, etc.
        """
        params: dict[str, Any] = {}
        if project_name is not None:
            params["project_name"] = project_name
        return await self._call("get_service_map", params, default={})

    async def get_contracts_for_service(self, service_name: str) -> list[dict[str, Any]]:
        """SVC-003: Get contracts associated with a specific service.

        Returns:
            List of contract dicts with id, role, type, counterparty, summary.
        """
        return await self._call(
            "get_contracts_for_service", {"service_name": service_name}, default=[],
        )

    async def get_domain_model(self, project_name: str | None = None) -> dict[str, Any]:
        """SVC-004: Retrieve the most recent domain model.

        Returns:
            DomainModel dict with entities, relationships, generated_at.
        """
        params: dict[str, Any] = {}
        if project_name is not None:
            params["project_name"] = project_name
        return await self._call("get_domain_model", params, default={})


# ---------------------------------------------------------------------------
# Module-level convenience functions (delegate to bare tool calls)
# ---------------------------------------------------------------------------

async def get_service_map(project_name: str | None = None) -> dict[str, Any]:
    """Retrieve the most recent service map via MCP stdio transport (SVC-002)."""
    params: dict[str, Any] = {}
    if project_name is not None:
        params["project_name"] = project_name
    return await _call_tool("get_service_map", params)


async def get_contracts_for_service(service_name: str) -> list[dict[str, Any]]:
    """Query contracts for a service via MCP stdio transport (SVC-003)."""
    return await _call_tool("get_contracts_for_service", {"service_name": service_name})


async def get_domain_model(project_name: str | None = None) -> dict[str, Any]:
    """Retrieve the most recent domain model via MCP stdio transport (SVC-004)."""
    params: dict[str, Any] = {}
    if project_name is not None:
        params["project_name"] = project_name
    return await _call_tool("get_domain_model", params)


# ---------------------------------------------------------------------------
# WIRE-011 — Fallback: decompose_prd_basic()
# ---------------------------------------------------------------------------

def decompose_prd_basic(prd_text: str) -> dict[str, Any]:
    """Produce a minimal PRD decomposition using simple heuristics.

    This is the **fallback** used by Build 2 when the Architect MCP server
    is unavailable (WIRE-011).  It extracts a naive single-service skeleton
    from the PRD text so the pipeline can proceed without the Architect.

    Args:
        prd_text: The PRD text to decompose.

    Returns:
        A dict with ``services`` (list of service stubs), ``domain_model``
        (empty skeleton), ``contract_stubs`` (empty list), and a
        ``fallback`` flag set to ``True``.
    """
    # Extract a project name from the first non-empty line
    lines = [ln.strip() for ln in prd_text.splitlines() if ln.strip()]
    project_name = lines[0][:80] if lines else "unknown-project"
    # Sanitise to a slug
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-") or "service"

    return {
        "services": [
            {
                "name": slug,
                "description": f"Auto-generated stub from PRD ({len(prd_text)} chars)",
                "endpoints": [],
            }
        ],
        "domain_model": {"entities": [], "relationships": []},
        "contract_stubs": [],
        "fallback": True,
    }


async def decompose_prd_with_fallback(
    prd_text: str,
    client: ArchitectClient | None = None,
) -> dict[str, Any]:
    """Decompose a PRD, trying Architect MCP first with heuristic fallback.

    Implements the WIRE-011 requirement: when the Architect MCP server is
    unavailable, Build 2 falls back to ``decompose_prd_basic()`` so that
    standard PRD decomposition still proceeds.

    Args:
        prd_text: The full PRD text to decompose.
        client: Optional ``ArchitectClient`` instance.  When *None*, the
            function skips MCP and goes straight to fallback.

    Returns:
        A decomposition result dict.  When produced by MCP the dict follows
        the Architect server's schema; when produced by fallback it contains
        a ``"fallback": True`` marker.
    """
    if client is not None:
        try:
            result = await client.decompose(prd_text)
            if result is not None and "error" not in result:
                logger.info("Architect MCP available; using MCP-based decomposition")
                return {**result, "fallback": False}
        except (ConnectionError, ImportError, OSError, Exception) as exc:
            logger.warning(
                "Architect MCP unavailable (%s); falling back to decompose_prd_basic()",
                exc,
            )

    # Fallback: heuristic-based decomposition
    logger.info("Using heuristic fallback: decompose_prd_basic()")
    return decompose_prd_basic(prd_text)
