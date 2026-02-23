"""Gap detector -- finds uncategorized violations and clusters them.

Identifies violations with scan codes not in the known 40 scan codes
and clusters them by semantic similarity.  Each cluster is a candidate
for promotion to a new scan code.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.build3_shared.constants import ALL_SCAN_CODES

if TYPE_CHECKING:
    from src.persistence.run_tracker import RunTracker

logger = logging.getLogger(__name__)


@dataclass
class PatternCluster:
    """A cluster of semantically similar violations."""

    representative_message: str
    violation_count: int
    suggested_scan_code: str  # e.g. "LEARNED-001"
    member_violations: list[str] = field(default_factory=list)  # violation IDs


class GapDetector:
    """Detects violations with unknown scan codes and clusters them.

    Queries the ``RunTracker`` for violations in a given run, filters
    out those with known scan codes, and groups the remainder by
    semantic similarity using ChromaDB.
    """

    def find_uncategorized_violations(
        self,
        run_id: str,
        run_tracker: "RunTracker",
        known_scan_codes: set[str] | None = None,
    ) -> list[PatternCluster]:
        """Find violations not covered by known scan codes.

        Args:
            run_id: Pipeline run to analyze.
            run_tracker: SQLite-backed run tracker.
            known_scan_codes: Set of known codes.  Defaults to
                ``ALL_SCAN_CODES`` from constants.

        Returns:
            List of pattern clusters for uncategorized violations.
        """
        if known_scan_codes is None:
            known_scan_codes = set(ALL_SCAN_CODES)

        try:
            conn = run_tracker._pool.get()
            rows = conn.execute(
                """SELECT violation_id, scan_code, message
                   FROM violations_observed
                   WHERE run_id = ?""",
                (run_id,),
            ).fetchall()

            # Filter to unknown scan codes
            unknown: list[dict[str, str]] = []
            for row in rows:
                code = row["scan_code"] or ""
                if code and code not in known_scan_codes:
                    unknown.append({
                        "violation_id": row["violation_id"],
                        "scan_code": code,
                        "message": row["message"] or "",
                    })

            if not unknown:
                return []

            # Simple clustering by scan_code prefix
            clusters_by_code: dict[str, list[dict[str, str]]] = {}
            for v in unknown:
                code = v["scan_code"]
                clusters_by_code.setdefault(code, []).append(v)

            clusters: list[PatternCluster] = []
            for i, (code, members) in enumerate(clusters_by_code.items()):
                clusters.append(PatternCluster(
                    representative_message=members[0]["message"][:200] if members else "",
                    violation_count=len(members),
                    suggested_scan_code=f"GAP-{i + 1:03d}",
                    member_violations=[m["violation_id"] for m in members],
                ))

            return clusters

        except Exception as exc:
            logger.warning("GapDetector.find_uncategorized_violations failed: %s", exc)
            return []
