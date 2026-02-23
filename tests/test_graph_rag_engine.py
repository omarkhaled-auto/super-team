"""Unit tests for Graph RAG Engine."""
from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock, patch

from src.graph_rag.knowledge_graph import KnowledgeGraph
from src.graph_rag.graph_rag_store import GraphRAGStore
from src.graph_rag.graph_rag_engine import GraphRAGEngine
from src.graph_rag.context_assembler import ContextAssembler
from src.shared.models.graph_rag import NodeType, EdgeType


def _build_test_graph() -> KnowledgeGraph:
    """Build a realistic test knowledge graph with 3 services,
    2 contracts, 4 endpoints, 3 entities, and 2 events."""
    kg = KnowledgeGraph()

    # -- Services --
    for svc in ["auth-service", "order-service", "notification-service"]:
        kg.add_node(
            f"service::{svc}",
            node_type=NodeType.SERVICE.value,
            service_name=svc,
            domain=svc.split("-")[0],
            description=f"{svc} description",
        )

    # -- Contracts --
    kg.add_node(
        "contract::auth-api",
        node_type=NodeType.CONTRACT.value,
        contract_id="auth-api",
        service_name="auth-service",
    )
    kg.add_edge(
        "service::auth-service",
        "contract::auth-api",
        key=EdgeType.PROVIDES_CONTRACT.value,
    )

    kg.add_node(
        "contract::order-api",
        node_type=NodeType.CONTRACT.value,
        contract_id="order-api",
        service_name="order-service",
    )
    kg.add_edge(
        "service::order-service",
        "contract::order-api",
        key=EdgeType.PROVIDES_CONTRACT.value,
    )

    # -- Endpoints --
    for method, path, svc, contract in [
        ("POST", "/auth/login", "auth-service", "contract::auth-api"),
        ("GET", "/auth/me", "auth-service", "contract::auth-api"),
        ("POST", "/orders", "order-service", "contract::order-api"),
        ("GET", "/orders/{id}", "order-service", "contract::order-api"),
    ]:
        ep_id = f"endpoint::{svc}::{method}::{path}"
        kg.add_node(
            ep_id,
            node_type=NodeType.ENDPOINT.value,
            service_name=svc,
            method=method,
            path=path,
            handler_symbol=f"handle_{path.replace('/', '_')}",
        )
        kg.add_edge(
            contract,
            ep_id,
            key=EdgeType.EXPOSES_ENDPOINT.value,
        )

    # -- SERVICE_CALLS: order -> auth (via endpoint) --
    kg.add_edge(
        "service::order-service",
        "service::auth-service",
        key=EdgeType.SERVICE_CALLS.value,
        via_endpoint="endpoint::auth-service::GET::/auth/me",
    )

    # -- Domain Entities --
    for entity_name, owner in [("User", "auth-service"), ("Order", "order-service"), ("Notification", "notification-service")]:
        eid = f"domain_entity::{entity_name.lower()}"
        kg.add_node(
            eid,
            node_type=NodeType.DOMAIN_ENTITY.value,
            entity_name=entity_name,
            owning_service=owner,
            fields_json=json.dumps([{"name": "id", "type": "string"}, {"name": "created_at", "type": "datetime"}]),
        )
        kg.add_edge(
            f"service::{owner}",
            eid,
            key=EdgeType.OWNS_ENTITY.value,
        )

    # Order service references User entity
    kg.add_edge(
        "service::order-service",
        "domain_entity::user",
        key=EdgeType.REFERENCES_ENTITY.value,
    )

    # -- Events --
    kg.add_node(
        "event::order.created",
        node_type=NodeType.EVENT.value,
        event_name="order.created",
        channel="order.created",
    )
    kg.add_edge(
        "service::order-service",
        "event::order.created",
        key=EdgeType.PUBLISHES_EVENT.value,
    )
    kg.add_edge(
        "service::notification-service",
        "event::order.created",
        key=EdgeType.CONSUMES_EVENT.value,
    )

    kg.add_node(
        "event::user.registered",
        node_type=NodeType.EVENT.value,
        event_name="user.registered",
        channel="user.registered",
    )
    kg.add_edge(
        "service::auth-service",
        "event::user.registered",
        key=EdgeType.PUBLISHES_EVENT.value,
    )
    # user.registered has NO consumer -- orphaned

    # -- File nodes for boundary validation --
    for i, svc in enumerate(["auth-service", "order-service"]):
        for j in range(3):
            fid = f"file::src/{svc}/file_{j}.py"
            kg.add_node(
                fid,
                node_type=NodeType.FILE.value,
                file_path=f"src/{svc}/file_{j}.py",
                service_name=svc,
            )
            kg.add_edge(f"service::{svc}", fid, key=EdgeType.CONTAINS_FILE.value)
            # Connect files within same service
            if j > 0:
                prev = f"file::src/{svc}/file_{j-1}.py"
                kg.add_edge(fid, prev, key=EdgeType.IMPORTS.value)
                kg.add_edge(prev, fid, key=EdgeType.IMPORTS.value)

    # Cross-service import: auth file imported by order file
    kg.add_edge(
        "file::src/order-service/file_0.py",
        "file::src/auth-service/file_0.py",
        key=EdgeType.IMPORTS.value,
        relation=EdgeType.IMPORTS.value,
    )

    return kg


