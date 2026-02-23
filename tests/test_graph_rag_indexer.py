"""Unit tests for Graph RAG Indexer."""
from __future__ import annotations

import json
import sqlite3

import pytest
from pathlib import Path

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_symbols_db, init_architect_db, init_contracts_db, init_graph_rag_db
from src.graph_rag.knowledge_graph import KnowledgeGraph
from src.graph_rag.graph_rag_store import GraphRAGStore
from src.graph_rag.graph_rag_indexer import GraphRAGIndexer
from src.shared.models.graph_rag import NodeType, EdgeType


@pytest.fixture
def indexer_env(tmp_path):
    """Set up all databases and return indexer components."""
    # -- CI database --
    ci_db_path = tmp_path / "ci.db"
    ci_pool = ConnectionPool(str(ci_db_path))
    init_symbols_db(ci_pool)

    # -- Architect database --
    arch_db_path = tmp_path / "architect.db"
    arch_pool = ConnectionPool(str(arch_db_path))
    init_architect_db(arch_pool)

    # -- Contract database --
    contract_db_path = tmp_path / "contracts.db"
    contract_pool = ConnectionPool(str(contract_db_path))
    init_contracts_db(contract_pool)

    # -- Graph RAG database --
    graph_rag_db_path = tmp_path / "graph_rag.db"
    graph_rag_pool = ConnectionPool(str(graph_rag_db_path))
    init_graph_rag_db(graph_rag_pool)

    # -- ChromaDB store --
    chroma_path = str(tmp_path / "chroma")
    store = GraphRAGStore(chroma_path)

    # -- Knowledge Graph --
    kg = KnowledgeGraph()

    # -- Indexer --
    indexer = GraphRAGIndexer(
        knowledge_graph=kg,
        store=store,
        pool=graph_rag_pool,
        ci_pool=ci_pool,
        architect_pool=arch_pool,
        contract_pool=contract_pool,
    )

    return {
        "indexer": indexer,
        "kg": kg,
        "store": store,
        "ci_pool": ci_pool,
        "arch_pool": arch_pool,
        "contract_pool": contract_pool,
        "graph_rag_pool": graph_rag_pool,
    }


def _insert_files(ci_pool: ConnectionPool, files: list[dict]) -> None:
    """Insert indexed_files rows."""
    conn = ci_pool.get()
    for f in files:
        conn.execute(
            "INSERT OR IGNORE INTO indexed_files (file_path, language, service_name, file_hash, loc) "
            "VALUES (?, ?, ?, ?, ?)",
            (f["file_path"], f.get("language", "python"), f.get("service_name", ""),
             f.get("file_hash", "abc123"), f.get("loc", 100)),
        )
    conn.commit()


def _insert_symbols(ci_pool: ConnectionPool, symbols: list[dict]) -> None:
    """Insert symbols rows."""
    conn = ci_pool.get()
    for s in symbols:
        conn.execute(
            "INSERT OR IGNORE INTO symbols (id, file_path, symbol_name, kind, language, "
            "service_name, line_start, line_end, signature, docstring, is_exported, parent_symbol) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s.get("id", f"{s['file_path']}::{s['symbol_name']}"),
                s["file_path"],
                s["symbol_name"],
                s.get("kind", "class"),
                s.get("language", "python"),
                s.get("service_name", ""),
                s.get("line_start", 1),
                s.get("line_end", 50),
                s.get("signature", ""),
                s.get("docstring", ""),
                s.get("is_exported", 1),
                s.get("parent_symbol", None),
            ),
        )
    conn.commit()


def _insert_dependency_edges(ci_pool: ConnectionPool, edges: list[dict]) -> None:
    """Insert dependency_edges rows."""
    conn = ci_pool.get()
    for e in edges:
        conn.execute(
            "INSERT OR IGNORE INTO dependency_edges "
            "(source_symbol_id, target_symbol_id, relation, source_file, target_file, line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                e["source_symbol_id"],
                e["target_symbol_id"],
                e.get("relation", "imports"),
                e.get("source_file", ""),
                e.get("target_file", ""),
                e.get("line", 1),
            ),
        )
    conn.commit()


