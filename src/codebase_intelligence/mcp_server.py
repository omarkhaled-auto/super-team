"""MCP server for the Codebase Intelligence service.

Exposes code indexing, semantic search, symbol lookup, dependency analysis,
graph analysis, and dead-code detection as MCP tools over stdio transport.
Each tool delegates to the real service functions -- no mock data is ever
returned.

Environment variables (typically set via .mcp.json):
    DATABASE_PATH  -- Path to the SQLite symbols database file.
    CHROMA_PATH    -- Path to the ChromaDB persistent storage directory.
    GRAPH_PATH     -- Path to the graph snapshot JSON file (unused directly;
                      snapshots are loaded from SQLite via GraphDB).

Usage:
    python -m src.codebase_intelligence.mcp_server
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import networkx as nx

from mcp.server.fastmcp import FastMCP

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_symbols_db
from src.shared.models.codebase import (
    DeadCodeEntry,
    Language,
    SymbolDefinition,
    SymbolKind,
)

from src.codebase_intelligence.services.ast_parser import ASTParser
from src.codebase_intelligence.services.symbol_extractor import SymbolExtractor
from src.codebase_intelligence.services.import_resolver import ImportResolver
from src.codebase_intelligence.services.graph_builder import GraphBuilder
from src.codebase_intelligence.services.graph_analyzer import GraphAnalyzer
from src.codebase_intelligence.services.dead_code_detector import DeadCodeDetector
from src.codebase_intelligence.services.semantic_indexer import SemanticIndexer
from src.codebase_intelligence.services.semantic_searcher import SemanticSearcher
from src.codebase_intelligence.services.incremental_indexer import IncrementalIndexer
from src.codebase_intelligence.services.service_interface_extractor import ServiceInterfaceExtractor
from src.codebase_intelligence.storage.symbol_db import SymbolDB
from src.codebase_intelligence.storage.graph_db import GraphDB
from src.codebase_intelligence.storage.chroma_store import ChromaStore

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("codebase_intelligence.mcp")

# ---------------------------------------------------------------------------
# Module-level initialisation
# ---------------------------------------------------------------------------

_db_path: str = os.environ.get("DATABASE_PATH", "./data/symbols.db")
_chroma_path: str = os.environ.get("CHROMA_PATH", "./data/chroma")

_pool = ConnectionPool(_db_path)
init_symbols_db(_pool)

_symbol_db = SymbolDB(_pool)
_graph_db = GraphDB(_pool)
_chroma_store = ChromaStore(_chroma_path)

# Load existing graph snapshot or start with an empty graph
_existing_graph = _graph_db.load_snapshot()
_graph_builder = GraphBuilder(graph=_existing_graph)
_graph_analyzer = GraphAnalyzer(_graph_builder.graph)

_ast_parser = ASTParser()
_symbol_extractor = SymbolExtractor()
_import_resolver = ImportResolver()
_dead_code_detector = DeadCodeDetector(_graph_builder.graph)

_semantic_indexer = SemanticIndexer(_chroma_store, _symbol_db)
_semantic_searcher = SemanticSearcher(_chroma_store)
_service_interface_extractor = ServiceInterfaceExtractor(_ast_parser, _symbol_extractor)

_incremental_indexer = IncrementalIndexer(
    ast_parser=_ast_parser,
    symbol_extractor=_symbol_extractor,
    import_resolver=_import_resolver,
    graph_builder=_graph_builder,
    symbol_db=_symbol_db,
    graph_db=_graph_db,
    semantic_indexer=_semantic_indexer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_LANGUAGES = {lang.value for lang in Language}


def _row_to_symbol(row: Any) -> SymbolDefinition:
    """Convert a raw ``sqlite3.Row`` to a :class:`SymbolDefinition`.

    Handles the language validation gracefully -- if the stored language
    value is not one of the known enum members, it defaults to
    ``Language.PYTHON``.
    """
    raw_language = row["language"]
    language = (
        Language(raw_language)
        if raw_language in _VALID_LANGUAGES
        else Language.PYTHON
    )

    return SymbolDefinition(
        file_path=row["file_path"],
        symbol_name=row["symbol_name"],
        kind=SymbolKind(row["kind"]),
        language=language,
        service_name=row["service_name"],
        line_start=row["line_start"],
        line_end=row["line_end"],
        signature=row["signature"],
        docstring=row["docstring"],
        is_exported=bool(row["is_exported"]),
        parent_symbol=row["parent_symbol"],
    )


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("Codebase Intelligence")


@mcp.tool(name="register_artifact")
def index_file(
    file_path: str,
    service_name: str | None = None,
    source_base64: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Index a source file through the full codebase-intelligence pipeline.

    Parses the file's AST, extracts symbols and imports, updates the
    dependency graph, persists everything to the database, and generates
    semantic embeddings for code search.

    Args:
        file_path: Absolute or project-relative path to the file.
        service_name: Optional service name the file belongs to.
        source_base64: Base64-encoded file contents.  When provided the
                       indexer uses these bytes instead of reading from disk.
        project_root: Project root directory for import resolution.

    Returns:
        A dictionary with keys: indexed (bool), symbols_found (int),
        dependencies_found (int), errors (list[str]).
    """
    try:
        source: bytes | None = None
        if source_base64 is not None:
            source = base64.b64decode(source_base64)

        result = _incremental_indexer.index_file(
            file_path,
            source=source,
            service_name=service_name,
            project_root=project_root,
        )
        return result
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error indexing file: %s", file_path)
        return {"error": str(exc)}