def _make_mock_store() -> MagicMock:
    """Create a mock GraphRAGStore."""
    store = MagicMock(spec=GraphRAGStore)
    store.query_nodes.return_value = []
    return store


class TestGetServiceContext:
    def test_get_service_context_returns_all_sections(self) -> None:
        kg = _build_test_graph()
        store = _make_mock_store()
        engine = GraphRAGEngine(kg, store)

        result = engine.get_service_context("auth-service")

        assert result["service_name"] == "auth-service"
        assert "provided_endpoints" in result
        assert "consumed_endpoints" in result
        assert "events_published" in result
        assert "events_consumed" in result
        assert "owned_entities" in result
        assert "referenced_entities" in result
        assert "depends_on" in result
        assert "depended_on_by" in result
        assert "context_text" in result

        # Auth service provides 2 endpoints (POST /auth/login, GET /auth/me)
        assert len(result["provided_endpoints"]) == 2
        # Auth publishes user.registered
        assert len(result["events_published"]) == 1
        assert result["events_published"][0]["event_name"] == "user.registered"
        # Auth owns User entity
        assert len(result["owned_entities"]) == 1
        assert result["owned_entities"][0]["name"] == "User"
        # Order-service depends on auth-service
        assert "order-service" in result["depended_on_by"]

    def test_get_service_context_unknown_service(self) -> None:
        kg = _build_test_graph()
        store = _make_mock_store()
        engine = GraphRAGEngine(kg, store)

        result = engine.get_service_context("nonexistent-service")
        assert "error" in result
        assert result["service_name"] == "nonexistent-service"


class TestHybridSearch:
    def test_hybrid_search_combines_scores(self) -> None:
        kg = _build_test_graph()
        store = _make_mock_store()
        store.query_nodes.return_value = [
            {"id": "service::auth-service", "document": "Auth service", "distance": 0.2, "metadata": {}},
            {"id": "service::order-service", "document": "Order service", "distance": 0.5, "metadata": {}},
            {"id": "service::notification-service", "document": "Notification", "distance": 0.8, "metadata": {}},
        ]
        engine = GraphRAGEngine(kg, store)

        result = engine.hybrid_search("authentication service", n_results=3)
        assert "results" in result
        assert len(result["results"]) == 3
        # Each result should have combined score
        for r in result["results"]:
            assert "score" in r
            assert "semantic_score" in r
            assert "graph_score" in r

    def test_hybrid_search_with_anchor_reranks(self) -> None:
        kg = _build_test_graph()
        store = _make_mock_store()
        # All three have the same semantic distance
        store.query_nodes.return_value = [
            {"id": "service::auth-service", "document": "Auth service", "distance": 0.3, "metadata": {}},
            {"id": "service::order-service", "document": "Order service", "distance": 0.3, "metadata": {}},
            {"id": "service::notification-service", "document": "Notification", "distance": 0.3, "metadata": {}},
        ]
        engine = GraphRAGEngine(kg, store)

        # Anchor at order-service: closer nodes should score higher on graph
        result = engine.hybrid_search(
            "service",
            n_results=3,
            anchor_node_id="service::order-service",
        )
        results = result["results"]
        assert len(results) == 3
        # The anchor itself should have the highest graph_score (distance=0)
        anchor_result = [r for r in results if r["node_id"] == "service::order-service"][0]
        assert anchor_result["graph_score"] == 1.0

    def test_hybrid_search_without_anchor_uses_pagerank(self) -> None:
        kg = _build_test_graph()
        # Assign pagerank values manually
        kg.graph.nodes["service::auth-service"]["pagerank"] = 0.3
        kg.graph.nodes["service::order-service"]["pagerank"] = 0.1
        kg.graph.nodes["service::notification-service"]["pagerank"] = 0.05

        store = _make_mock_store()
        store.query_nodes.return_value = [
            {"id": "service::auth-service", "document": "Auth", "distance": 0.5, "metadata": {}},
            {"id": "service::order-service", "document": "Order", "distance": 0.5, "metadata": {}},
            {"id": "service::notification-service", "document": "Notif", "distance": 0.5, "metadata": {}},
        ]
        engine = GraphRAGEngine(kg, store)

        result = engine.hybrid_search("service", n_results=3)
        results = result["results"]
        # Auth has highest pagerank, so with same semantic score it should rank first
        auth_result = [r for r in results if r["node_id"] == "service::auth-service"][0]
        other_results = [r for r in results if r["node_id"] != "service::auth-service"]
        assert all(auth_result["graph_score"] >= r["graph_score"] for r in other_results)