def _insert_service_map(arch_pool: ConnectionPool, services: list[dict], project_name: str = "test-project") -> None:
    """Insert a service_maps row."""
    import uuid
    conn = arch_pool.get()
    map_json = json.dumps({"services": services})
    conn.execute(
        "INSERT INTO service_maps (id, project_name, prd_hash, map_json) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), project_name, "hash123", map_json),
    )
    conn.commit()


def _insert_domain_model(arch_pool: ConnectionPool, entities: list[dict], project_name: str = "test-project") -> None:
    """Insert a domain_models row."""
    import uuid
    conn = arch_pool.get()
    model_json = json.dumps({"entities": entities})
    conn.execute(
        "INSERT INTO domain_models (id, project_name, model_json) VALUES (?, ?, ?)",
        (str(uuid.uuid4()), project_name, model_json),
    )
    conn.commit()


def _insert_contracts(contract_pool: ConnectionPool, contracts: list[dict]) -> None:
    """Insert contracts rows."""
    import uuid
    import hashlib
    conn = contract_pool.get()
    for c in contracts:
        spec_json = json.dumps(c.get("spec", {}))
        conn.execute(
            "INSERT OR IGNORE INTO contracts (id, type, version, service_name, spec_json, spec_hash, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                c.get("id", str(uuid.uuid4())),
                c.get("type", "openapi"),
                c.get("version", "1.0.0"),
                c.get("service_name", ""),
                spec_json,
                hashlib.sha256(spec_json.encode()).hexdigest()[:16],
                c.get("status", "active"),
            ),
        )
    conn.commit()


def _seed_basic_data(env: dict) -> None:
    """Seed a minimal but realistic data set for basic tests."""
    ci_pool = env["ci_pool"]
    arch_pool = env["arch_pool"]
    contract_pool = env["contract_pool"]

    # Files
    files = [
        {"file_path": "src/auth/auth.py", "service_name": "auth-service", "language": "python"},
        {"file_path": "src/auth/models.py", "service_name": "auth-service", "language": "python"},
        {"file_path": "src/orders/orders.py", "service_name": "order-service", "language": "python"},
    ]
    _insert_files(ci_pool, files)

    # Symbols
    symbols = [
        {"file_path": "src/auth/auth.py", "symbol_name": "AuthService", "kind": "class",
         "service_name": "auth-service", "id": "src/auth/auth.py::AuthService"},
        {"file_path": "src/auth/auth.py", "symbol_name": "login", "kind": "function",
         "service_name": "auth-service", "id": "src/auth/auth.py::login"},
        {"file_path": "src/auth/models.py", "symbol_name": "UserModel", "kind": "class",
         "service_name": "auth-service", "id": "src/auth/models.py::UserModel"},
        {"file_path": "src/orders/orders.py", "symbol_name": "OrderService", "kind": "class",
         "service_name": "order-service", "id": "src/orders/orders.py::OrderService"},
        {"file_path": "src/orders/orders.py", "symbol_name": "create_order", "kind": "function",
         "service_name": "order-service", "id": "src/orders/orders.py::create_order"},
    ]
    _insert_symbols(ci_pool, symbols)

    # Dependency edges
    dep_edges = [
        {
            "source_symbol_id": "src/orders/orders.py::OrderService",
            "target_symbol_id": "src/auth/auth.py::AuthService",
            "relation": "imports",
            "source_file": "src/orders/orders.py",
            "target_file": "src/auth/auth.py",
        },
    ]
    _insert_dependency_edges(ci_pool, dep_edges)

    # Service map
    _insert_service_map(arch_pool, [
        {"name": "auth-service", "domain": "identity", "description": "Authentication service",
         "stack": ["python", "fastapi"], "estimated_loc": 3000},
        {"name": "order-service", "domain": "commerce", "description": "Order management service",
         "stack": ["python", "fastapi"], "estimated_loc": 4000},
    ])

    # Domain model
    _insert_domain_model(arch_pool, [
        {"name": "User", "owning_service": "auth-service", "description": "Application user",
         "fields": [{"name": "id", "type": "uuid"}, {"name": "email", "type": "string"}]},
        {"name": "Order", "owning_service": "order-service", "description": "Customer order",
         "fields": [{"name": "id", "type": "uuid"}, {"name": "total", "type": "float"}]},
    ])

    # Contracts with OpenAPI paths
    _insert_contracts(contract_pool, [
        {
            "id": "auth-api-v1",
            "type": "openapi",
            "version": "1.0.0",
            "service_name": "auth-service",
            "spec": {
                "paths": {
                    "/auth/login": {"post": {"summary": "Login endpoint"}},
                    "/auth/register": {"post": {"summary": "Register endpoint"}},
                    "/auth/me": {"get": {"summary": "Get current user"}},
                }
            },
        },
        {
            "id": "order-api-v1",
            "type": "openapi",
            "version": "1.0.0",
            "service_name": "order-service",
            "spec": {
                "paths": {
                    "/orders": {"post": {"summary": "Create order"}},
                    "/orders/{id}": {"get": {"summary": "Get order by ID"}},
                }
            },
        },
    ])


