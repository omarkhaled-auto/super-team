"""Contract Engine service FastAPI application."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from src.shared.config import ContractEngineConfig
from src.shared.constants import VERSION, CONTRACT_ENGINE_SERVICE_NAME
from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db
from src.shared.errors import register_exception_handlers
from src.shared.logging import TraceIDMiddleware, setup_logging

config = ContractEngineConfig()
logger = setup_logging(CONTRACT_ENGINE_SERVICE_NAME, config.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan - initialize and cleanup resources."""
    app.state.start_time = time.time()

    app.state.pool = ConnectionPool(config.database_path)
    init_contracts_db(app.state.pool)

    logger.info(
        "Service started: name=%s version=%s port=8000 db=%s",
        CONTRACT_ENGINE_SERVICE_NAME, VERSION, config.database_path,
    )
    yield

    if app.state.pool:
        app.state.pool.close()
    logger.info("Service stopped: name=%s", CONTRACT_ENGINE_SERVICE_NAME)


app = FastAPI(
    title="Contract Engine",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(TraceIDMiddleware)
register_exception_handlers(app)

# Register all routers
from src.contract_engine.routers.health import router as health_router
from src.contract_engine.routers.contracts import router as contracts_router
from src.contract_engine.routers.validation import router as validation_router
from src.contract_engine.routers.breaking_changes import router as breaking_changes_router
from src.contract_engine.routers.implementations import router as implementations_router
from src.contract_engine.routers.tests import router as tests_router

app.include_router(health_router)
app.include_router(contracts_router)
app.include_router(validation_router)
app.include_router(breaking_changes_router)
app.include_router(implementations_router)
app.include_router(tests_router)
