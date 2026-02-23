"""Graph property tests for Graph RAG."""
from __future__ import annotations

import pytest
import networkx as nx

from src.graph_rag.knowledge_graph import KnowledgeGraph
from src.shared.models.graph_rag import NodeType, EdgeType


def _build_property_graph() -> KnowledgeGraph:
    """Build a small graph with properly formatted node IDs and edge keys."""
    kg = KnowledgeGraph()

    # Services
    kg.add_node("service::auth-service", node_type=NodeType.SERVICE.value, service_name="auth-service")
    kg.add_node("service::order-service", node_type=NodeType.SERVICE.value, service_name="order-service")

    # Files
    kg.add_node("file::src/auth/main.py", node_type=NodeType.FILE.value,
                file_path="src/auth/main.py", service_name="auth-service")
    kg.add_node("file::src/order/main.py", node_type=NodeType.FILE.value,
                file_path="src/order/main.py", service_name="order-service")

    # Symbols
    kg.add_node("symbol::src/auth/main.py::AuthService", node_type=NodeType.SYMBOL.value,
                symbol_name="AuthService", service_name="auth-service")

    # Contract
    kg.add_node("contract::auth-api", node_type=NodeType.CONTRACT.value,
                contract_id="auth-api", service_name="auth-service")

    # Endpoint
    kg.add_node("endpoint::auth-service::POST::/login", node_type=NodeType.ENDPOINT.value,
                method="POST", path="/login", service_name="auth-service")

    # Domain entity
    kg.add_node("domain_entity::user", node_type=NodeType.DOMAIN_ENTITY.value,
                entity_name="User", owning_service="auth-service")

    # Event -- node ID omits service name per SCH-1
    kg.add_node("event::order.created", node_type=NodeType.EVENT.value,
                event_name="order.created", channel="order.created")

    # Edges with EdgeType values as keys
    kg.add_edge("service::auth-service", "file::src/auth/main.py",
                key=EdgeType.CONTAINS_FILE.value)
    kg.add_edge("file::src/auth/main.py", "symbol::src/auth/main.py::AuthService",
                key=EdgeType.DEFINES_SYMBOL.value)
    kg.add_edge("service::auth-service", "contract::auth-api",
                key=EdgeType.PROVIDES_CONTRACT.value)
    kg.add_edge("contract::auth-api", "endpoint::auth-service::POST::/login",
                key=EdgeType.EXPOSES_ENDPOINT.value)
    kg.add_edge("service::auth-service", "domain_entity::user",
                key=EdgeType.OWNS_ENTITY.value)
    kg.add_edge("service::order-service", "event::order.created",
                key=EdgeType.PUBLISHES_EVENT.value)
    kg.add_edge("service::auth-service", "event::order.created",
                key=EdgeType.CONSUMES_EVENT.value)
    kg.add_edge("file::src/order/main.py", "file::src/auth/main.py",
                key=EdgeType.IMPORTS.value)
    kg.add_edge("service::order-service", "service::auth-service",
                key=EdgeType.SERVICE_CALLS.value,
                via_endpoint="endpoint::auth-service::POST::/login")

    return kg


# Collect all valid EdgeType string values
_VALID_EDGE_TYPE_VALUES = {e.value for e in EdgeType}

# Collect all valid NodeType string values
_VALID_NODE_TYPE_VALUES = {e.value for e in NodeType}

# Expected prefixes for each node type
_NODE_ID_PREFIXES = {
    NodeType.FILE.value: "file::",
    NodeType.SERVICE.value: "service::",
    NodeType.SYMBOL.value: "symbol::",
    NodeType.CONTRACT.value: "contract::",
    NodeType.ENDPOINT.value: "endpoint::",
    NodeType.DOMAIN_ENTITY.value: "domain_entity::",
    NodeType.EVENT.value: "event::",
}


class TestNodeIdFormat:
    def test_node_ids_follow_specified_format(self) -> None:
        kg = _build_property_graph()

        for node_id, attrs in kg.graph.nodes(data=True):
            node_type = attrs.get("node_type", "")
            expected_prefix = _NODE_ID_PREFIXES.get(node_type, "")
            assert node_id.startswith(expected_prefix), (
                f"Node '{node_id}' of type '{node_type}' should start with '{expected_prefix}'"
            )


