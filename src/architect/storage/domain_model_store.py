"""Domain model storage layer for the Architect service."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from src.shared.db.connection import ConnectionPool
from src.shared.models.architect import DomainModel


class DomainModelStore:
    """Persists and retrieves DomainModel from the database.

    Uses the domain_models table with columns:
    - id TEXT PRIMARY KEY
    - project_name TEXT NOT NULL
    - model_json TEXT NOT NULL
    - generated_at TEXT NOT NULL DEFAULT (datetime('now'))
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, domain_model: DomainModel, project_name: str) -> str:
        """Save a domain model to the database.

        Args:
            domain_model: The DomainModel to persist.
            project_name: The project name to associate with.

        Returns:
            The generated ID for the stored domain model.
        """
        model_id = str(uuid.uuid4())
        conn = self._pool.get()
        conn.execute(
            """INSERT INTO domain_models (id, project_name, model_json, generated_at)
               VALUES (?, ?, ?, ?)""",
            (
                model_id,
                project_name,
                domain_model.model_dump_json(),
                domain_model.generated_at.isoformat(),
            ),
        )
        conn.commit()
        return model_id

    def get_latest(self, project_name: str | None = None) -> DomainModel | None:
        """Get the most recent domain model, optionally filtered by project.

        Args:
            project_name: Optional project name filter.

        Returns:
            The latest DomainModel or None if not found.
        """
        conn = self._pool.get()
        if project_name:
            row = conn.execute(
                "SELECT model_json FROM domain_models WHERE project_name = ? ORDER BY generated_at DESC LIMIT 1",
                (project_name,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT model_json FROM domain_models ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()

        if row is None:
            return None
        return DomainModel.model_validate_json(row["model_json"])
