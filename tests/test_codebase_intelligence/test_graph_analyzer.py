"""Tests for GraphAnalyzer — analyses a NetworkX dependency graph.

Covers empty graphs, DAG detection, cycle detection, PageRank ranking,
connected components, direct and transitive dependencies, reverse
dependents, full impact analysis, and topological sort ordering.
"""
from __future__ import annotations

import pytest
import networkx as nx

from src.codebase_intelligence.services.graph_analyzer import GraphAnalyzer
from src.shared.models.codebase import GraphAnalysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _linear_chain(*nodes: str) -> nx.DiGraph:
    """Build a linear chain: A -> B -> C -> ... (a DAG)."""
    g = nx.DiGraph()
    for i in range(len(nodes) - 1):
        g.add_edge(nodes[i], nodes[i + 1])
    return g


def _cycle_graph(*nodes: str) -> nx.DiGraph:
    """Build a cycle: A -> B -> C -> A."""
    g = nx.DiGraph()
    for i in range(len(nodes) - 1):
        g.add_edge(nodes[i], nodes[i + 1])
    g.add_edge(nodes[-1], nodes[0])
    return g


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyzeEmptyGraph:
    """analyze() on an empty graph returns 0 nodes, 0 edges, is_dag=True."""

    def test_analyze_empty_graph(self) -> None:
        """An empty graph is a trivial DAG with no components."""
        analyzer = GraphAnalyzer(nx.DiGraph())
        result = analyzer.analyze()

        assert isinstance(result, GraphAnalysis)
        assert result.node_count == 0
        assert result.edge_count == 0
        assert result.is_dag is True
        assert result.circular_dependencies == []


class TestAnalyzeDag:
    """A linear chain is a DAG with a valid build_order."""

    def test_analyze_dag(self) -> None:
        """A linear chain A -> B -> C is a DAG and has a topological build_order."""
        graph = _linear_chain("a.py", "b.py", "c.py")
        analyzer = GraphAnalyzer(graph)
        result = analyzer.analyze()

        assert result.is_dag is True
        assert result.build_order is not None
        assert len(result.build_order) == 3
        assert result.circular_dependencies == []


class TestAnalyzeCycle:
    """A cycle is detected, is_dag=False, no build_order."""

    def test_analyze_cycle(self) -> None:
        """A graph with a cycle reports is_dag=False and has no build_order."""
        graph = _cycle_graph("a.py", "b.py", "c.py")
        analyzer = GraphAnalyzer(graph)
        result = analyzer.analyze()

        assert result.is_dag is False
        assert result.build_order is None
        assert len(result.circular_dependencies) > 0


class TestPagerankTopFiles:
    """The most-imported file has the highest PageRank."""

    def test_pagerank_top_files(self) -> None:
        """When many files import a single hub, that hub has the highest PageRank."""
        g = nx.DiGraph()
        # Multiple files import hub.py
        for name in ["a.py", "b.py", "c.py", "d.py"]:
            g.add_edge(name, "hub.py")

        analyzer = GraphAnalyzer(g)
        result = analyzer.analyze()

        assert len(result.top_files_by_pagerank) > 0
        top_file, top_score = result.top_files_by_pagerank[0]
        assert top_file == "hub.py"
        # Verify hub.py has a higher score than any source file
        scores = dict(result.top_files_by_pagerank)
        for name in ["a.py", "b.py", "c.py", "d.py"]:
            assert scores["hub.py"] > scores[name]


class TestConnectedComponents:
    """Separate subgraphs are counted as distinct weakly connected components."""

    def test_connected_components(self) -> None:
        """Two disconnected subgraphs produce connected_components=2."""
        g = nx.DiGraph()
        g.add_edge("a.py", "b.py")
        g.add_edge("x.py", "y.py")

        analyzer = GraphAnalyzer(g)
        result = analyzer.analyze()

        assert result.connected_components == 2


class TestGetDependenciesDirect:
    """get_dependencies with depth=1 returns direct deps only."""

    def test_get_dependencies_direct(self) -> None:
        """depth=1 returns only immediate successors, not transitive ones."""
        graph = _linear_chain("a.py", "b.py", "c.py")
        analyzer = GraphAnalyzer(graph)

        deps = analyzer.get_dependencies("a.py", depth=1)

        assert "b.py" in deps
        assert "c.py" not in deps


class TestGetDependenciesTransitive:
    """get_dependencies with depth=2 includes indirect deps."""

    def test_get_dependencies_transitive(self) -> None:
        """depth=2 on a linear chain A -> B -> C returns both B and C."""
        graph = _linear_chain("a.py", "b.py", "c.py")
        analyzer = GraphAnalyzer(graph)

        deps = analyzer.get_dependencies("a.py", depth=2)

        assert "b.py" in deps
        assert "c.py" in deps


class TestGetDependentsReverse:
    """get_dependents shows what depends on a file."""

    def test_get_dependents_reverse(self) -> None:
        """get_dependents returns predecessors (files that import the target)."""
        graph = _linear_chain("a.py", "b.py", "c.py")
        analyzer = GraphAnalyzer(graph)

        dependents = analyzer.get_dependents("b.py", depth=1)

        assert "a.py" in dependents
        assert "c.py" not in dependents


class TestGetImpactFull:
    """get_impact returns all transitively affected files."""

    def test_get_impact_full(self) -> None:
        """Changing c.py impacts b.py (which imports c.py) and
        a.py (which imports b.py)."""
        graph = _linear_chain("a.py", "b.py", "c.py")
        analyzer = GraphAnalyzer(graph)

        impact = analyzer.get_impact("c.py")

        assert "b.py" in impact
        assert "a.py" in impact
        # c.py itself should not appear in its own impact list
        assert "c.py" not in impact


class TestTopologicalSortOrder:
    """build_order has correct topological ordering."""

    def test_topological_sort_order(self) -> None:
        """In topological order, every dependency appears before its dependents.

        For A -> B -> C, B must appear before A and C before B in the order
        (since the edge direction means A depends-on B depends-on C).
        """
        graph = _linear_chain("a.py", "b.py", "c.py")
        analyzer = GraphAnalyzer(graph)
        result = analyzer.analyze()

        assert result.build_order is not None
        order = result.build_order
        # In topological sort of a -> b -> c (a depends on b depends on c):
        # a must come before b, b before c in the topo sort because nx
        # topological_sort lists nodes such that for every edge u->v, u comes
        # before v.
        assert order.index("a.py") < order.index("b.py")
        assert order.index("b.py") < order.index("c.py")


class TestGetDependenciesUnknownFile:
    """get_dependencies for a file not in the graph returns empty list."""

    def test_get_dependencies_unknown_file(self) -> None:
        """Querying dependencies for a non-existent node returns []."""
        graph = _linear_chain("a.py", "b.py")
        analyzer = GraphAnalyzer(graph)

        deps = analyzer.get_dependencies("nonexistent.py")

        assert deps == []


class TestGetDependentsTransitive:
    """get_dependents with depth > 1 returns transitive reverse deps."""

    def test_get_dependents_transitive(self) -> None:
        """depth=2 on get_dependents walks predecessors transitively."""
        graph = _linear_chain("a.py", "b.py", "c.py")
        analyzer = GraphAnalyzer(graph)

        dependents = analyzer.get_dependents("c.py", depth=2)

        assert "b.py" in dependents
        assert "a.py" in dependents
