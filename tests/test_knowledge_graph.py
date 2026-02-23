"""Unit tests for Graph RAG KnowledgeGraph."""
from __future__ import annotations

import pytest
import networkx as nx

from src.graph_rag.knowledge_graph import KnowledgeGraph


class TestAddNode:
    def test_add_node_creates_node_with_attributes(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("file::src/auth.py", node_type="file", language="python", service_name="auth")

        attrs = kg.get_node("file::src/auth.py")
        assert attrs is not None
        assert attrs["node_type"] == "file"
        assert attrs["language"] == "python"
        assert attrs["service_name"] == "auth"


class TestAddEdge:
    def test_add_edge_creates_edge_with_key(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("A")
        kg.add_node("B")
        kg.add_edge("A", "B", key="IMPORTS")

        edges = list(kg.graph.edges("A", keys=True))
        assert len(edges) == 1
        assert edges[0] == ("A", "B", "IMPORTS")

    def test_multiple_edges_between_same_nodes(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("A")
        kg.add_node("B")
        kg.add_edge("A", "B", key="IMPORTS")
        kg.add_edge("A", "B", key="CALLS")

        edges = list(kg.graph.edges("A", keys=True))
        assert len(edges) == 2
        edge_keys = {e[2] for e in edges}
        assert edge_keys == {"IMPORTS", "CALLS"}


class TestGetNode:
    def test_get_node_returns_attributes(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("node1", alpha="a", beta=2, gamma=True)

        attrs = kg.get_node("node1")
        assert attrs is not None
        assert attrs["alpha"] == "a"
        assert attrs["beta"] == 2
        assert attrs["gamma"] is True

    def test_get_node_returns_none_for_missing(self) -> None:
        kg = KnowledgeGraph()
        assert kg.get_node("nonexistent") is None


class TestEgoSubgraph:
    def test_get_ego_subgraph_respects_radius(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("A")
        kg.add_node("B")
        kg.add_node("C")
        kg.add_edge("A", "B", key="IMPORTS")
        kg.add_edge("B", "C", key="IMPORTS")

        # radius=1 from A in directed mode should include only A and B
        sub = kg.get_ego_subgraph("A", radius=1, undirected=False)
        assert "A" in sub.nodes()
        assert "B" in sub.nodes()
        assert "C" not in sub.nodes()

    def test_get_ego_subgraph_undirected(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("A")
        kg.add_node("B")
        kg.add_node("C")
        kg.add_edge("A", "B", key="IMPORTS")
        kg.add_edge("B", "C", key="IMPORTS")

        # undirected=True, radius=1 from B should include all three
        sub = kg.get_ego_subgraph("B", radius=1, undirected=True)
        assert set(sub.nodes()) == {"A", "B", "C"}


class TestPagerank:
    def test_compute_pagerank_returns_scores(self) -> None:
        kg = KnowledgeGraph()
        # Star topology: hub with 5 spokes pointing to it
        kg.add_node("hub")
        for i in range(5):
            leaf = f"leaf_{i}"
            kg.add_node(leaf)
            kg.add_edge(leaf, "hub", key="IMPORTS")

        scores = kg.compute_pagerank()
        assert len(scores) == 6
        # Hub should have the highest score
        assert scores["hub"] == max(scores.values())
        # Scores should sum to approximately 1.0
        assert abs(sum(scores.values()) - 1.0) < 0.01


class TestCommunities:
    def test_compute_communities_returns_sets(self) -> None:
        kg = KnowledgeGraph()
        # Two disconnected 4-node cliques
        for i in range(4):
            kg.add_node(f"A{i}")
        for i in range(4):
            for j in range(i + 1, 4):
                kg.add_edge(f"A{i}", f"A{j}", key="CALLS")
                kg.add_edge(f"A{j}", f"A{i}", key="CALLS")

        for i in range(4):
            kg.add_node(f"B{i}")
        for i in range(4):
            for j in range(i + 1, 4):
                kg.add_edge(f"B{i}", f"B{j}", key="CALLS")
                kg.add_edge(f"B{j}", f"B{i}", key="CALLS")

        communities = kg.compute_communities()
        assert len(communities) == 2
        all_members = set()
        for c in communities:
            all_members.update(c)
        assert len(all_members) == 8


class TestShortestPath:
    def test_get_shortest_path_finds_path(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("A")
        kg.add_node("B")
        kg.add_node("C")
        kg.add_edge("A", "B", key="IMPORTS")
        kg.add_edge("B", "C", key="IMPORTS")

        path = kg.get_shortest_path("A", "C", undirected=False)
        assert path == ["A", "B", "C"]

    def test_get_shortest_path_no_path_returns_none(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("X")
        kg.add_node("Y")
        # No edges between them, directed mode
        assert kg.get_shortest_path("X", "Y", undirected=False) is None


class TestDescendantsAncestors:
    def test_get_descendants_respects_max_depth(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("A")
        kg.add_node("B")
        kg.add_node("C")
        kg.add_node("D")
        kg.add_edge("A", "B", key="IMPORTS")
        kg.add_edge("B", "C", key="IMPORTS")
        kg.add_edge("C", "D", key="IMPORTS")

        desc = kg.get_descendants("A", max_depth=1)
        assert desc == {"B"}

    def test_get_ancestors_returns_predecessors(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("A")
        kg.add_node("B")
        kg.add_node("C")
        kg.add_edge("A", "B", key="IMPORTS")
        kg.add_edge("B", "C", key="IMPORTS")

        ancestors = kg.get_ancestors("C")
        assert ancestors == {"A", "B"}


class TestSerialization:
    def test_to_json_and_from_json_roundtrip(self) -> None:
        kg = KnowledgeGraph()
        # Add 5 nodes
        for i in range(5):
            kg.add_node(f"node_{i}", label=f"label_{i}", index=i)
        # Add 8 edges
        edges = [
            (0, 1), (0, 2), (1, 2), (1, 3),
            (2, 3), (2, 4), (3, 4), (4, 0),
        ]
        for u, v in edges:
            kg.add_edge(f"node_{u}", f"node_{v}", key="IMPORTS")

        json_str = kg.to_json()

        # Clear and deserialize
        kg2 = KnowledgeGraph()
        kg2.from_json(json_str)

        assert kg2.node_count() == 5
        assert kg2.edge_count() == 8
        for i in range(5):
            attrs = kg2.get_node(f"node_{i}")
            assert attrs is not None
            assert attrs["label"] == f"label_{i}"


class TestClear:
    def test_clear_removes_all_nodes_and_edges(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("A")
        kg.add_node("B")
        kg.add_edge("A", "B", key="IMPORTS")

        kg.clear()
        assert kg.node_count() == 0
        assert kg.edge_count() == 0