@mcp.tool(name="search_semantic")
def search_code(
    query: str,
    language: str | None = None,
    service_name: str | None = None,
    n_results: int = 10,
) -> list[dict[str, Any]]:
    """Search indexed code using natural-language semantic similarity.

    Queries the ChromaDB vector store for code chunks whose embeddings
    are closest to the query string.  Results can be filtered by
    programming language and/or service name.

    Args:
        query: Natural-language or code search query.
        language: Optional language filter (e.g. "python", "typescript").
        service_name: Optional service name filter.
        n_results: Maximum number of results to return (default 10).

    Returns:
        A list of search-result dictionaries sorted by descending score.
    """
    try:
        results = _semantic_searcher.search(
            query,
            language=language,
            service_name=service_name,
            top_k=n_results,
        )
        return [r.model_dump(mode="json") for r in results]
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error during code search")
        return [{"error": str(exc)}]


@mcp.tool(name="find_definition")
def find_definition(
    symbol: str,
    language: str | None = None,
) -> dict[str, Any]:
    """Find the definition location of a symbol.

    Searches the symbol index for the given symbol name, optionally
    filtered by programming language.  Returns the first matching
    symbol's location information.

    Args:
        symbol: The symbol name to search for (exact match).
        language: Optional language filter (python, typescript, csharp, go).

    Returns:
        A dict with file_path, line_start, line_end, kind, language,
        signature, and docstring for the symbol, or an error dict if
        the symbol is not found.
    """
    try:
        symbols = _symbol_db.query_by_name(symbol)

        # Apply language filter if provided
        if language is not None:
            symbols = [s for s in symbols if s.language.value == language]

        if not symbols:
            return {"error": f"Symbol {symbol!r} not found"}

        # Return the first match shaped to the SVC-007 contract
        s = symbols[0]
        return {
            "file": s.file_path,
            "line": s.line_start,
            "kind": s.kind.value if hasattr(s.kind, 'value') else str(s.kind),
            "signature": s.signature or "",
        }
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error finding definition for: %s", symbol)
        return {"error": str(exc)}


@mcp.tool(name="find_dependencies")
def get_dependencies(
    file_path: str,
    depth: int = 1,
    direction: str = "both",
) -> dict[str, Any]:
    """Retrieve the dependency relationships for a file.

    Looks up the dependency graph to find files that *file_path* depends
    on (forward / downstream) and files that depend on *file_path*
    (reverse / upstream -- useful for impact analysis).

    Args:
        file_path: The file whose dependencies to query.
        depth: Maximum traversal depth (default 1 = direct only).
        direction: One of "forward", "reverse", or "both" (default).

    Returns:
        A dictionary with keys: file_path, depth, dependencies (list),
        dependents (list).
    """
    try:
        # Direct imports and reverse dependents
        deps = _graph_analyzer.get_dependencies(file_path, depth)
        dependents = _graph_analyzer.get_dependents(file_path, depth)

        # Transitive dependencies: walk forward with a large depth
        transitive = _graph_analyzer.get_dependencies(file_path, depth=100)

        # Circular dependencies involving this file
        circular: list[list[str]] = []
        graph = _graph_analyzer.graph
        if file_path in graph:
            try:
                for cycle in nx.simple_cycles(graph):
                    if file_path in cycle:
                        circular.append(list(cycle))
                    if len(circular) >= 20:
                        break
            except (nx.NetworkXError, KeyError):
                pass

        return {
            "imports": deps,
            "imported_by": dependents,
            "transitive_deps": transitive,
            "circular_deps": circular,
        }
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception(
            "Unexpected error querying dependencies for: %s", file_path
        )
        return {"error": str(exc)}


@mcp.tool()
def analyze_graph() -> dict[str, Any]:
    """Analyse the full dependency graph for structural metrics.

    Computes node/edge counts, checks if the graph is a DAG, detects
    circular dependencies, ranks files by PageRank importance, counts
    weakly-connected components, and produces a topological build order
    (when the graph is acyclic).

    Returns:
        A dictionary containing the full graph analysis results.
    """
    try:
        analysis = _graph_analyzer.analyze()
        return analysis.model_dump(mode="json")
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error during graph analysis")
        return {"error": str(exc)}


