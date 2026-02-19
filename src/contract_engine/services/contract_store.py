"""Contract store -- CRUD operations on the contracts table."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid

logger = logging.getLogger(__name__)

from src.shared.db.connection import ConnectionPool
from src.shared.utils import now_iso
from src.shared.errors import ContractNotFoundError, ValidationError
from src.shared.models.contracts import (
    ContractCreate,
    ContractEntry,
    ContractListResponse,
    ContractStatus,
    ContractType,
)

_MAX_PAGE_SIZE = 100


class ContractStore:
    """Manages CRUD operations against the ``contracts`` SQLite table."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_hash(spec: dict) -> str:
        return hashlib.sha256(
            json.dumps(spec, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _row_to_entry(row) -> ContractEntry:
        """Convert a ``sqlite3.Row`` into a :class:`ContractEntry`."""
        return ContractEntry(
            id=row["id"],
            type=ContractType(row["type"]),
            version=row["version"],
            service_name=row["service_name"],
            spec=json.loads(row["spec_json"]),
            spec_hash=row["spec_hash"],
            status=ContractStatus(row["status"]),
            build_cycle_id=row["build_cycle_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def upsert(self, create: ContractCreate) -> ContractEntry:
        """Insert or update a contract.

        Uses ``INSERT ... ON CONFLICT(service_name, type, version) DO UPDATE``
        to perform an upsert.  Returns the resulting :class:`ContractEntry`
        with generated *id*, *spec_hash* and timestamps.
        """
        conn = self._pool.get()

        contract_id = str(uuid.uuid4())
        spec_json = json.dumps(create.spec, sort_keys=True)
        spec_hash = self._compute_hash(create.spec)
        now = now_iso()

        sql = """
            INSERT INTO contracts
                (id, type, version, service_name, spec_json, spec_hash,
                 status, build_cycle_id, created_at, updated_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service_name, type, version) DO UPDATE SET
                spec_json      = excluded.spec_json,
                spec_hash      = excluded.spec_hash,
                status         = excluded.status,
                build_cycle_id = excluded.build_cycle_id,
                updated_at     = excluded.updated_at
        """
        params = (
            contract_id,
            create.type.value,
            create.version,
            create.service_name,
            spec_json,
            spec_hash,
            ContractStatus.DRAFT.value,
            create.build_cycle_id,
            now,
            now,
        )

        cursor = conn.execute(sql, params)
        conn.commit()

        # Retrieve the row that was inserted or updated so that we return the
        # authoritative values (the id may differ when an update occurred).
        row = conn.execute(
            "SELECT * FROM contracts WHERE service_name = ? AND type = ? AND version = ?",
            (create.service_name, create.type.value, create.version),
        ).fetchone()

        return self._row_to_entry(row)

    def get(self, contract_id: str) -> ContractEntry:
        """Return a single contract by its *id*.

        Raises :class:`ContractNotFoundError` when no matching row exists.
        """
        conn = self._pool.get()
        row = conn.execute(
            "SELECT * FROM contracts WHERE id = ?", (contract_id,)
        ).fetchone()

        if row is None:
            raise ContractNotFoundError(
                detail=f"Contract not found: {contract_id}"
            )

        return self._row_to_entry(row)

    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        service_name: str | None = None,
        contract_type: str | None = None,
        status: str | None = None,
    ) -> ContractListResponse:
        """Return a paginated, optionally filtered list of contracts."""
        conn = self._pool.get()

        # Clamp page_size
        page_size = max(1, min(page_size, _MAX_PAGE_SIZE))
        page = max(1, page)

        # Build dynamic WHERE clause
        conditions: list[str] = []
        params: list[str] = []

        if service_name is not None:
            conditions.append("service_name = ?")
            params.append(service_name)
        if contract_type is not None:
            conditions.append("type = ?")
            params.append(contract_type)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Total count
        count_sql = f"SELECT COUNT(*) AS cnt FROM contracts {where_clause}"
        total: int = conn.execute(count_sql, params).fetchone()["cnt"]

        # Paginated results
        offset = (page - 1) * page_size
        select_sql = (
            f"SELECT * FROM contracts {where_clause} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        rows = conn.execute(
            select_sql, [*params, page_size, offset]
        ).fetchall()

        items = []
        for r in rows:
            try:
                items.append(self._row_to_entry(r))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Failed to convert contract row: %s", exc)

        return ContractListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def delete(self, contract_id: str) -> None:
        """Delete a contract by its *id*.

        Raises :class:`ContractNotFoundError` when no matching row exists.
        """
        conn = self._pool.get()
        cursor = conn.execute(
            "DELETE FROM contracts WHERE id = ?", (contract_id,)
        )
        conn.commit()

        if cursor.rowcount == 0:
            raise ContractNotFoundError(
                detail=f"Contract not found: {contract_id}"
            )

    def has_changed(
        self,
        service_name: str,
        contract_type: str,
        version: str,
        spec: dict,
    ) -> bool:
        """Check whether *spec* differs from what is currently stored.

        Returns ``True`` when the computed hash does not match the stored
        ``spec_hash`` **or** when no matching contract exists yet.
        """
        conn = self._pool.get()
        row = conn.execute(
            "SELECT spec_hash FROM contracts "
            "WHERE service_name = ? AND type = ? AND version = ?",
            (service_name, contract_type, version),
        ).fetchone()

        if row is None:
            return True

        return row["spec_hash"] != self._compute_hash(spec)
