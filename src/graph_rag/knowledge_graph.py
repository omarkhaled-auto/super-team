"""NetworkX MultiDiGraph wrapper for the Graph RAG knowledge graph."""
from __future__ import annotations

import json
from typing import Any

import networkx as nx


class KnowledgeGraph:
    """Manages the unified knowledge graph as an nx.MultiDiGraph.

    Wraps common graph operations and provides serialization/deserialization
    via node_link_data/node_link_graph (JSON format).
    """

    def __init__(self) -> None:
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()

    def add_node(self, node_id: str, **attrs: Any) -> None:
        """Add a node with attributes to the graph."""
        self.graph.add_node(node_id, **attrs)

    def add_edge(self, u: str, v: str, key: str, **attrs: Any) -> None:
        """Add an edge with a key and attributes."""
        self.graph.add_edge(u, v, key=key, **attrs)

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Return node attributes as dict, or None if not present."""
        if node_id in self.graph:
            return dict(self.graph.nodes[node_id])
        return None

    def get_ego_subgraph(
        self,
        node_id: str,
        radius: int = 2,
        undirected: bool = True,
    ) -> nx.MultiDiGraph:
        """Extract the N-hop neighborhood around *node_id*.

        When *undirected* is True the traversal follows edges in both
        directions.  The returned subgraph is always a MultiDiGraph
        (directed view of the ego graph).
        """
        if node_id not in self.graph:
            return nx.MultiDiGraph()

        if undirected:
            G_traversal = self.graph.to_undirected()
        else:
            G_traversal = self.graph

        ego = nx.ego_graph(G_traversal, node_id, radius=radius)

        # Return the directed subgraph induced by the ego nodes
        return self.graph.subgraph(ego.nodes()).copy()

    def compute_pagerank(self) -> dict[str, float]:
        """Compute PageRank scores for all nodes.

        Returns dict mapping node_id -> pagerank score.
        """
        if len(self.graph) == 0:
            return {}
        return nx.pagerank(self.graph, alpha=0.85)

    def compute_communities(
        self,
        resolution: float = 1.0,
        seed: int = 42,
    ) -> list[set[str]]:
        """Detect communities using Louvain on the undirected projection.

        Returns a list of sets, each set containing node IDs in one community.
        """
        if len(self.graph) == 0:
            return []

        G_undirected = self.graph.to_undirected()
        return list(
            nx.community.louvain_communities(
                G_undirected,
                resolution=resolution,
                seed=seed,
            )
        )

    def get_shortest_path(
        self,
        source: str,
        target: str,
        undirected: bool = True,
    ) -> list[str] | None:
        """Find shortest path between two nodes.

        Returns None if no path exists.
        """
        try:
            if undirected:
                G = self.graph.to_undirected()
            else:
                G = self.graph
            return nx.shortest_path(G, source, target)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def get_descendants(self, node_id: str, max_depth: int = 3) -> set[str]:
        """BFS forward from *node_id* up to *max_depth* hops."""
        if node_id not in self.graph:
            return set()
        lengths = nx.single_source_shortest_path_length(
            self.graph, node_id, cutoff=max_depth
        )
        result = set(lengths.keys())
        result.discard(node_id)
        return result

    def get_ancestors(self, node_id: str, max_depth: int = 3) -> set[str]:
        """BFS backward (reverse graph) from *node_id* up to *max_depth* hops."""
        if node_id not in self.graph:
            return set()
        reversed_graph = self.graph.reverse(copy=False)
        lengths = nx.single_source_shortest_path_length(
            reversed_graph, node_id, cutoff=max_depth
        )
        result = set(lengths.keys())
        result.discard(node_id)
        return result

    def to_json(self) -> str:
        """Serialize the graph to a JSON string via node_link_data."""
        data = nx.node_link_data(self.graph, edges="edges")
        return json.dumps(data)

    def from_json(self, json_str: str) -> None:
        """Deserialize a graph from a JSON string via node_link_graph."""
        data = json.loads(json_str)
        self.graph = nx.node_link_graph(
            data,
            edges="edges",
            multigraph=True,
            directed=True,
        )

    def clear(self) -> None:
        """Remove all nodes and edges."""
        self.graph.clear()

    def __len__(self) -> int:
        return len(self.graph)

    def node_count(self) -> int:
        """Return the number of nodes."""
        return len(self.graph.nodes)

    def edge_count(self) -> int:
        """Return the number of edges."""
        return len(self.graph.edges)