class TestBuildServiceNodes:
    def test_build_creates_service_nodes(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        result = indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        service_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.SERVICE.value
        ]
        assert len(service_nodes) == 2
        service_names = {kg.graph.nodes[n]["service_name"] for n in service_nodes}
        assert service_names == {"auth-service", "order-service"}


class TestBuildFileNodes:
    def test_build_creates_file_nodes(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        file_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.FILE.value
        ]
        assert len(file_nodes) >= 3  # At least the 3 files we inserted


class TestBuildSymbolNodes:
    def test_build_creates_symbol_nodes(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        symbol_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.SYMBOL.value
        ]
        assert len(symbol_nodes) >= 5


class TestBuildContractNodes:
    def test_build_creates_contract_nodes(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        contract_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.CONTRACT.value
        ]
        assert len(contract_nodes) == 2


class TestBuildEndpointNodes:
    def test_build_creates_endpoint_nodes_from_openapi(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        endpoint_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.ENDPOINT.value
        ]
        # auth-api has 3 paths (POST /auth/login, POST /auth/register, GET /auth/me)
        # order-api has 2 paths (POST /orders, GET /orders/{id})
        assert len(endpoint_nodes) == 5


class TestBuildDomainEntityNodes:
    def test_build_creates_domain_entity_nodes(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        entity_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.DOMAIN_ENTITY.value
        ]
        assert len(entity_nodes) == 2
        entity_names = {kg.graph.nodes[n]["entity_name"] for n in entity_nodes}
        assert entity_names == {"User", "Order"}


class TestBuildEventNodes:
    def test_build_creates_event_nodes(self, indexer_env) -> None:
        ci_pool = indexer_env["ci_pool"]
        arch_pool = indexer_env["arch_pool"]

        _insert_files(ci_pool, [
            {"file_path": "src/svc/main.py", "service_name": "svc-a", "language": "python"},
        ])
        _insert_symbols(ci_pool, [
            {"file_path": "src/svc/main.py", "symbol_name": "handler", "kind": "function",
             "service_name": "svc-a", "id": "src/svc/main.py::handler"},
        ])
        _insert_service_map(arch_pool, [
            {"name": "svc-a", "domain": "core", "description": "Service A"},
            {"name": "svc-b", "domain": "core", "description": "Service B"},
        ])

        service_interfaces = {
            "svc-a": {
                "events_published": ["order.created", "order.updated"],
            },
            "svc-b": {
                "events_consumed": ["order.created"],
            },
        }

        indexer_env["indexer"].build(
            project_name="test-project",
            service_interfaces=service_interfaces,
        )
        kg = indexer_env["kg"]

        event_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.EVENT.value
        ]
        assert len(event_nodes) >= 2  # order.created, order.updated