@mcp.tool(name="check_dead_code")
def detect_dead_code(
    service_name: str | None = None,
) -> list[dict[str, Any]]:
    """Detect potentially unused (dead) code in the index.

    Queries all indexed symbols (optionally scoped to a single service)
    and cross-references them against the dependency graph to find
    exported symbols that are never referenced.  Each result includes a
    confidence level (high, medium, low).

    Args:
        service_name: Optional service name to limit the analysis to.

    Returns:
        A list of dead-code entry dictionaries.
    """
    try:
        # Fetch all symbols via direct SQL to support the optional filter
        conn = _pool.get()
        query = "SELECT * FROM symbols"
        params: list[str] = []
        if service_name:
            query += " WHERE service_name = ?"
            params.append(service_name)
        rows = conn.execute(query, params).fetchall()
        symbols = [_row_to_symbol(row) for row in rows]

        result = _dead_code_detector.find_dead_code(symbols)
        return [entry.model_dump(mode="json") for entry in result]
    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error during dead-code detection")
        return [{"error": str(exc)}]


@mcp.tool(name="find_callers")
def find_callers(symbol: str, max_results: int = 50) -> list[dict[str, Any]]:
    """Find all locations where a symbol is called or referenced.

    Queries the dependency graph for edges targeting the given symbol,
    returning the call sites with file path, line number, and the
    calling symbol name.

    Args:
        symbol: The symbol name to find callers for.
        max_results: Maximum number of results to return (default 50).

    Returns:
        List of caller dicts with file_path, line, caller_symbol.
    """
    try:
        conn = _pool.get()
        # Look up the symbol's ID (file_path::symbol_name format)
        # First find all symbols matching the name to get their IDs
        symbol_rows = conn.execute(
            "SELECT id FROM symbols WHERE symbol_name = ?", (symbol,)
        ).fetchall()

        if not symbol_rows:
            return []

        target_ids = [row["id"] for row in symbol_rows]

        # Query dependency_edges for edges targeting any of these symbol IDs
        callers: list[dict[str, Any]] = []
        for target_id in target_ids:
            rows = conn.execute(
                "SELECT de.source_symbol_id, de.source_file, de.line, de.relation, "
                "s.symbol_name AS caller_symbol "
                "FROM dependency_edges de "
                "LEFT JOIN symbols s ON de.source_symbol_id = s.id "
                "WHERE de.target_symbol_id = ? "
                "LIMIT ?",
                (target_id, max_results - len(callers)),
            ).fetchall()

            for row in rows:
                callers.append({
                    "file_path": row["source_file"],
                    "line": row["line"],
                    "caller_symbol": row["caller_symbol"] or row["source_symbol_id"],
                })

            if len(callers) >= max_results:
                break

        return callers[:max_results]

    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception("Unexpected error finding callers for: %s", symbol)
        return [{"error": str(exc)}]


@mcp.tool(name="get_service_interface")
def get_service_interface(service_name: str) -> dict[str, Any]:
    """Extract the public interface of a service.

    Queries the symbol database for all files belonging to the service,
    reads their source content, and uses the ServiceInterfaceExtractor
    to detect HTTP endpoints, published/consumed events, and exported
    symbols.

    Args:
        service_name: Name of the service to analyze.

    Returns:
        Dict with endpoints, events_published, events_consumed,
        exported_symbols.
    """
    try:
        from src.shared.models.codebase import ServiceInterface

        conn = _pool.get()

        # Get all indexed files for this service
        rows = conn.execute(
            "SELECT file_path FROM indexed_files WHERE service_name = ?",
            (service_name,),
        ).fetchall()

        if not rows:
            # Return an empty interface
            empty = ServiceInterface(service_name=service_name)
            return empty.model_dump(mode="json")

        # Aggregate interfaces from all files in the service
        all_endpoints: list[dict] = []
        all_events_published: list[dict] = []
        all_events_consumed: list[dict] = []
        all_exported: list[dict] = []

        for row in rows:
            file_path = row["file_path"]
            try:
                with open(file_path, "rb") as f:
                    source = f.read()
                iface = _service_interface_extractor.extract(
                    source, file_path, service_name
                )
                iface_dict = iface.model_dump(mode="json")
                all_endpoints.extend(iface_dict.get("endpoints", []))
                all_events_published.extend(iface_dict.get("events_published", []))
                all_events_consumed.extend(iface_dict.get("events_consumed", []))
                all_exported.extend(iface_dict.get("exported_symbols", []))
            except (OSError, IOError):
                # File may no longer exist on disk; skip it
                logger.debug("Cannot read file %s for interface extraction", file_path)
                continue

        return {
            "service_name": service_name,
            "endpoints": all_endpoints,
            "events_published": all_events_published,
            "events_consumed": all_events_consumed,
            "exported_symbols": all_exported,
        }

    # Top-level handler: broad catch intentional
    except Exception as exc:
        logger.exception(
            "Unexpected error extracting service interface for: %s", service_name
        )
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
