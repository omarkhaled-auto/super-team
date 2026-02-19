"""Codebase Intelligence service FastAPI application."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from src.shared.config import CodebaseIntelConfig
from src.shared.constants import VERSION, CODEBASE_INTEL_SERVICE_NAME
from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_symbols_db
from src.shared.errors import register_exception_handlers
from src.shared.logging import TraceIDMiddleware, setup_logging

# Services
from src.codebase_intelligence.services.ast_parser import ASTParser
from src.codebase_intelligence.services.symbol_extractor import SymbolExtractor
from src.codebase_intelligence.services.import_resolver import ImportResolver
from src.codebase_intelligence.services.graph_builder import GraphBuilder
from src.codebase_intelligence.services.graph_analyzer import GraphAnalyzer
from src.codebase_intelligence.services.dead_code_detector import DeadCodeDetector
from src.codebase_intelligence.services.semantic_indexer import SemanticIndexer
from src.codebase_intelligence.services.semantic_searcher import SemanticSearcher
from src.codebase_intelligence.services.incremental_indexer import IncrementalIndexer
from src.codebase_intelligence.services.service_interface_extractor import ServiceInterfaceExtractor

# Storage
from src.codebase_intelligence.storage.symbol_db import SymbolDB
from src.codebase_intelligence.storage.graph_db import GraphDB
from src.codebase_intelligence.storage.chroma_store import ChromaStore

# Routers
from src.codebase_intelligence.routers.symbols import router as symbols_router
from src.codebase_intelligence.routers.dependencies import router as dependencies_router
from src.codebase_intelligence.routers.search import router as search_router
from src.codebase_intelligence.routers.artifacts import router as artifacts_router
from src.codebase_intelligence.routers.dead_code import router as dead_code_router
from src.codebase_intelligence.routers.health import router as health_router

config = CodebaseIntelConfig()
logger = setup_logging(CODEBASE_INTEL_SERVICE_NAME, config.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — initialize and clean up resources."""
    start_time = time.time()
    app.state.start_time = start_time

    # Database
    pool = ConnectionPool(config.database_path)
    init_symbols_db(pool)
    app.state.pool = pool

    # Storage layer
    symbol_db = SymbolDB(pool)
    graph_db = GraphDB(pool)
    chroma_store = ChromaStore(config.chroma_path)
    app.state.symbol_db = symbol_db
    app.state.graph_db = graph_db
    app.state.chroma_store = chroma_store

    # Load existing graph or create empty
    existing_graph = graph_db.load_snapshot()
    graph_builder = GraphBuilder(graph=existing_graph)
    graph_analyzer = GraphAnalyzer(graph_builder.graph)
    app.state.graph_builder = graph_builder
    app.state.graph_analyzer = graph_analyzer

    # Core services
    ast_parser = ASTParser()
    symbol_extractor = SymbolExtractor()
    import_resolver = ImportResolver()
    dead_code_detector = DeadCodeDetector(graph_builder.graph)
    app.state.ast_parser = ast_parser
    app.state.symbol_extractor = symbol_extractor
    app.state.import_resolver = import_resolver
    app.state.dead_code_detector = dead_code_detector

    # Semantic services
    semantic_indexer = SemanticIndexer(chroma_store, symbol_db)
    semantic_searcher = SemanticSearcher(chroma_store)
    app.state.semantic_indexer = semantic_indexer
    app.state.semantic_searcher = semantic_searcher

    # Service interface extractor
    service_interface_extractor = ServiceInterfaceExtractor(ast_parser, symbol_extractor)
    app.state.service_interface_extractor = service_interface_extractor

    # Incremental indexer (full pipeline)
    incremental_indexer = IncrementalIndexer(
        ast_parser=ast_parser,
        symbol_extractor=symbol_extractor,
        import_resolver=import_resolver,
        graph_builder=graph_builder,
        symbol_db=symbol_db,
        graph_db=graph_db,
        semantic_indexer=semantic_indexer,
    )
    app.state.incremental_indexer = incremental_indexer

    logger.info(
        "Service started: name=%s version=%s port=8000 db=%s chroma=%s",
        CODEBASE_INTEL_SERVICE_NAME, VERSION, config.database_path, config.chroma_path,
    )
    yield

    pool.close()
    logger.info("Service stopped: name=%s", CODEBASE_INTEL_SERVICE_NAME)


app = FastAPI(
    title="Codebase Intelligence",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(TraceIDMiddleware)
register_exception_handlers(app)

# Register routers
# NOTE: health_router is included FIRST so it can override the skeleton /api/health
app.include_router(health_router)
app.include_router(symbols_router)
app.include_router(dependencies_router)
app.include_router(search_router)
app.include_router(artifacts_router)
app.include_router(dead_code_router)
