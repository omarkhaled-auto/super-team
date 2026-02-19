"""Performance test for indexing the sample codebase."""
import os
import time
import tempfile
import pytest

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_symbols_db
from src.codebase_intelligence.services.ast_parser import ASTParser
from src.codebase_intelligence.services.symbol_extractor import SymbolExtractor
from src.codebase_intelligence.services.import_resolver import ImportResolver
from src.codebase_intelligence.services.graph_builder import GraphBuilder
from src.codebase_intelligence.services.incremental_indexer import IncrementalIndexer
from src.codebase_intelligence.storage.symbol_db import SymbolDB
from src.codebase_intelligence.storage.graph_db import GraphDB


SAMPLE_CODEBASE_DIR = os.path.join("sample_data", "sample_codebase")
SAMPLE_FILES = [
    os.path.join(SAMPLE_CODEBASE_DIR, "auth_service", "auth.py"),
    os.path.join(SAMPLE_CODEBASE_DIR, "auth_service", "models.py"),
    os.path.join(SAMPLE_CODEBASE_DIR, "billing_service", "billing.ts"),
    os.path.join(SAMPLE_CODEBASE_DIR, "billing_service", "types.ts"),
]


@pytest.fixture
def indexer_setup():
    """Create all services needed for indexing."""
    tmpdir = tempfile.mkdtemp()
    pool = ConnectionPool(os.path.join(tmpdir, "perf_test.db"))
    init_symbols_db(pool)

    ast_parser = ASTParser()
    symbol_extractor = SymbolExtractor()
    import_resolver = ImportResolver()
    graph_builder = GraphBuilder()
    symbol_db = SymbolDB(pool)
    graph_db = GraphDB(pool)

    indexer = IncrementalIndexer(
        ast_parser, symbol_extractor, import_resolver,
        graph_builder, symbol_db, graph_db,
    )

    yield indexer, pool, symbol_db, graph_builder

    pool.close()


def test_index_sample_codebase_under_5_seconds(indexer_setup):
    """Index all sample codebase files in under 5 seconds."""
    indexer, pool, symbol_db, graph_builder = indexer_setup

    start = time.time()

    total_symbols = 0
    total_deps = 0
    all_indexed = True

    for file_path in SAMPLE_FILES:
        result = indexer.index_file(file_path, service_name="test-service")
        if not result["indexed"]:
            all_indexed = False
        total_symbols += result["symbols_found"]
        total_deps += result["dependencies_found"]

    elapsed = time.time() - start

    # Performance assertion
    assert elapsed < 5.0, f"Indexing took {elapsed:.2f}s, expected < 5.0s"

    # Correctness assertions
    assert all_indexed, "All files should be indexed successfully"
    assert total_symbols > 0, "Should have found some symbols"
    assert total_deps > 0, "Should have found some dependencies"
    assert graph_builder.graph.number_of_nodes() > 0, "Graph should have nodes"


def test_symbols_queryable_after_indexing(indexer_setup):
    """After indexing, symbols should be queryable from the database."""
    indexer, pool, symbol_db, graph_builder = indexer_setup

    for file_path in SAMPLE_FILES:
        indexer.index_file(file_path, service_name="test-service")

    # Query symbols from Python files
    py_symbols = symbol_db.query_by_file(
        os.path.join(SAMPLE_CODEBASE_DIR, "auth_service", "auth.py")
    )
    assert len(py_symbols) > 0, "Should find symbols in auth.py"

    # Query symbols from TypeScript files
    ts_symbols = symbol_db.query_by_file(
        os.path.join(SAMPLE_CODEBASE_DIR, "billing_service", "billing.ts")
    )
    assert len(ts_symbols) > 0, "Should find symbols in billing.ts"


def test_graph_built_after_indexing(indexer_setup):
    """After indexing, the dependency graph should be populated."""
    indexer, pool, symbol_db, graph_builder = indexer_setup

    for file_path in SAMPLE_FILES:
        indexer.index_file(file_path, service_name="test-service")

    graph = graph_builder.graph
    assert graph.number_of_nodes() > 0, "Graph should have nodes"
    assert graph.number_of_edges() > 0, "Graph should have edges"
