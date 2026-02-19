"""Contract version management with build cycle immutability."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.shared.db.connection import ConnectionPool
from src.shared.errors import ImmutabilityViolationError
from src.shared.models.contracts import ContractVersion, BreakingChange

logger = logging.getLogger(__name__)


class VersionManager:
    """Manages contract versioning and enforces immutability within build cycles."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def check_immutability(self, contract_id: str, build_cycle_id: str | None) -> None:
        """Check if a contract can be modified within a build cycle.

        If build_cycle_id is provided and a version already exists for this
        contract+build_cycle, raise ImmutabilityViolationError.
        If build_cycle_id is None, always allow (no immutability constraint).
        """
        if build_cycle_id is None:
            return

        conn = self._pool.get()
        row = conn.execute(
            "SELECT id FROM contract_versions "
            "WHERE contract_id = ? AND build_cycle_id = ?",
            (contract_id, build_cycle_id),
        ).fetchone()

        if row is not None:
            raise ImmutabilityViolationError(
                detail=(
                    f"Contract '{contract_id}' already has a version recorded in "
                    f"build cycle '{build_cycle_id}'. Contracts are immutable within "
                    f"a build cycle."
                ),
            )

    def create_version(
        self,
        contract_id: str,
        version: str,
        spec_hash: str,
        build_cycle_id: str | None = None,
        is_breaking: bool = False,
        breaking_changes: list[BreakingChange] | None = None,
        change_summary: str | None = None,
    ) -> ContractVersion:
        """Create a new version record for a contract.

        1. Check immutability
        2. Insert into contract_versions
        3. If breaking_changes provided, insert each into breaking_changes table
        4. Return ContractVersion object
        """
        self.check_immutability(contract_id, build_cycle_id)

        conn = self._pool.get()

        cursor = conn.execute(
            "INSERT INTO contract_versions "
            "(contract_id, version, spec_hash, build_cycle_id, is_breaking, change_summary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                contract_id,
                version,
                spec_hash,
                build_cycle_id,
                1 if is_breaking else 0,
                change_summary,
            ),
        )
        version_id = cursor.lastrowid

        if breaking_changes:
            for change in breaking_changes:
                try:
                    conn.execute(
                        "INSERT INTO breaking_changes "
                        "(contract_version_id, change_type, json_path, old_value, "
                        "new_value, severity, affected_consumers, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            version_id,
                            change.change_type,
                            change.path,
                            change.old_value,
                            change.new_value,
                            change.severity,
                            json.dumps(change.affected_consumers),
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                except (TypeError, ValueError) as exc:
                    logger.warning("Failed to insert breaking change: %s", exc)

        conn.commit()

        # Fetch the created row to get the server-generated created_at
        row = conn.execute(
            "SELECT * FROM contract_versions WHERE id = ?",
            (version_id,),
        ).fetchone()

        return ContractVersion(
            contract_id=row["contract_id"],
            version=row["version"],
            spec_hash=row["spec_hash"],
            build_cycle_id=row["build_cycle_id"],
            created_at=row["created_at"],
            is_breaking=bool(row["is_breaking"]),
            breaking_changes=breaking_changes or [],
        )

    def get_version_history(self, contract_id: str) -> list[ContractVersion]:
        """Get all versions for a contract, ordered by created_at DESC.

        For each version, load associated breaking_changes from the
        breaking_changes table.
        """
        conn = self._pool.get()

        version_rows = conn.execute(
            "SELECT * FROM contract_versions "
            "WHERE contract_id = ? "
            "ORDER BY id DESC",
            (contract_id,),
        ).fetchall()

        versions: list[ContractVersion] = []
        for vrow in version_rows:
            try:
                change_rows = conn.execute(
                    "SELECT * FROM breaking_changes "
                    "WHERE contract_version_id = ?",
                    (vrow["id"],),
                ).fetchall()

                changes: list[BreakingChange] = []
                for crow in change_rows:
                    try:
                        changes.append(
                            BreakingChange(
                                change_type=crow["change_type"],
                                path=crow["json_path"],
                                old_value=crow["old_value"],
                                new_value=crow["new_value"],
                                severity=crow["severity"],
                                affected_consumers=json.loads(crow["affected_consumers"]),
                            )
                        )
                    except (KeyError, TypeError, json.JSONDecodeError) as exc:
                        logger.warning("Failed to parse breaking change row: %s", exc)

                versions.append(
                    ContractVersion(
                        contract_id=vrow["contract_id"],
                        version=vrow["version"],
                        spec_hash=vrow["spec_hash"],
                        build_cycle_id=vrow["build_cycle_id"],
                        created_at=vrow["created_at"],
                        is_breaking=bool(vrow["is_breaking"]),
                        breaking_changes=changes,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to convert version row: %s", exc)

        return versions
