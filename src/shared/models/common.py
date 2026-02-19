"""Common Pydantic v2 data models shared across services."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class BuildCycle(BaseModel):
    """Record of a build cycle."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_name: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    status: str = Field(
        default="running",
        pattern=r"^(running|completed|failed|paused)$"
    )
    services_planned: int = 0
    services_completed: int = 0
    total_cost_usd: float = 0.0

    model_config = {"from_attributes": True}


class ArtifactRegistration(BaseModel):
    """Registration of a code artifact for indexing."""
    file_path: str
    service_name: str
    build_cycle_id: str | None = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"from_attributes": True}


class HealthStatus(BaseModel):
    """Health status of a service."""
    status: str = Field(
        default="healthy",
        pattern=r"^(healthy|degraded|unhealthy)$"
    )
    service_name: str
    version: str
    database: str = Field(
        default="connected",
        pattern=r"^(connected|disconnected)$"
    )
    uptime_seconds: float
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}