class TestEdgeKeys:
    def test_edge_keys_are_edge_type_strings(self) -> None:
        kg = _build_property_graph()

        for u, v, key in kg.graph.edges(keys=True):
            assert key in _VALID_EDGE_TYPE_VALUES, (
                f"Edge ({u} -> {v}) has key '{key}' which is not a valid EdgeType value"
            )


class TestEventNodeId:
    def test_event_node_id_omits_service_name(self) -> None:
        kg = _build_property_graph()

        event_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.EVENT.value
        ]
        for event_node in event_nodes:
            # Event node IDs should be "event::<event_name>" without service name
            parts = event_node.split("::")
            assert len(parts) == 2, (
                f"Event node '{event_node}' should have format 'event::<event_name>', "
                f"not include service name"
            )
            assert parts[0] == "event"


class TestServiceCallsEdge:
    def test_service_calls_edge_has_via_endpoint(self) -> None:
        kg = _build_property_graph()

        service_calls_edges = [
            (u, v, k, d) for u, v, k, d in kg.graph.edges(keys=True, data=True)
            if k == EdgeType.SERVICE_CALLS.value
        ]

        assert len(service_calls_edges) > 0
        for u, v, k, data in service_calls_edges:
            # SERVICE_CALLS edges should have via_endpoint attribute
            assert "via_endpoint" in data, (
                f"SERVICE_CALLS edge ({u} -> {v}) missing 'via_endpoint' attribute"
            )


class TestCommunitiesStability:
    def test_louvain_community_ids_stable(self) -> None:
        kg = _build_property_graph()

        communities_1 = kg.compute_communities(seed=42)
        communities_2 = kg.compute_communities(seed=42)

        # Same seed should produce same community assignments
        assert len(communities_1) == len(communities_2)
        for c1, c2 in zip(
            sorted(communities_1, key=lambda s: sorted(s)),
            sorted(communities_2, key=lambda s: sorted(s)),
        ):
            assert c1 == c2


class TestPagerankCentralNode:
    def test_pagerank_central_node_highest(self) -> None:
        kg = KnowledgeGraph()
        # Star graph: hub receives edges from 5 leaves
        kg.add_node("hub", node_type="service")
        for i in range(5):
            leaf = f"leaf_{i}"
            kg.add_node(leaf, node_type="file")
            kg.add_edge(leaf, "hub", key=EdgeType.IMPORTS.value)

        scores = kg.compute_pagerank()
        assert scores["hub"] == max(scores.values())


class TestGraphType:
    def test_graph_is_multidigraph(self) -> None:
        kg = KnowledgeGraph()
        assert isinstance(kg.graph, nx.MultiDiGraph)


class TestNodeTypeAttribute:
    def test_all_node_types_have_node_type_attribute(self) -> None:
        kg = _build_property_graph()

        for node_id, attrs in kg.graph.nodes(data=True):
            assert "node_type" in attrs, (
                f"Node '{node_id}' is missing 'node_type' attribute"
            )
            assert attrs["node_type"] in _VALID_NODE_TYPE_VALUES, (
                f"Node '{node_id}' has invalid node_type '{attrs['node_type']}'"
            )


class TestEdgeKeyValidity:
    def test_all_edges_have_valid_key(self) -> None:
        kg = _build_property_graph()

        for u, v, key in kg.graph.edges(keys=True):
            assert key in _VALID_EDGE_TYPE_VALUES, (
                f"Edge ({u} -> {v}) has invalid key '{key}', "
                f"must be one of {_VALID_EDGE_TYPE_VALUES}"
            )


class TestEndpointExposeEdge:
    """Every endpoint node must have an incoming EXPOSES_ENDPOINT edge.

    Catches orphaned endpoints that were created without being linked to
    a contract node.
    """

    def test_all_endpoints_have_incoming_exposes_endpoint(self) -> None:
        kg = _build_property_graph()

        endpoint_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.ENDPOINT.value
        ]
        assert len(endpoint_nodes) > 0, "Test graph must contain endpoint nodes"

        for ep_node in endpoint_nodes:
            incoming_expose = [
                (u, v, k)
                for u, v, k in kg.graph.in_edges(ep_node, keys=True)
                if k == EdgeType.EXPOSES_ENDPOINT.value
            ]
            assert len(incoming_expose) >= 1, (
                f"Endpoint node '{ep_node}' has no incoming EXPOSES_ENDPOINT edge — "
                f"orphaned endpoint"
            )
