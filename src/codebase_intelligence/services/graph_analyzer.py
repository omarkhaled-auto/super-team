"""Dependency graph analysis using NetworkX algorithms."""
from __future__ import annotations

import logging

import networkx as nx

from src.shared.models.codebase import GraphAnalysis

logger = logging.getLogger(__name__)


class GraphAnalyzer:
    """Analyzes a NetworkX dependency graph for metrics and patterns.

    Uses PageRank, cycle detection, topological sort, and other NetworkX
    algorithms to provide insights about the codebase dependency structure.
    """

    def __init__(self, graph: nx.DiGraph) -> None:
        self._graph = graph

    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    def analyze(self) -> GraphAnalysis:
        """Perform full graph analysis and return a GraphAnalysis result.

        Returns:
            GraphAnalysis with node_count, edge_count, is_dag,
            circular_dependencies, top_files_by_pagerank,
            connected_components, build_order
        """
        node_count = self._graph.number_of_nodes()
        edge_count = self._graph.number_of_edges()

        # Check if DAG (MUST check before topological_sort!)
        is_dag = nx.is_directed_acyclic_graph(self._graph)

        # Detect circular dependencies
        circular_deps: list[list[str]] = []
        if not is_dag:
            try:
                cycles = list(nx.simple_cycles(self._graph))
                circular_deps = [list(cycle) for cycle in cycles[:20]]  # Limit to 20
            except (nx.NetworkXError, KeyError) as exc:
                logger.warning("Failed to detect cycles: %s", exc)

        # PageRank
        top_files: list[tuple[str, float]] = []
        if node_count > 0:
            try:
                pr = nx.pagerank(self._graph)
                sorted_pr = sorted(pr.items(), key=lambda x: x[1], reverse=True)
                top_files = sorted_pr[:10]  # Top 10
            except (nx.NetworkXError, KeyError) as exc:
                logger.warning("PageRank failed: %s", exc)

        # Connected components (weakly connected for DiGraph)
        components = 0
        try:
            components = nx.number_weakly_connected_components(self._graph)
        except (nx.NetworkXError, KeyError):
            pass

        # Build order (topological sort) - only if DAG
        build_order: list[str] | None = None
        if is_dag and node_count > 0:
            try:
                build_order = list(nx.topological_sort(self._graph))
            except nx.NetworkXError:
                pass

        return GraphAnalysis(
            node_count=node_count,
            edge_count=edge_count,
            is_dag=is_dag,
            circular_dependencies=circular_deps,
            top_files_by_pagerank=top_files,
            connected_components=components,
            build_order=build_order,
        )

    def get_dependencies(self, file_path: str, depth: int = 1) -> list[str]:
        """Get transitive dependencies of a file up to a given depth.

        Args:
            file_path: The file to find dependencies for
            depth: Maximum traversal depth (default 1 = direct deps only)

        Returns:
            List of file paths that this file depends on
        """
        if file_path not in self._graph:
            return []

        if depth == 1:
            return list(self._graph.successors(file_path))

        # BFS for multi-level dependencies
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(file_path, 0)]
        result: list[str] = []

        while queue:
            current, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue
            for successor in self._graph.successors(current):
                if successor not in visited and successor != file_path:
                    visited.add(successor)
                    result.append(successor)
                    queue.append((successor, current_depth + 1))

        return result

    def get_dependents(self, file_path: str, depth: int = 1) -> list[str]:
        """Get files that depend on the given file (reverse dependencies).

        Also called 'impact analysis' -- what files are affected if this file changes.
        """
        if file_path not in self._graph:
            return []

        if depth == 1:
            return list(self._graph.predecessors(file_path))

        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(file_path, 0)]
        result: list[str] = []

        while queue:
            current, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue
            for predecessor in self._graph.predecessors(current):
                if predecessor not in visited and predecessor != file_path:
                    visited.add(predecessor)
                    result.append(predecessor)
                    queue.append((predecessor, current_depth + 1))

        return result

    def get_impact(self, file_path: str) -> list[str]:
        """Get all files transitively affected by changes to this file.

        Uses reverse BFS with no depth limit.
        """
        return self.get_dependents(file_path, depth=100)
