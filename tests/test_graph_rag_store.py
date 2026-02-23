"""Unit tests for Graph RAG ChromaDB store."""
from __future__ import annotations

import pytest

from src.graph_rag.graph_rag_store import GraphRAGStore
from src.shared.models.graph_rag import GraphRAGContextRecord, GraphRAGNodeRecord


def _make_node_record(
    id: str,
    document: str,
    node_type: str = "file",
    service_name: str = "",
    language: str = "python",
    community_id: int = -1,
    pagerank: float = 0.0,
) -> GraphRAGNodeRecord:
    return GraphRAGNodeRecord(
        id=id,
        document=document,
        node_type=node_type,
        service_name=service_name,
        language=language,
        community_id=community_id,
        pagerank=pagerank,
    )


class TestUpsertNodes:
    def test_upsert_nodes_creates_records(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = [
            _make_node_record("n1", "First node about authentication"),
            _make_node_record("n2", "Second node about user login"),
            _make_node_record("n3", "Third node about session management"),
        ]
        store.upsert_nodes(records)
        assert store.node_count() == 3

    def test_upsert_nodes_idempotent(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = [
            _make_node_record("n1", "First node about authentication"),
            _make_node_record("n2", "Second node about user login"),
            _make_node_record("n3", "Third node about session management"),
        ]
        store.upsert_nodes(records)
        store.upsert_nodes(records)  # second upsert
        assert store.node_count() == 3


class TestQueryNodes:
    def test_query_nodes_returns_results(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = [
            _make_node_record("n1", "Authentication service handles login and signup"),
            _make_node_record("n2", "Auth module processes JWT tokens and sessions"),
            _make_node_record("n3", "Database migration for user table schema"),
            _make_node_record("n4", "Payment processing stripe integration"),
            _make_node_record("n5", "Notification service sends email alerts"),
        ]
        store.upsert_nodes(records)

        results = store.query_nodes("login auth", n_results=5)
        assert len(results) > 0
        assert all("id" in r for r in results)

    def test_query_nodes_with_where_filter(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = []
        for i in range(5):
            records.append(
                _make_node_record(
                    f"svc_{i}",
                    f"Service node number {i} for authentication",
                    node_type="service",
                )
            )
        for i in range(5):
            records.append(
                _make_node_record(
                    f"file_{i}",
                    f"File node number {i} for authentication",
                    node_type="file",
                )
            )
        store.upsert_nodes(records)

        results = store.query_nodes(
            "authentication",
            n_results=10,
            node_types=["service"],
        )
        assert len(results) > 0
        for r in results:
            assert r["metadata"]["node_type"] == "service"

    def test_query_nodes_with_service_filter(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = []
        for i in range(3):
            records.append(
                _make_node_record(
                    f"auth_{i}",
                    f"Auth service file {i} handling user authentication",
                    service_name="auth-service",
                )
            )
        for i in range(3):
            records.append(
                _make_node_record(
                    f"order_{i}",
                    f"Order service file {i} handling order processing",
                    service_name="order-service",
                )
            )
        store.upsert_nodes(records)

        results = store.query_nodes(
            "service file handling",
            n_results=6,
            service_name="auth-service",
        )
        assert len(results) > 0
        for r in results:
            assert r["metadata"]["service_name"] == "auth-service"


class TestUpsertContexts:
    def test_upsert_contexts_creates_records(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = [
            GraphRAGContextRecord(
                id="ctx1",
                document="Service context for auth-service: handles authentication",
                context_type="service",
                service_name="auth-service",
                node_count=10,
                edge_count=15,
            ),
            GraphRAGContextRecord(
                id="ctx2",
                document="Service context for order-service: handles orders",
                context_type="service",
                service_name="order-service",
                node_count=8,
                edge_count=12,
            ),
        ]
        store.upsert_contexts(records)
        assert store.context_count() == 2

    def test_query_contexts_returns_summaries(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = [
            GraphRAGContextRecord(
                id="ctx1",
                document="Service context for auth-service: manages user authentication and JWT tokens",
                context_type="service",
                service_name="auth-service",
                node_count=10,
                edge_count=15,
            ),
        ]
        store.upsert_contexts(records)

        results = store.query_contexts("authentication service")
        assert len(results) > 0
        assert results[0]["id"] == "ctx1"


class TestDelete:
    def test_delete_all_nodes_clears_collection(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = [
            _make_node_record(f"n{i}", f"Node document {i} about testing")
            for i in range(10)
        ]
        store.upsert_nodes(records)
        assert store.node_count() == 10

        store.delete_all_nodes()
        assert store.node_count() == 0

    def test_delete_all_contexts_clears_collection(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = [
            GraphRAGContextRecord(
                id=f"ctx{i}",
                document=f"Context document {i} about service operations",
                context_type="service",
                node_count=5,
                edge_count=8,
            )
            for i in range(5)
        ]
        store.upsert_contexts(records)
        assert store.context_count() == 5

        store.delete_all_contexts()
        assert store.context_count() == 0


class TestBatchUpsert:
    def test_batch_upsert_300_records(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        records = [
            _make_node_record(
                f"node_{i:04d}",
                f"Unique document content for node {i} about file processing and service integration",
            )
            for i in range(300)
        ]
        store.upsert_nodes(records)
        assert store.node_count() == 300


class TestEdgeCases:
    def test_none_metadata_values_converted(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        record = GraphRAGNodeRecord(
            id="n_none",
            document="Node with None service name for testing",
            node_type="file",
            service_name=None,  # type: ignore[arg-type]
            language=None,  # type: ignore[arg-type]
            community_id=None,  # type: ignore[arg-type]
            pagerank=None,  # type: ignore[arg-type]
        )
        # Should not raise
        store.upsert_nodes([record])
        assert store.node_count() == 1


class TestGetNodeById:
    def test_get_node_by_id(self, tmp_path) -> None:
        store = GraphRAGStore(str(tmp_path / "chroma"))
        record = _make_node_record("lookup_node", "A node for lookup testing purposes")
        store.upsert_nodes([record])

        result = store.get_node_by_id("lookup_node")
        assert result is not None
        assert result["id"] == "lookup_node"

        missing = store.get_node_by_id("nonexistent_node_id")
        assert missing is None
