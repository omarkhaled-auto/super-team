"""Service map storage layer for the Architect service."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from src.shared.db.connection import ConnectionPool
from src.shared.models.architect import ServiceMap


class ServiceMapStore:
    """Persists and retrieves ServiceMap from the database.

    Uses the service_maps table with columns:
    - id TEXT PRIMARY KEY
    - project_name TEXT NOT NULL
    - prd_hash TEXT NOT NULL
    - map_json TEXT NOT NULL
    - build_cycle_id TEXT
    - generated_at TEXT NOT NULL DEFAULT (datetime('now'))
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, service_map: ServiceMap) -> str:
        """Save a service map to the database.

        Args:
            service_map: The ServiceMap to persist.

        Returns:
            The generated ID for the stored service map.
        """
        map_id = str(uuid.uuid4())
        conn = self._pool.get()
        conn.execute(
            """INSERT INTO service_maps (id, project_name, prd_hash, map_json, build_cycle_id, generated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                map_id,
                service_map.project_name,
                service_map.prd_hash,
                service_map.model_dump_json(),
                service_map.build_cycle_id,
                service_map.generated_at.isoformat(),
            ),
        )
        conn.commit()
        return map_id

    def get_latest(self, project_name: str | None = None) -> ServiceMap | None:
        """Get the most recent service map, optionally filtered by project.

        Args:
            project_name: Optional project name filter.

        Returns:
            The latest ServiceMap or None if not found.
        """
        conn = self._pool.get()
        if project_name:
            row = conn.execute(
                "SELECT map_json FROM service_maps WHERE project_name = ? ORDER BY generated_at DESC LIMIT 1",
                (project_name,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT map_json FROM service_maps ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()

        if row is None:
            return None
        return ServiceMap.model_validate_json(row["map_json"])

    def get_by_prd_hash(self, prd_hash: str) -> ServiceMap | None:
        """Get a service map by its PRD content hash.

        Args:
            prd_hash: The SHA-256 hash of the PRD content.

        Returns:
            The ServiceMap or None if not found.
        """
        conn = self._pool.get()
        row = conn.execute(
            "SELECT map_json FROM service_maps WHERE prd_hash = ? ORDER BY generated_at DESC LIMIT 1",
            (prd_hash,),
        ).fetchone()

        if row is None:
            return None
        return ServiceMap.model_validate_json(row["map_json"])
