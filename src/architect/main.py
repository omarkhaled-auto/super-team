"""Architect service FastAPI application."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from src.shared.config import ArchitectConfig
from src.shared.constants import VERSION, ARCHITECT_SERVICE_NAME
from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_architect_db
from src.shared.errors import register_exception_handlers
from src.shared.logging import TraceIDMiddleware, setup_logging

config = ArchitectConfig()
logger = setup_logging(ARCHITECT_SERVICE_NAME, config.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan - initialize and cleanup resources."""
    app.state.start_time = time.time()

    app.state.pool = ConnectionPool(config.database_path)
    init_architect_db(app.state.pool)

    logger.info(
        "Service started: name=%s version=%s port=8000 db=%s",
        ARCHITECT_SERVICE_NAME, VERSION, config.database_path,
    )
    yield

    if app.state.pool:
        app.state.pool.close()
    logger.info("Service stopped: name=%s", ARCHITECT_SERVICE_NAME)


app = FastAPI(
    title="Architect Service",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(TraceIDMiddleware)
register_exception_handlers(app)

# Register all routers
from src.architect.routers.health import router as health_router
from src.architect.routers.decomposition import router as decomposition_router
from src.architect.routers.service_map import router as service_map_router
from src.architect.routers.domain_model import router as domain_model_router

app.include_router(health_router)
app.include_router(decomposition_router)
app.include_router(service_map_router)
app.include_router(domain_model_router)
