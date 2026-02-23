"""Run tracker -- records pipeline runs, violations, and fixes to SQLite."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from src.build3_shared.models import ScanViolation
from src.persistence.schema import init_persistence_db
from src.shared.db.connection import ConnectionPool

logger = logging.getLogger(__name__)


class RunTracker:
    """Tracks pipeline runs, violations, and fix patterns in SQLite.

    Every public method is independently try/excepted so that a
    ``RunTracker`` failure **never** raises into the pipeline.

    Args:
        db_path: Path to the persistence SQLite database.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._pool = ConnectionPool(db_path)
        init_persistence_db(self._pool)

    # ------------------------------------------------------------------
    # Pipeline run tracking
    # ------------------------------------------------------------------

    def record_run(
        self,
        pipeline_id: str,
        prd_hash: str,
        verdict: str,
        service_count: int,
        cost: float,
    ) -> None:
        """Record a completed pipeline run."""
        try:
            conn = self._pool.get()
            conn.execute(
                """INSERT OR REPLACE INTO pipeline_runs
                   (run_id, prd_hash, overall_verdict, service_count, total_cost)
                   VALUES (?, ?, ?, ?, ?)""",
                (pipeline_id, prd_hash, verdict, service_count, cost),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("RunTracker.record_run failed (non-blocking): %s", exc)

    # ------------------------------------------------------------------
    # Violation tracking
    # ------------------------------------------------------------------

    def record_violation(
        self,
        run_id: str,
        violation: ScanViolation,
        service_name: str,
        tech_stack: str,
    ) -> str:
        """Record a violation observed during a pipeline run.

        Returns:
            The generated ``violation_id``.
        """
        violation_id = str(uuid.uuid4())
        try:
            conn = self._pool.get()
            conn.execute(
                """INSERT OR REPLACE INTO violations_observed
                   (violation_id, run_id, scan_code, file_path, line,
                    message, severity, service_name, service_tech_stack)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    violation_id,
                    run_id,
                    violation.code,
                    violation.file_path,
                    violation.line,
                    violation.message,
                    violation.severity,
                    service_name,
                    tech_stack,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("RunTracker.record_violation failed (non-blocking): %s", exc)
        return violation_id

    # ------------------------------------------------------------------
    # Fix tracking
    # ------------------------------------------------------------------

    def record_fix(
        self,
        violation_id: str,
        code_before: str,
        code_after: str,
        diff: str,
        description: str,
    ) -> None:
        """Record a fix pattern applied to a violation."""
        try:
            fix_id = str(uuid.uuid4())
            conn = self._pool.get()
            conn.execute(
                """INSERT OR REPLACE INTO fix_patterns
                   (fix_id, violation_id, code_before, code_after, diff, fix_description)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (fix_id, violation_id, code_before, code_after, diff, description),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("RunTracker.record_fix failed (non-blocking): %s", exc)

    def mark_fixed(self, violation_id: str, fix_cost: float = 0.0) -> None:
        """Mark a violation as fixed and record the cost."""
        try:
            conn = self._pool.get()
            conn.execute(
                """UPDATE violations_observed
                   SET was_fixed = 1, fix_cost = ?
                   WHERE violation_id = ?""",
                (fix_cost, violation_id),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("RunTracker.mark_fixed failed (non-blocking): %s", exc)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats_for_stack(self, tech_stack: str) -> list[dict]:
        """Return scan_code_stats rows for a tech stack, ordered by occurrence count.

        Returns:
            List of dicts with scan_code, tech_stack, occurrence_count,
            fix_success_rate, avg_fix_cost, promotion_candidate.
        """
        try:
            conn = self._pool.get()
            rows = conn.execute(
                """SELECT scan_code, tech_stack, occurrence_count,
                          fix_success_rate, avg_fix_cost, promotion_candidate
                   FROM scan_code_stats
                   WHERE tech_stack = ?
                   ORDER BY occurrence_count DESC""",
                (tech_stack,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("RunTracker.get_stats_for_stack failed (non-blocking): %s", exc)
            return []

    def update_scan_code_stats(self, run_id: str) -> None:
        """Recompute aggregate scan_code_stats after a run completes.

        Aggregates all violations across all runs, grouped by
        (scan_code, tech_stack).  Called internally after write operations.
        """
        try:
            conn = self._pool.get()
            conn.execute(
                """INSERT OR REPLACE INTO scan_code_stats
                       (scan_code, tech_stack, occurrence_count,
                        fix_success_rate, avg_fix_cost, promotion_candidate)
                   SELECT
                       scan_code,
                       service_tech_stack,
                       COUNT(*) AS occurrence_count,
                       CASE WHEN COUNT(*) > 0
                            THEN CAST(SUM(was_fixed) AS REAL) / COUNT(*)
                            ELSE 0.0
                       END AS fix_success_rate,
                       CASE WHEN SUM(was_fixed) > 0
                            THEN SUM(fix_cost) / SUM(was_fixed)
                            ELSE 0.0
                       END AS avg_fix_cost,
                       CASE WHEN COUNT(*) >= 10 THEN 1 ELSE 0 END AS promotion_candidate
                   FROM violations_observed
                   WHERE scan_code IS NOT NULL
                     AND service_tech_stack IS NOT NULL
                   GROUP BY scan_code, service_tech_stack""",
            )
            conn.commit()
        except Exception as exc:
            logger.warning("RunTracker.update_scan_code_stats failed (non-blocking): %s", exc)

    def close(self) -> None:
        """Close the database connection pool."""
        self._pool.close()
