"""Implementation tracking for contracts."""
from __future__ import annotations

import json
import logging
from typing import Any

from src.shared.db.connection import ConnectionPool
from src.shared.utils import now_iso
from src.shared.errors import ContractNotFoundError
from src.shared.models.contracts import (
    ImplementationRecord,
    ImplementationStatus,
    MarkResponse,
    UnimplementedContract,
)

logger = logging.getLogger(__name__)


class ImplementationTracker:
    """Tracks which contracts have been implemented by which services."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def mark_implemented(
        self,
        contract_id: str,
        service_name: str,
        evidence_path: str,
    ) -> MarkResponse:
        """Mark a contract as implemented by a service.

        Uses ``INSERT ... ON CONFLICT(contract_id, service_name) DO UPDATE``
        so re-marking is idempotent.

        Raises :class:`ContractNotFoundError` if the contract does not exist.

        Returns a :class:`MarkResponse` with:
        - ``marked=True``
        - ``total_implementations``: count of implementations for this contract
        - ``all_implemented``: whether every service that references the
          contract has an implementation row
        """
        conn = self._pool.get()

        # Verify the contract exists.
        contract_row = conn.execute(
            "SELECT id, service_name FROM contracts WHERE id = ?",
            (contract_id,),
        ).fetchone()
        if contract_row is None:
            raise ContractNotFoundError(
                detail=f"Contract not found: {contract_id}"
            )

        now = now_iso()

        conn.execute(
            """
            INSERT INTO implementations
                (contract_id, service_name, evidence_path, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(contract_id, service_name) DO UPDATE SET
                evidence_path = excluded.evidence_path,
                status        = excluded.status,
                created_at    = excluded.created_at
            """,
            (contract_id, service_name, evidence_path, ImplementationStatus.PENDING.value, now),
        )
        conn.commit()

        # Count total implementations for this contract.
        total_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM implementations WHERE contract_id = ?",
            (contract_id,),
        ).fetchone()
        total = total_row["cnt"]

        # Determine if *all* services referencing contracts with this id
        # have implementations.  A simple heuristic: check if there are any
        # contracts for the same service_name+type combination that lack an
        # implementation row.
        pending_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM implementations
            WHERE contract_id = ? AND status = ?
            """,
            (contract_id, ImplementationStatus.PENDING.value),
        ).fetchone()

        verified_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM implementations
            WHERE contract_id = ? AND status = ?
            """,
            (contract_id, ImplementationStatus.VERIFIED.value),
        ).fetchone()

        # Consider all_implemented = True only when every implementation is
        # verified (no pending ones remain except the one we just created).
        all_implemented = total > 0 and pending_row["cnt"] == 0

        return MarkResponse(
            marked=True,
            total_implementations=total,
            all_implemented=all_implemented,
        )

    def verify_implementation(
        self,
        contract_id: str,
        service_name: str,
    ) -> ImplementationRecord:
        """Mark an implementation as verified.

        Sets ``status = 'verified'`` and ``verified_at`` to the current time.

        Raises :class:`ContractNotFoundError` if the implementation record
        does not exist.
        """
        conn = self._pool.get()
        now = now_iso()

        row = conn.execute(
            """
            SELECT * FROM implementations
            WHERE contract_id = ? AND service_name = ?
            """,
            (contract_id, service_name),
        ).fetchone()

        if row is None:
            raise ContractNotFoundError(
                detail=f"Implementation not found for contract={contract_id}, "
                       f"service={service_name}"
            )

        conn.execute(
            """
            UPDATE implementations
            SET status = ?, verified_at = ?
            WHERE contract_id = ? AND service_name = ?
            """,
            (ImplementationStatus.VERIFIED.value, now, contract_id, service_name),
        )
        conn.commit()

        # Re-fetch the updated row.
        updated = conn.execute(
            """
            SELECT * FROM implementations
            WHERE contract_id = ? AND service_name = ?
            """,
            (contract_id, service_name),
        ).fetchone()

        return ImplementationRecord(
            contract_id=updated["contract_id"],
            service_name=updated["service_name"],
            evidence_path=updated["evidence_path"],
            status=ImplementationStatus(updated["status"]),
            verified_at=updated["verified_at"],
            created_at=updated["created_at"],
        )

    def get_unimplemented(
        self,
        service_name: str | None = None,
    ) -> list[UnimplementedContract]:
        """Get contracts that have not been fully implemented.

        Uses a ``LEFT JOIN`` to find contracts that either:
        - have **no** matching row in ``implementations``, or
        - have an implementation still in ``'pending'`` status.

        Optionally filters by *service_name* (the contract's owning service).
        """
        conn = self._pool.get()

        base_sql = """
            SELECT c.id, c.type, c.version, c.service_name, c.status
            FROM contracts c
            LEFT JOIN implementations i
                ON c.id = i.contract_id
            WHERE (i.id IS NULL OR i.status = ?)
        """
        params: list[Any] = [ImplementationStatus.PENDING.value]

        if service_name is not None:
            base_sql += " AND c.service_name = ?"
            params.append(service_name)

        base_sql += " ORDER BY c.created_at DESC"

        rows = conn.execute(base_sql, params).fetchall()

        results: list[UnimplementedContract] = []
        for row in rows:
            try:
                results.append(
                    UnimplementedContract(
                        id=row["id"],
                        type=row["type"],
                        version=row["version"],
                        expected_service=row["service_name"],
                        status=row["status"],
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to convert unimplemented contract row: %s", exc)
        return results
