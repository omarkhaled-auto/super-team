"""Tests for GraphBuilder — constructs a NetworkX dependency graph.

Covers empty graphs, building from imports, node correctness, edge
attributes, incremental add_file, remove_file cleanup, multiple edge
types, and node metadata via add_file.
"""
from __future__ import annotations

import pytest
import networkx as nx

from src.codebase_intelligence.services.graph_builder import GraphBuilder
from src.shared.models.codebase import (
    DependencyEdge,
    DependencyRelation,
    ImportReference,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_import(
    source: str,
    target: str,
    line: int = 1,
    names: list[str] | None = None,
) -> ImportReference:
    """Convenience factory for ImportReference objects."""
    return ImportReference(
        source_file=source,
        target_file=target,
        imported_names=names or [],
        line=line,
    )


def _make_edge(
    source_file: str,
    target_file: str,
    relation: DependencyRelation = DependencyRelation.CALLS,
    line: int | None = None,
) -> DependencyEdge:
    """Convenience factory for DependencyEdge objects."""
    return DependencyEdge(
        source_symbol_id=f"{source_file}::func",
        target_symbol_id=f"{target_file}::func",
        relation=relation,
        source_file=source_file,
        target_file=target_file,
        line=line,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildEmptyGraph:
    """build_graph with no imports creates an empty graph."""

    def test_build_empty_graph(self) -> None:
        """An empty import list produces a graph with 0 nodes and 0 edges."""
        builder = GraphBuilder()
        graph = builder.build_graph(imports=[])

        assert graph.number_of_nodes() == 0
        assert graph.number_of_edges() == 0


class TestBuildFromImports:
    """build_graph with imports creates nodes and edges."""

    def test_build_from_imports(self) -> None:
        """Imports between files create corresponding directed edges."""
        imports = [
            _make_import("a.py", "b.py"),
            _make_import("b.py", "c.py"),
        ]
        builder = GraphBuilder()
        graph = builder.build_graph(imports=imports)

        assert graph.number_of_nodes() == 3
        assert graph.number_of_edges() == 2
        assert graph.has_edge("a.py", "b.py")
        assert graph.has_edge("b.py", "c.py")


class TestGraphHasCorrectNodes:
    """All source and target files appear as nodes."""

    def test_graph_has_correct_nodes(self) -> None:
        """Every unique file mentioned as source or target is a node."""
        imports = [
            _make_import("src/main.py", "src/utils.py"),
            _make_import("src/main.py", "src/models.py"),
        ]
        builder = GraphBuilder()
        graph = builder.build_graph(imports=imports)

        expected_nodes = {"src/main.py", "src/utils.py", "src/models.py"}
        assert set(graph.nodes) == expected_nodes


class TestGraphEdgeAttributes:
    """Edges carry relation='imports' attribute."""

    def test_graph_edge_attributes(self) -> None:
        """Each edge created from an ImportReference has relation='imports'."""
        imports = [_make_import("a.py", "b.py", line=5, names=["foo"])]
        builder = GraphBuilder()
        graph = builder.build_graph(imports=imports)

        edge_data = graph.edges["a.py", "b.py"]
        assert edge_data["relation"] == "imports"
        assert edge_data["line"] == 5
        assert edge_data["imported_names"] == ["foo"]


class TestAddFileIncremental:
    """add_file updates the graph incrementally."""

    def test_add_file_incremental(self) -> None:
        """Adding a new file introduces its edges without affecting others."""
        builder = GraphBuilder()
        # Start with one file
        builder.add_file(
            "a.py",
            imports=[_make_import("a.py", "b.py")],
            language="python",
        )
        assert builder.graph.has_edge("a.py", "b.py")

        # Add a second file
        builder.add_file(
            "c.py",
            imports=[_make_import("c.py", "b.py")],
            language="python",
        )
        assert builder.graph.has_edge("c.py", "b.py")
        # Original edge still present
        assert builder.graph.has_edge("a.py", "b.py")
        assert builder.graph.number_of_nodes() == 3


class TestRemoveFileCleansEdges:
    """remove_file removes the file's edges (both inbound and outbound)."""

    def test_remove_file_cleans_edges(self) -> None:
        """After removing a file, all edges from and to it are gone."""
        builder = GraphBuilder()
        builder.build_graph(
            imports=[
                _make_import("a.py", "b.py"),
                _make_import("b.py", "c.py"),
                _make_import("c.py", "b.py"),
            ]
        )
        assert builder.graph.has_edge("a.py", "b.py")
        assert builder.graph.has_edge("b.py", "c.py")
        assert builder.graph.has_edge("c.py", "b.py")

        builder.remove_file("b.py")

        # All edges involving b.py are removed
        assert not builder.graph.has_edge("a.py", "b.py")
        assert not builder.graph.has_edge("b.py", "c.py")
        assert not builder.graph.has_edge("c.py", "b.py")


class TestMultipleEdgeTypes:
    """imports + calls edges work together in the same graph."""

    def test_multiple_edge_types(self) -> None:
        """build_graph accepts both ImportReference and DependencyEdge objects."""
        imports = [_make_import("a.py", "b.py")]
        edges = [_make_edge("a.py", "c.py", DependencyRelation.CALLS, line=10)]

        builder = GraphBuilder()
        graph = builder.build_graph(imports=imports, edges=edges)

        assert graph.has_edge("a.py", "b.py")
        assert graph.has_edge("a.py", "c.py")
        assert graph.edges["a.py", "b.py"]["relation"] == "imports"
        assert graph.edges["a.py", "c.py"]["relation"] == "calls"


class TestNodeMetadata:
    """language and service_name are set on nodes via add_file."""

    def test_node_metadata(self) -> None:
        """add_file stores language and service_name as node attributes."""
        builder = GraphBuilder()
        builder.add_file(
            "src/auth/views.py",
            imports=[_make_import("src/auth/views.py", "src/auth/models.py")],
            language="python",
            service_name="auth-service",
        )

        node_data = builder.graph.nodes["src/auth/views.py"]
        assert node_data["language"] == "python"
        assert node_data["service_name"] == "auth-service"


class TestGraphPropertyReturnsDiGraph:
    """The graph property returns a NetworkX DiGraph."""

    def test_graph_property_returns_digraph(self) -> None:
        """The graph property exposes the underlying nx.DiGraph instance."""
        builder = GraphBuilder()
        assert isinstance(builder.graph, nx.DiGraph)


class TestAddFileReplacesExistingEdges:
    """Calling add_file twice for the same file replaces its edges."""

    def test_add_file_replaces_existing_edges(self) -> None:
        """Re-adding a file first removes its old edges, then adds new ones."""
        builder = GraphBuilder()
        builder.add_file(
            "a.py",
            imports=[_make_import("a.py", "b.py")],
        )
        assert builder.graph.has_edge("a.py", "b.py")

        # Re-add with a different target
        builder.add_file(
            "a.py",
            imports=[_make_import("a.py", "c.py")],
        )
        # Old edge gone, new edge present
        assert not builder.graph.has_edge("a.py", "b.py")
        assert builder.graph.has_edge("a.py", "c.py")
