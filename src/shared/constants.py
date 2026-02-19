"""Shared constants used across all services."""
from __future__ import annotations

# Application version
VERSION: str = "1.0.0"

# Port numbers
ARCHITECT_PORT: int = 8001
CONTRACT_ENGINE_PORT: int = 8002
CODEBASE_INTEL_PORT: int = 8003
INTERNAL_PORT: int = 8000

# Supported languages
SUPPORTED_LANGUAGES: list[str] = ["python", "typescript", "csharp", "go"]

# Supported contract types
SUPPORTED_CONTRACT_TYPES: list[str] = ["openapi", "asyncapi", "json_schema"]

# Database settings
DB_BUSY_TIMEOUT_MS: int = 30000

# Service names
ARCHITECT_SERVICE_NAME: str = "architect"
CONTRACT_ENGINE_SERVICE_NAME: str = "contract-engine"
CODEBASE_INTEL_SERVICE_NAME: str = "codebase-intelligence"
