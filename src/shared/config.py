"""Shared configuration management using pydantic-settings."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class SharedConfig(BaseSettings):
    """Base configuration shared across all services."""
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")
    database_path: str = Field(
        default="./data/service.db", validation_alias="DATABASE_PATH"
    )

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }


class ArchitectConfig(SharedConfig):
    """Configuration for the Architect service."""
    contract_engine_url: str = Field(
        default="http://contract-engine:8000",
        validation_alias="CONTRACT_ENGINE_URL",
    )
    codebase_intel_url: str = Field(
        default="http://codebase-intel:8000",
        validation_alias="CODEBASE_INTEL_URL",
    )


class ContractEngineConfig(SharedConfig):
    """Configuration for the Contract Engine service."""
    pass


class CodebaseIntelConfig(SharedConfig):
    """Configuration for the Codebase Intelligence service."""
    chroma_path: str = Field(
        default="./data/chroma", validation_alias="CHROMA_PATH"
    )
    graph_path: str = Field(
        default="./data/graph.json", validation_alias="GRAPH_PATH"
    )
    contract_engine_url: str = Field(
        default="http://contract-engine:8000",
        validation_alias="CONTRACT_ENGINE_URL",
    )