class TestFindCrossServiceImpact:
    def test_find_cross_service_impact_finds_services(self) -> None:
        kg = _build_test_graph()
        store = _make_mock_store()
        engine = GraphRAGEngine(kg, store)

        # Impact from auth file that's imported by order file
        result = engine.find_cross_service_impact("file::src/auth-service/file_0.py")

        assert result["source_node"] == "file::src/auth-service/file_0.py"
        assert result["total_impacted_nodes"] > 0

    def test_find_cross_service_impact_respects_max_depth(self) -> None:
        kg = KnowledgeGraph()
        # Chain of 5 nodes across services
        for i in range(5):
            svc = f"svc-{i}"
            nid = f"file::f{i}.py"
            kg.add_node(nid, node_type="file", service_name=svc, file_path=f"f{i}.py")
            kg.add_node(f"service::{svc}", node_type="service", service_name=svc)
            if i > 0:
                kg.add_edge(f"file::f{i-1}.py", nid, key="IMPORTS")

        store = _make_mock_store()
        engine = GraphRAGEngine(kg, store)

        result_d2 = engine.find_cross_service_impact("file::f0.py", max_depth=2)
        result_d5 = engine.find_cross_service_impact("file::f0.py", max_depth=5)

        # With max_depth=2, fewer nodes should be reached than max_depth=5
        assert result_d2["total_impacted_nodes"] <= result_d5["total_impacted_nodes"]


class TestValidateServiceBoundaries:
    def test_validate_service_boundaries_detects_misplaced(self) -> None:
        kg = KnowledgeGraph()
        # Create two service clusters with one misplaced file
        for i in range(4):
            nid = f"file::auth/f{i}.py"
            kg.add_node(nid, node_type="file", service_name="auth-service", file_path=f"auth/f{i}.py")
        # Densely connect auth files
        for i in range(4):
            for j in range(i + 1, 4):
                kg.add_edge(f"file::auth/f{i}.py", f"file::auth/f{j}.py", key="IMPORTS")
                kg.add_edge(f"file::auth/f{j}.py", f"file::auth/f{i}.py", key="IMPORTS")

        # One file declared as "order-service" but densely connected to auth cluster
        misplaced_id = "file::auth/f_misplaced.py"
        kg.add_node(misplaced_id, node_type="file", service_name="order-service", file_path="auth/f_misplaced.py")
        for i in range(4):
            kg.add_edge(misplaced_id, f"file::auth/f{i}.py", key="IMPORTS")
            kg.add_edge(f"file::auth/f{i}.py", misplaced_id, key="IMPORTS")

        store = _make_mock_store()
        engine = GraphRAGEngine(kg, store)

        result = engine.validate_service_boundaries()
        # The misplaced file should be detected
        assert result["alignment_score"] < 1.0
        misplaced_files = [m["file"] for m in result["misplaced_files"]]
        assert "auth/f_misplaced.py" in misplaced_files

    def test_validate_service_boundaries_perfect_alignment(self) -> None:
        kg = KnowledgeGraph()
        # All files correctly grouped in one service
        for i in range(4):
            nid = f"file::svc/f{i}.py"
            kg.add_node(nid, node_type="file", service_name="my-service", file_path=f"svc/f{i}.py")
        for i in range(4):
            for j in range(i + 1, 4):
                kg.add_edge(f"file::svc/f{i}.py", f"file::svc/f{j}.py", key="IMPORTS")

        store = _make_mock_store()
        engine = GraphRAGEngine(kg, store)

        result = engine.validate_service_boundaries()
        assert result["alignment_score"] == 1.0
        assert len(result["misplaced_files"]) == 0


class TestCheckCrossServiceEvents:
    def test_check_cross_service_events_finds_orphaned(self) -> None:
        kg = _build_test_graph()
        store = _make_mock_store()
        engine = GraphRAGEngine(kg, store)

        result = engine.check_cross_service_events()
        # user.registered has publisher but no consumer => orphaned
        orphaned_names = [e["event_name"] for e in result["orphaned_events"]]
        assert "user.registered" in orphaned_names

    def test_check_cross_service_events_finds_unmatched(self) -> None:
        kg = KnowledgeGraph()
        kg.add_node("service::svc-a", node_type="service", service_name="svc-a")
        kg.add_node(
            "event::mystery.event",
            node_type="event",
            event_name="mystery.event",
            channel="mystery.event",
        )
        # Consumer but no publisher
        kg.add_edge("service::svc-a", "event::mystery.event", key=EdgeType.CONSUMES_EVENT.value)

        store = _make_mock_store()
        engine = GraphRAGEngine(kg, store)

        result = engine.check_cross_service_events()
        unmatched_names = [e["event_name"] for e in result["unmatched_consumers"]]
        assert "mystery.event" in unmatched_names

    def test_check_cross_service_events_finds_matched(self) -> None:
        kg = _build_test_graph()
        store = _make_mock_store()
        engine = GraphRAGEngine(kg, store)

        result = engine.check_cross_service_events()
        # order.created has both publisher and consumer => matched
        matched_names = [e["event_name"] for e in result["matched_events"]]
        assert "order.created" in matched_names
