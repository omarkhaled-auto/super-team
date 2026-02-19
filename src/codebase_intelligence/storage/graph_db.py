"""SQLite-backed storage for the dependency graph and NetworkX snapshots."""
from __future__ import annotations

import json
import logging

import networkx as nx

from src.shared.db.connection import ConnectionPool
from src.shared.models.codebase import DependencyEdge, DependencyRelation

logger = logging.getLogger(__name__)


class GraphDB:
    """Stores dependency graph edges and NetworkX graph snapshots.

    Edges live in the ``dependency_edges`` table created by
    ``init_symbols_db``.  Full graph snapshots are serialised via
    :func:`networkx.node_link_data` and kept in the
    ``graph_snapshots`` table so the graph can be rebuilt without
    re-parsing every file.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def save_edges(self, edges: list[DependencyEdge]) -> None:
        """Save dependency edges to the database.

        Uses ``INSERT OR REPLACE`` so duplicate
        ``(source_symbol_id, target_symbol_id, relation)`` tuples are
        updated rather than raising a constraint violation.
        """
        if not edges:
            return

        conn = self._pool.get()
        for edge in edges:
            conn.execute(
                """
                INSERT OR REPLACE INTO dependency_edges
                    (source_symbol_id, target_symbol_id, relation,
                     source_file, target_file, line)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.source_symbol_id,
                    edge.target_symbol_id,
                    edge.relation.value
                    if isinstance(edge.relation, DependencyRelation)
                    else edge.relation,
                    edge.source_file,
                    edge.target_file,
                    edge.line,
                ),
            )
        conn.commit()
        logger.debug("Saved %d dependency edges to database", len(edges))

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def save_snapshot(self, graph: nx.DiGraph) -> None:
        """Save a NetworkX directed-graph snapshot to the database.

        The graph is serialised with :func:`networkx.node_link_data`
        using ``edges="edges"`` as required by the project specification,
        then stored as a JSON string alongside basic statistics.
        """
        data = nx.node_link_data(graph, edges="edges")
        graph_json = json.dumps(data)

        conn = self._pool.get()
        conn.execute(
            """
            INSERT INTO graph_snapshots
                (graph_json, node_count, edge_count, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (graph_json, graph.number_of_nodes(), graph.number_of_edges()),
        )
        conn.commit()
        logger.debug(
            "Saved graph snapshot: %d nodes, %d edges",
            graph.number_of_nodes(),
            graph.number_of_edges(),
        )

    def load_snapshot(self) -> nx.DiGraph | None:
        """Load the most recent graph snapshot from the database.

        Returns ``None`` when no snapshot has been persisted yet.  The
        graph is deserialised with :func:`networkx.node_link_graph`
        using ``edges="edges"`` to match the serialisation format.
        """
        conn = self._pool.get()
        row = conn.execute(
            "SELECT graph_json FROM graph_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if row is None:
            return None

        data = json.loads(row["graph_json"])
        graph: nx.DiGraph = nx.node_link_graph(data, edges="edges")
        logger.debug(
            "Loaded graph snapshot: %d nodes, %d edges",
            graph.number_of_nodes(),
            graph.number_of_edges(),
        )
        return graph

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete_by_file(self, file_path: str) -> None:
        """Delete all dependency edges involving *file_path*.

        Removes rows where the file appears as either the source or
        the target of an edge.
        """
        conn = self._pool.get()
        conn.execute(
            "DELETE FROM dependency_edges WHERE source_file = ? OR target_file = ?",
            (file_path, file_path),
        )
        conn.commit()
        logger.debug("Deleted dependency edges for file: %s", file_path)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_edges_for_file(self, file_path: str) -> list[DependencyEdge]:
        """Get all dependency edges for a given file.

        Returns edges where *file_path* is either the source or the
        target file.
        """
        conn = self._pool.get()
        cursor = conn.execute(
            """
            SELECT source_symbol_id, target_symbol_id, relation,
                   source_file, target_file, line
            FROM dependency_edges
            WHERE source_file = ? OR target_file = ?
            """,
            (file_path, file_path),
        )
        return [self._row_to_edge(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_edge(row: object) -> DependencyEdge:
        """Convert a ``sqlite3.Row`` to a :class:`DependencyEdge`."""
        return DependencyEdge(
            source_symbol_id=row["source_symbol_id"],
            target_symbol_id=row["target_symbol_id"],
            relation=DependencyRelation(row["relation"]),
            source_file=row["source_file"],
            target_file=row["target_file"],
            line=row["line"],
        )
