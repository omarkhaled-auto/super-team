"""Run4State — pipeline state persistence with atomic writes."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    """A single defect or observation discovered during verification.

    Findings follow the ``FINDING-NNN`` naming convention and track
    resolution through fix passes.
    """

    finding_id: str = ""  # FINDING-NNN pattern
    priority: str = ""  # P0, P1, P2, P3
    system: str = ""  # "Build 1", "Build 2", "Build 3", "Integration"
    component: str = ""  # specific module/function
    evidence: str = ""  # exact reproduction or test output
    recommendation: str = ""  # specific fix action
    resolution: str = "OPEN"  # "FIXED", "OPEN", "WONTFIX"
    fix_pass_number: int = 0  # which pass fixed it (0 = unfixed)
    fix_verification: str = ""  # test ID confirming fix
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class Run4State:
    """Full state of a Run 4 verification pipeline execution.

    Persisted to ``run4_state.json`` using atomic writes (write to
    ``.tmp`` then ``os.replace``).  Supports ``save``/``load`` round-
    trips with schema version validation.
    """

    schema_version: int = 1
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    current_phase: str = "init"
    completed_phases: list[str] = field(default_factory=list)

    # MCP health results
    mcp_health: dict[str, dict] = field(default_factory=dict)

    # Builder results
    builder_results: dict[str, dict] = field(default_factory=dict)

    # Defect catalog
    findings: list[Finding] = field(default_factory=list)

    # Fix pass metrics
    fix_passes: list[dict] = field(default_factory=list)

    # Scoring
    scores: dict[str, float] = field(default_factory=dict)
    aggregate_score: float = 0.0
    traffic_light: str = "RED"

    # Cost tracking
    total_cost: float = 0.0
    phase_costs: dict[str, float] = field(default_factory=dict)

    # Timestamps
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ------------------------------------------------------------------
    # Finding management
    # ------------------------------------------------------------------

    def next_finding_id(self) -> str:
        """Generate the next ``FINDING-NNN`` identifier.

        Returns:
            A string like ``FINDING-001``, auto-incremented from the
            current maximum.
        """
        if not self.findings:
            return "FINDING-001"
        max_num = 0
        for f in self.findings:
            if f.finding_id.startswith("FINDING-"):
                try:
                    num = int(f.finding_id.split("-", 1)[1])
                    max_num = max(max_num, num)
                except (ValueError, IndexError):
                    pass
        return f"FINDING-{max_num + 1:03d}"

    def add_finding(self, finding: Finding) -> None:
        """Append a finding to the defect catalog.

        If the finding has no ``finding_id`` set, one is generated
        automatically.
        """
        if not finding.finding_id:
            finding.finding_id = self.next_finding_id()
        self.findings.append(finding)
        logger.info("Added finding %s (priority=%s)", finding.finding_id, finding.priority)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Persist state to disk using atomic writes.

        Writes to a temporary file first, then uses ``os.replace`` for
        an atomic rename, preventing corruption on crash.

        Args:
            path: Target JSON file path.
        """
        self.updated_at = datetime.now(timezone.utc).isoformat()
        data = self._to_dict()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, default=str)
            os.replace(tmp_path, path)
            logger.debug("State saved to %s", path)
        except Exception:
            # Clean up temp file on failure
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    @classmethod
    def load(cls, path: Path) -> Run4State | None:
        """Load state from a JSON file.

        Returns ``None`` for missing files or corrupted JSON.  Validates
        the ``schema_version`` field to guard against incompatible data.

        Args:
            path: Source JSON file path.

        Returns:
            Reconstructed ``Run4State``, or ``None`` if the file is
            missing, corrupted, or has an incompatible schema version.
        """
        path = Path(path)
        if not path.exists():
            logger.debug("State file not found: %s", path)
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load state from %s: %s", path, exc)
            return None

        if not isinstance(data, dict):
            logger.warning("State file does not contain a JSON object: %s", path)
            return None

        # Schema version check
        schema_ver = data.get("schema_version", 0)
        if schema_ver != 1:
            logger.warning(
                "Incompatible schema version %s in %s (expected 1)", schema_ver, path
            )
            return None

        # Reconstruct findings
        raw_findings = data.pop("findings", [])
        findings: list[Finding] = []
        for raw in raw_findings:
            if isinstance(raw, dict):
                known = {f.name for f in Finding.__dataclass_fields__.values()}
                filtered = {k: v for k, v in raw.items() if k in known}
                findings.append(Finding(**filtered))

        # Filter to known Run4State fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        filtered_data["findings"] = findings

        state = cls(**filtered_data)
        logger.debug("State loaded from %s (run_id=%s)", path, state.run_id)
        return state

    def _to_dict(self) -> dict:
        """Serialise state to a plain dictionary."""
        data = asdict(self)
        return data
