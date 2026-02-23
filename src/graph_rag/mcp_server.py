"""MCP server for the Graph RAG module.

Exposes 7 tools for knowledge graph construction, querying, and analysis
over stdio transport. Each tool delegates to GraphRAGEngine or
GraphRAGIndexer.

Environment variables:
    GRAPH_RAG_DB_PATH       -- SQLite database for graph_rag_snapshots.
    GRAPH_RAG_CHROMA_PATH   -- ChromaDB persistent storage directory.
    CI_DATABASE_PATH        -- Codebase Intelligence SQLite (read-only).
    ARCHITECT_DATABASE_PATH -- Architect SQLite (read-only).
    CONTRACT_DATABASE_PATH  -- Contract Engine SQLite (read-only).

Usage:
    python -m src.graph_rag.mcp_server
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_graph_rag_db

from src.graph_rag.knowledge_graph import KnowledgeGraph
from src.graph_rag.graph_rag_store import GraphRAGStore
from src.graph_rag.graph_rag_indexer import GraphRAGIndexer
from src.graph_rag.graph_rag_engine import GraphRAGEngine
from src.graph_rag.context_assembler import ContextAssembler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("graph_rag.mcp")

# ---------------------------------------------------------------------------
# Module-level initialisation
# ---------------------------------------------------------------------------

# Graph RAG's own stores
_db_path: str = os.environ.get("GRAPH_RAG_DB_PATH", "./data/graph_rag.db")
_chroma_path: str = os.environ.get("GRAPH_RAG_CHROMA_PATH", "./data/graph_rag_chroma")

# External databases (read-only access)
_ci_db_path: str = os.environ.get("CI_DATABASE_PATH", "./data/codebase_intel.db")
_architect_db_path: str = os.environ.get("ARCHITECT_DATABASE_PATH", "./data/architect.db")
_contract_db_path: str = os.environ.get("CONTRACT_DATABASE_PATH", "./data/contracts.db")

# Initialize connection pools
_pool = ConnectionPool(_db_path)
_ci_pool = ConnectionPool(_ci_db_path)
_architect_pool = ConnectionPool(_architect_db_path)
_contract_pool = ConnectionPool(_contract_db_path)

# Initialize schema (own database only)
init_graph_rag_db(_pool)

# Initialize core objects
_knowledge_graph = KnowledgeGraph()
_store = GraphRAGStore(_chroma_path)
_assembler = ContextAssembler()
_engine = GraphRAGEngine(_knowledge_graph, _store, _assembler)
_indexer = GraphRAGIndexer(
    knowledge_graph=_knowledge_graph,
    store=_store,
    pool=_pool,
    ci_pool=_ci_pool,
    architect_pool=_architect_pool,
    contract_pool=_contract_pool,
)

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("Graph RAG")


@mcp.tool(name="build_knowledge_graph")
def build_knowledge_graph(
    project_name: str = "",
    force_rebuild: bool = True,
    service_interfaces_json: str = "",
) -> dict[str, Any]:
    """Build or rebuild the unified knowledge graph from all data stores.

    Reads from Codebase Intelligence, Architect, and Contract Engine
    databases, constructs a NetworkX MultiDiGraph, computes PageRank
    and Louvain communities, and populates ChromaDB collections.

    Args:
        project_name: Project name filter for service map lookup.
        force_rebuild: If False and a recent snapshot exists, skip rebuild.
        service_interfaces_json: JSON-encoded dict of pre-fetched service
            interface data from CI MCP get_service_interface calls.

    Returns:
        Build result with node/edge counts, community count, and errors.
    """
    try:
        # force_rebuild=False: return cached snapshot if < 300 seconds old
        if not force_rebuild:
            try:
                conn = _pool.get()
                row = conn.execute(
                    "SELECT node_count, edge_count, community_count, "
                    "services_indexed, created_at FROM graph_rag_snapshots "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    from datetime import datetime, timezone
                    created = datetime.fromisoformat(row["created_at"])
                    age = (datetime.now(timezone.utc) - created).total_seconds()
                    if age < 300:
                        logger.info(
                            "Recent snapshot found (%.0fs old) -- skipping rebuild",
                            age,
                        )
                        svc_list = json.loads(row["services_indexed"]) if row["services_indexed"] else []
                        return {
                            "success": True,
                            "node_count": row["node_count"],
                            "edge_count": row["edge_count"],
                            "node_types": {},
                            "edge_types": {},
                            "community_count": row["community_count"],
                            "build_time_ms": 0,
                            "services_indexed": svc_list,
                            "errors": [],
                        }
            except Exception:
                pass  # Fall through to full rebuild

        service_interfaces: dict[str, Any] | None = None
        if service_interfaces_json:
            try:
                service_interfaces = json.loads(service_interfaces_json)
            except (json.JSONDecodeError, TypeError):
                service_interfaces = None

        result = _indexer.build(
            project_name=project_name,
            service_interfaces=service_interfaces,
        )

        # Update engine's undirected cache after rebuild
        _engine.update_undirected_cache()

        return dataclasses.asdict(result)
    except Exception as exc:
        logger.exception("build_knowledge_graph failed")
        return {"success": False, "error": str(exc), "errors": [str(exc)]}


@mcp.tool(name="get_service_context")
def get_service_context(
    service_name: str,
    include_consumed_apis: bool = True,
    include_provided_apis: bool = True,
    include_events: bool = True,
    include_entities: bool = True,
    include_dependencies: bool = True,
    max_depth: int = 2,
) -> dict[str, Any]:
    """Retrieve structured context for a service.

    Returns consumed/provided APIs, events, entities, dependency topology,
    and a pre-formatted context text block for builder injection.

    Args:
        service_name: Target service name.
        include_consumed_apis: Include APIs this service calls.
        include_provided_apis: Include APIs this service exposes.
        include_events: Include published/consumed events.
        include_entities: Include owned/referenced domain entities.
        include_dependencies: Include service dependency topology.
        max_depth: Max traversal depth for dependency topology.

    Returns:
        Service context dict with all sections and context_text.
    """
    try:
        return _engine.get_service_context(
            service_name=service_name,
            include_consumed_apis=include_consumed_apis,
            include_provided_apis=include_provided_apis,
            include_events=include_events,
            include_entities=include_entities,
            include_dependencies=include_dependencies,
            max_depth=max_depth,
        )
    except Exception as exc:
        logger.exception("get_service_context failed for %s", service_name)
        return {"service_name": service_name, "error": str(exc)}


@mcp.tool(name="query_graph_neighborhood")
def query_graph_neighborhood(
    node_id: str,
    radius: int = 2,
    undirected: bool = True,
    filter_node_types: str = "",
    filter_edge_types: str = "",
    max_nodes: int = 50,
) -> dict[str, Any]:
    """Extract the N-hop neighborhood around a node.

    Args:
        node_id: Knowledge graph node ID.
        radius: Hop count.
        undirected: Include both incoming and outgoing edges.
        filter_node_types: Comma-separated node types to include.
        filter_edge_types: Comma-separated edge types to include.
        max_nodes: Maximum nodes to return.

    Returns:
        Subgraph with center_node, nodes, edges, and truncation info.
    """
    try:
        return _engine.query_graph_neighborhood(
            node_id=node_id,
            radius=radius,
            undirected=undirected,
            filter_node_types=filter_node_types,
            filter_edge_types=filter_edge_types,
            max_nodes=max_nodes,
        )
    except Exception as exc:
        logger.exception("query_graph_neighborhood failed for %s", node_id)
        return {"error": str(exc), "nodes": [], "edges": []}


@mcp.tool(name="hybrid_search")
def hybrid_search(
    query: str,
    n_results: int = 10,
    node_types: str = "",
    service_name: str = "",
    anchor_node_id: str = "",
    semantic_weight: float = 0.6,
    graph_weight: float = 0.4,
) -> dict[str, Any]:
    """Combine semantic vector search with graph-structural re-ranking.

    Args:
        query: Natural language query.
        n_results: Number of results to return.
        node_types: Comma-separated node types to search.
        service_name: Filter to specific service.
        anchor_node_id: Re-rank by graph distance to this node.
        semantic_weight: Weight for semantic score (0.0-1.0).
        graph_weight: Weight for graph proximity score (0.0-1.0).

    Returns:
        Ranked results with combined scores.
    """
    try:
        return _engine.hybrid_search(
            query=query,
            n_results=n_results,
            anchor_node_id=anchor_node_id,
            node_types=node_types,
            service_name=service_name,
            semantic_weight=semantic_weight,
            graph_weight=graph_weight,
        )
    except Exception as exc:
        logger.exception("hybrid_search failed")
        return {"error": str(exc), "results": [], "query": query}


@mcp.tool(name="find_cross_service_impact")
def find_cross_service_impact(
    node_id: str,
    max_depth: int = 3,
) -> dict[str, Any]:
    """Find cross-service entities affected by a change to the given node.

    Args:
        node_id: File or symbol node ID.
        max_depth: Maximum traversal depth.

    Returns:
        Impact analysis with impacted services, contracts, and entities.
    """
    try:
        return _engine.find_cross_service_impact(
            node_id=node_id,
            max_depth=max_depth,
        )
    except Exception as exc:
        logger.exception("find_cross_service_impact failed for %s", node_id)
        return {"error": str(exc), "total_impacted_nodes": 0}


@mcp.tool(name="validate_service_boundaries")
def validate_service_boundaries(
    resolution: float = 1.0,
) -> dict[str, Any]:
    """Validate service boundaries using community detection.

    Uses Louvain community detection to check whether declared service
    boundaries align with actual code dependency clusters.

    Args:
        resolution: Louvain resolution parameter (<1 larger, >1 smaller).

    Returns:
        Validation result with alignment score and misplaced files.
    """
    try:
        return _engine.validate_service_boundaries(
            resolution=resolution,
        )
    except Exception as exc:
        logger.exception("validate_service_boundaries failed")
        return {"error": str(exc), "alignment_score": 0.0}


@mcp.tool(name="check_cross_service_events")
def check_cross_service_events(
    service_name: str = "",
) -> dict[str, Any]:
    """Validate cross-service event publisher/consumer matching.

    Checks that published events have consumers and consumed events have
    publishers.  Directly supports ADV-001/ADV-002 false positive reduction.

    Args:
        service_name: Filter to specific service (empty for all).

    Returns:
        Event validation with orphaned, unmatched, and matched events.
    """
    try:
        return _engine.check_cross_service_events(
            service_name=service_name,
        )
    except Exception as exc:
        logger.exception("check_cross_service_events failed")
        return {"error": str(exc), "matched_events": [], "orphaned_events": []}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
