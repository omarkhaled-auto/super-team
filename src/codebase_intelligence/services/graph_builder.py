"""Dependency graph construction using NetworkX."""
from __future__ import annotations

import logging

import networkx as nx

from src.shared.models.codebase import ImportReference, DependencyEdge, DependencyRelation

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Builds and maintains a NetworkX DiGraph representing file and symbol dependencies.

    Node IDs are file paths (strings) for easy JSON serialization.
    Edges have attributes: relation (imports/calls/inherits/implements), line, etc.
    """

    def __init__(self, graph: nx.DiGraph | None = None) -> None:
        self._graph: nx.DiGraph = graph if graph is not None else nx.DiGraph()

    @property
    def graph(self) -> nx.DiGraph:
        """Return the underlying NetworkX DiGraph."""
        return self._graph

    def build_graph(
        self,
        imports: list[ImportReference],
        edges: list[DependencyEdge] | None = None,
    ) -> nx.DiGraph:
        """Build a dependency graph from imports and optional edges.

        Args:
            imports: List of ImportReference instances
            edges: Optional list of DependencyEdge instances

        Returns:
            The constructed NetworkX DiGraph
        """
        for imp in imports:
            try:
                # Add nodes with metadata
                if imp.source_file not in self._graph:
                    self._graph.add_node(imp.source_file)
                if imp.target_file not in self._graph:
                    self._graph.add_node(imp.target_file)

                # Add edge for the import
                self._graph.add_edge(
                    imp.source_file,
                    imp.target_file,
                    relation="imports",
                    line=imp.line,
                    imported_names=imp.imported_names,
                )
            except (AttributeError, TypeError) as exc:
                logger.warning("Failed to add import edge: %s", exc)

        if edges:
            for edge in edges:
                try:
                    # Add edges for other dependency types
                    if edge.source_file not in self._graph:
                        self._graph.add_node(edge.source_file)
                    if edge.target_file not in self._graph:
                        self._graph.add_node(edge.target_file)

                    self._graph.add_edge(
                        edge.source_file,
                        edge.target_file,
                        relation=edge.relation.value
                        if isinstance(edge.relation, DependencyRelation)
                        else edge.relation,
                        source_symbol=edge.source_symbol_id,
                        target_symbol=edge.target_symbol_id,
                        line=edge.line,
                    )
                except (AttributeError, TypeError) as exc:
                    logger.warning("Failed to add dependency edge: %s", exc)

        return self._graph

    def add_file(
        self,
        file_path: str,
        imports: list[ImportReference],
        edges: list[DependencyEdge] | None = None,
        language: str | None = None,
        service_name: str | None = None,
    ) -> None:
        """Add a single file's dependencies to the graph (incremental update).

        First removes all existing edges from this file, then adds new ones.

        Args:
            file_path: Path to the file being added
            imports: Import references from this file
            edges: Optional dependency edges from this file
            language: File language
            service_name: Service the file belongs to
        """
        # Remove existing edges from this file
        self.remove_file(file_path)

        # Add/update node with metadata
        self._graph.add_node(file_path, language=language, service_name=service_name)

        # Add import edges
        for imp in imports:
            try:
                if imp.target_file not in self._graph:
                    self._graph.add_node(imp.target_file)
                self._graph.add_edge(
                    imp.source_file,
                    imp.target_file,
                    relation="imports",
                    line=imp.line,
                )
            except (AttributeError, TypeError) as exc:
                logger.warning("Failed to add import edge in add_file: %s", exc)

        # Add other dependency edges
        if edges:
            for edge in edges:
                try:
                    if edge.target_file not in self._graph:
                        self._graph.add_node(edge.target_file)
                    self._graph.add_edge(
                        edge.source_file,
                        edge.target_file,
                        relation=edge.relation.value
                        if isinstance(edge.relation, DependencyRelation)
                        else edge.relation,
                        source_symbol=edge.source_symbol_id,
                        target_symbol=edge.target_symbol_id,
                        line=edge.line,
                    )
                except (AttributeError, TypeError) as exc:
                    logger.warning("Failed to add dependency edge in add_file: %s", exc)

    def remove_file(self, file_path: str) -> None:
        """Remove a file and all its edges from the graph."""
        if file_path in self._graph:
            # Remove all edges FROM this file
            successors = list(self._graph.successors(file_path))
            for s in successors:
                self._graph.remove_edge(file_path, s)
            # Remove all edges TO this file
            predecessors = list(self._graph.predecessors(file_path))
            for p in predecessors:
                self._graph.remove_edge(p, file_path)
