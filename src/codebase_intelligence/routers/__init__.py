"""Codebase Intelligence routers."""
from src.codebase_intelligence.routers.symbols import router as symbols_router
from src.codebase_intelligence.routers.dependencies import router as dependencies_router
from src.codebase_intelligence.routers.search import router as search_router
from src.codebase_intelligence.routers.artifacts import router as artifacts_router
from src.codebase_intelligence.routers.dead_code import router as dead_code_router
from src.codebase_intelligence.routers.health import router as health_router

__all__ = [
    "symbols_router",
    "dependencies_router",
    "search_router",
    "artifacts_router",
    "dead_code_router",
    "health_router",
]
