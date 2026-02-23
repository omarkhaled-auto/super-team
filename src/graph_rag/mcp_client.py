"""MCP client wrapper for calling Graph RAG MCP tools via an MCP session.

Provides ``GraphRAGClient`` -- an async wrapper around the 7 Graph RAG MCP
tools.  Each method calls the appropriate tool on the session and returns a
parsed ``dict``.  On any MCP/transport error, methods return safe defaults
(``{"success": False, "error": ...}`` or empty dicts) rather than raising,
so callers can always proceed to fallback logic without exception handling.

This follows the same pattern as
``src.codebase_intelligence.mcp_client.CodebaseIntelligenceClient``.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class GraphRAGClient:
    """Async wrapper for calling Graph RAG MCP tools via an MCP session.

    Parameters
    ----------
    session:
        An already-initialised MCP ``ClientSession`` (or compatible mock).
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Tool 1 -- build_knowledge_graph
    # ------------------------------------------------------------------

    async def build_knowledge_graph(
        self,
        project_name: str = "",
        force_rebuild: bool = True,
        service_interfaces_json: str = "",
    ) -> dict[str, Any]:
        """Build or rebuild the knowledge graph from all existing data stores.

        Returns a stats dict on success, or ``{"success": False, "error": ...}``
        on failure.
        """
        try:
            result = await self._session.call_tool(
                "build_knowledge_graph",
                {
                    "project_name": project_name,
                    "force_rebuild": force_rebuild,
                    "service_interfaces_json": service_interfaces_json,
                },
            )
            return _parse_tool_result(result)
        except Exception as e:
            logger.warning("build_knowledge_graph failed: %s", e)
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Tool 2 -- get_service_context
    # ------------------------------------------------------------------

    async def get_service_context(
        self,
        service_name: str,
        **options: Any,
    ) -> dict[str, Any]:
        """Retrieve a structured context block for a specific service.

        Supported keyword options: ``include_consumed_apis``,
        ``include_provided_apis``, ``include_events``,
        ``include_entities``, ``include_dependencies``, ``max_depth``.

        Returns a ``ServiceContext``-shaped dict, or a safe default on
        failure.
        """
        params: dict[str, Any] = {"service_name": service_name}
        params.update(options)
        try:
            result = await self._session.call_tool(
                "get_service_context", params
            )
            return _parse_tool_result(result)
        except Exception as e:
            logger.warning("get_service_context failed: %s", e)
            return {"service_name": service_name, "error": str(e)}

    # ------------------------------------------------------------------
    # Tool 3 -- query_graph_neighborhood
    # ------------------------------------------------------------------

    async def query_graph_neighborhood(
        self,
        node_id: str,
        **options: Any,
    ) -> dict[str, Any]:
        """Extract the N-hop neighborhood around a graph node.

        Supported keyword options: ``radius``, ``undirected``,
        ``filter_node_types``, ``filter_edge_types``, ``max_nodes``.
        """
        params: dict[str, Any] = {"node_id": node_id}
        params.update(options)
        try:
            result = await self._session.call_tool(
                "query_graph_neighborhood", params
            )
            return _parse_tool_result(result)
        except Exception as e:
            logger.warning("query_graph_neighborhood failed: %s", e)
            return {
                "center_node": {},
                "nodes": [],
                "edges": [],
                "total_nodes_in_neighborhood": 0,
                "truncated": False,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # Tool 4 -- hybrid_search
    # ------------------------------------------------------------------

    async def hybrid_search(
        self,
        query: str,
        **options: Any,
    ) -> dict[str, Any]:
        """Combine semantic vector search with graph-structural re-ranking.

        Supported keyword options: ``n_results``, ``anchor_node_id``,
        ``node_types``, ``service_name``, ``semantic_weight``,
        ``graph_weight``.
        """
        params: dict[str, Any] = {"query": query}
        params.update(options)
        try:
            result = await self._session.call_tool("hybrid_search", params)
            return _parse_tool_result(result)
        except Exception as e:
            logger.warning("hybrid_search failed: %s", e)
            return {"results": [], "query": query, "error": str(e)}

    # ------------------------------------------------------------------
    # Tool 5 -- find_cross_service_impact
    # ------------------------------------------------------------------

    async def find_cross_service_impact(
        self,
        node_id: str,
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """Find all cross-service entities impacted by a change at *node_id*.

        Returns an impact analysis dict, or a safe default on failure.
        """
        try:
            result = await self._session.call_tool(
                "find_cross_service_impact",
                {
                    "node_id": node_id,
                    "max_depth": max_depth,
                },
            )
            return _parse_tool_result(result)
        except Exception as e:
            logger.warning("find_cross_service_impact failed: %s", e)
            return {
                "source_node": node_id,
                "source_service": "",
                "impacted_services": [],
                "impacted_contracts": [],
                "impacted_entities": [],
                "total_impacted_nodes": 0,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # Tool 6 -- validate_service_boundaries
    # ------------------------------------------------------------------

    async def validate_service_boundaries(
        self,
        resolution: float = 1.0,
    ) -> dict[str, Any]:
        """Validate service boundaries via Louvain community detection.

        Returns a boundary validation dict, or a safe default on failure.
        """
        try:
            result = await self._session.call_tool(
                "validate_service_boundaries",
                {"resolution": resolution},
            )
            return _parse_tool_result(result)
        except Exception as e:
            logger.warning("validate_service_boundaries failed: %s", e)
            return {
                "communities_detected": 0,
                "services_declared": 0,
                "alignment_score": 0.0,
                "misplaced_files": [],
                "isolated_files": [],
                "service_coupling": [],
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # Tool 7 -- check_cross_service_events
    # ------------------------------------------------------------------

    async def check_cross_service_events(
        self,
        service_name: str = "",
    ) -> dict[str, Any]:
        """Validate cross-service event publisher/consumer matching.

        Returns an event validation dict, or a safe default on failure.
        """
        params: dict[str, Any] = {}
        if service_name:
            params["service_name"] = service_name
        try:
            result = await self._session.call_tool(
                "check_cross_service_events", params
            )
            return _parse_tool_result(result)
        except Exception as e:
            logger.warning("check_cross_service_events failed: %s", e)
            return {
                "orphaned_events": [],
                "unmatched_consumers": [],
                "matched_events": [],
                "total_events": 0,
                "match_rate": 0.0,
                "error": str(e),
            }


# ======================================================================
# Module-level helpers
# ======================================================================


def _parse_tool_result(result: Any) -> dict[str, Any]:
    """Parse an MCP tool result into a dict.

    Handles three cases:
    1. Result has ``.content`` with text blocks -- parse JSON from first
       text block.
    2. Result is already a ``dict`` -- return as-is.
    3. Anything else -- wrap in ``{"raw": str(result)}``.
    """
    if hasattr(result, "content"):
        for block in result.content:
            if hasattr(block, "text"):
                try:
                    return json.loads(block.text)
                except (json.JSONDecodeError, TypeError):
                    return {"raw": block.text}
    if isinstance(result, dict):
        return result
    return {"raw": str(result)}