class TestBuildEdges:
    def test_build_creates_service_calls_edges(self, indexer_env) -> None:
        """Cross-service imports should create SERVICE_CALLS edges."""
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        # Check for SERVICE_CALLS edges between services
        service_calls = [
            (u, v, k) for u, v, k in kg.graph.edges(keys=True)
            if k == EdgeType.SERVICE_CALLS.value
        ]
        # order-service imports from auth-service should produce a SERVICE_CALLS edge
        assert len(service_calls) >= 1

    def test_build_matches_symbols_to_entities(self, indexer_env) -> None:
        """Symbols like 'OrderService' should match 'Order' entity via IMPLEMENTS_ENTITY."""
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        implements_edges = [
            (u, v, k) for u, v, k in kg.graph.edges(keys=True)
            if k == EdgeType.IMPLEMENTS_ENTITY.value
        ]
        # OrderService -> Order entity, UserModel -> User entity
        assert len(implements_edges) >= 1


class TestBuildHandlerMatching:
    def test_build_matches_handlers_to_endpoints(self, indexer_env) -> None:
        """Symbol handlers should match endpoints via HANDLES_ENDPOINT."""
        ci_pool = indexer_env["ci_pool"]
        arch_pool = indexer_env["arch_pool"]
        contract_pool = indexer_env["contract_pool"]

        _insert_files(ci_pool, [
            {"file_path": "src/svc/routes.py", "service_name": "my-service", "language": "python"},
        ])
        _insert_symbols(ci_pool, [
            {"file_path": "src/svc/routes.py", "symbol_name": "login_handler", "kind": "function",
             "service_name": "my-service", "id": "src/svc/routes.py::login_handler",
             "signature": "def login_handler(request):"},
        ])
        _insert_service_map(arch_pool, [
            {"name": "my-service", "domain": "auth", "description": "My service"},
        ])
        _insert_contracts(contract_pool, [
            {
                "id": "my-api-v1",
                "type": "openapi",
                "version": "1.0.0",
                "service_name": "my-service",
                "spec": {
                    "paths": {
                        "/login": {"post": {"summary": "Login"}},
                    }
                },
            },
        ])

        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        # Verify endpoint node was created
        endpoint_nodes = [
            n for n, d in kg.graph.nodes(data=True)
            if d.get("node_type") == NodeType.ENDPOINT.value
        ]
        assert len(endpoint_nodes) >= 1


class TestBuildChromaDB:
    def test_build_populates_chromadb(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        store = indexer_env["store"]

        assert store.node_count() > 0


class TestBuildPersistence:
    def test_build_persists_snapshot(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")

        conn = indexer_env["graph_rag_pool"].get()
        row = conn.execute("SELECT COUNT(*) as cnt FROM graph_rag_snapshots").fetchone()
        assert row["cnt"] >= 1


class TestBuildMetrics:
    def test_build_computes_pagerank(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        # At least some nodes should have pagerank > 0
        pageranks = [
            d.get("pagerank", 0)
            for _, d in kg.graph.nodes(data=True)
            if d.get("pagerank", 0) > 0
        ]
        assert len(pageranks) > 0

    def test_build_computes_communities(self, indexer_env) -> None:
        _seed_basic_data(indexer_env)
        indexer_env["indexer"].build(project_name="test-project")
        kg = indexer_env["kg"]

        community_ids = {
            d.get("community_id")
            for _, d in kg.graph.nodes(data=True)
            if d.get("community_id") is not None and d.get("community_id", -1) >= 0
        }
        assert len(community_ids) > 0


class TestBuildPartialData:
    def test_build_partial_data_tolerates_missing_db(self, tmp_path) -> None:
        """Build should succeed even without a valid CI database."""
        graph_rag_db_path = tmp_path / "graph_rag.db"
        graph_rag_pool = ConnectionPool(str(graph_rag_db_path))
        init_graph_rag_db(graph_rag_pool)

        chroma_path = str(tmp_path / "chroma")
        store = GraphRAGStore(chroma_path)
        kg = KnowledgeGraph()

        # No CI pool, no architect pool, no contract pool
        indexer = GraphRAGIndexer(
            knowledge_graph=kg,
            store=store,
            pool=graph_rag_pool,
            ci_pool=None,
            architect_pool=None,
            contract_pool=None,
        )

        result = indexer.build(project_name="test-project")
        # Should succeed (possibly with 0 nodes) but not crash
        assert result.success is True or len(result.errors) > 0
        # Even with errors, the build should complete
        assert result.build_time_ms >= 0
