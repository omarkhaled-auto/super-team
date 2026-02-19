"""Schema registry for managing shared schemas between services."""
from __future__ import annotations

import json
import logging
from typing import Any

from src.shared.db.connection import ConnectionPool
from src.shared.errors import NotFoundError
from src.shared.models.contracts import SharedSchema
from src.shared.utils import now_iso

logger = logging.getLogger(__name__)


class SchemaRegistry:
    """Manages shared schemas in the ``shared_schemas`` and ``schema_consumers`` tables."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def register_schema(
        self,
        name: str,
        schema: dict[str, Any],
        owning_service: str,
    ) -> SharedSchema:
        """Register or update a shared schema.

        Uses ``INSERT ... ON CONFLICT(name) DO UPDATE`` so that re-registering
        an existing name simply overwrites the schema JSON, owning service, and
        updated_at timestamp.
        """
        conn = self._pool.get()
        now = now_iso()
        schema_json = json.dumps(schema, sort_keys=True)

        conn.execute(
            """
            INSERT INTO shared_schemas (name, schema_json, owning_service, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                schema_json    = excluded.schema_json,
                owning_service = excluded.owning_service,
                updated_at     = excluded.updated_at
            """,
            (name, schema_json, owning_service, now, now),
        )
        conn.commit()

        return self.get_schema(name)

    def get_schema(self, name: str) -> SharedSchema:
        """Get a schema by name.

        Raises :class:`NotFoundError` if the schema does not exist.
        """
        conn = self._pool.get()
        row = conn.execute(
            "SELECT * FROM shared_schemas WHERE name = ?",
            (name,),
        ).fetchone()

        if row is None:
            raise NotFoundError(detail=f"Schema not found: {name}")

        consumers = self.get_consumers(name)

        return SharedSchema(
            name=row["name"],
            schema_def=json.loads(row["schema_json"]),
            owning_service=row["owning_service"],
            consuming_services=consumers,
        )

    def list_schemas(self, owning_service: str | None = None) -> list[SharedSchema]:
        """List all schemas, optionally filtered by *owning_service*."""
        conn = self._pool.get()

        if owning_service is not None:
            rows = conn.execute(
                "SELECT * FROM shared_schemas WHERE owning_service = ? ORDER BY name",
                (owning_service,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM shared_schemas ORDER BY name",
            ).fetchall()

        results: list[SharedSchema] = []
        for row in rows:
            try:
                consumers = self.get_consumers(row["name"])
                results.append(
                    SharedSchema(
                        name=row["name"],
                        schema_def=json.loads(row["schema_json"]),
                        owning_service=row["owning_service"],
                        consuming_services=consumers,
                    )
                )
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                logger.warning("Failed to convert schema row: %s", exc)
        return results

    def get_consumers(self, schema_name: str) -> list[str]:
        """Get the list of service names that consume the given schema."""
        conn = self._pool.get()
        rows = conn.execute(
            "SELECT service_name FROM schema_consumers WHERE schema_name = ? ORDER BY service_name",
            (schema_name,),
        ).fetchall()
        return [row["service_name"] for row in rows]

    def add_consumer(self, schema_name: str, service_name: str) -> None:
        """Add a consumer to a schema.

        Uses ``INSERT OR IGNORE`` for idempotency -- adding the same
        consumer twice is a no-op.  The schema must already exist.
        """
        conn = self._pool.get()

        # Verify the schema exists first.
        exists = conn.execute(
            "SELECT 1 FROM shared_schemas WHERE name = ?",
            (schema_name,),
        ).fetchone()

        if exists is None:
            raise NotFoundError(detail=f"Schema not found: {schema_name}")

        conn.execute(
            "INSERT OR IGNORE INTO schema_consumers (schema_name, service_name) VALUES (?, ?)",
            (schema_name, service_name),
        )
        conn.commit()
