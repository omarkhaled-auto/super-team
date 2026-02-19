"""Pipeline state persistence with atomic writes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.build3_shared.utils import atomic_write_json, load_json


@dataclass
class PipelineState:
    """Represents the full state of a pipeline run.

    Persisted to ``PIPELINE_STATE.json`` using atomic writes.
    """

    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    prd_path: str = ""
    config_path: str = ""
    depth: str = "thorough"
    current_state: str = "init"
    previous_state: str = ""
    completed_phases: list[str] = field(default_factory=list)
    phase_artifacts: dict[str, Any] = field(default_factory=dict)
    architect_retries: int = 0
    max_architect_retries: int = 2
    service_map_path: str = ""
    contract_registry_path: str = ""
    domain_model_path: str = ""
    builder_statuses: dict[str, str] = field(default_factory=dict)
    builder_costs: dict[str, float] = field(default_factory=dict)
    builder_results: list[dict] = field(default_factory=list)
    total_builders: int = 0
    successful_builders: int = 0
    services_deployed: list[str] = field(default_factory=list)
    integration_report_path: str = ""
    quality_attempts: int = 0
    max_quality_retries: int = 3
    last_quality_results: dict[str, Any] = field(default_factory=dict)
    quality_report_path: str = ""
    total_cost: float = 0.0
    phase_costs: dict[str, float] = field(default_factory=dict)
    budget_limit: float | None = None
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    interrupted: bool = False
    interrupt_reason: str = ""
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise the state to a plain dictionary."""
        from dataclasses import asdict

        return asdict(self)

    def save(self, directory: Path | str | None = None) -> Path:
        """Persist state to disk using atomic writes.

        Args:
            directory: Target directory.  Defaults to the standard state
                       directory location.

        Returns:
            The path the state was written to.
        """
        from src.build3_shared.constants import STATE_DIR, STATE_FILE

        directory = Path(directory) if directory else Path(STATE_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / STATE_FILE
        self.updated_at = datetime.now(timezone.utc).isoformat()
        atomic_write_json(target, self.to_dict())
        return target

    @classmethod
    def load(cls, directory: Path | str | None = None) -> PipelineState | None:
        """Load state from a JSON file.

        Args:
            directory: Source directory.  Defaults to the standard state
                       directory location.

        Returns:
            Reconstructed ``PipelineState``, or ``None`` if the file is
            missing or invalid.
        """
        from src.build3_shared.constants import STATE_DIR, STATE_FILE

        directory = Path(directory) if directory else Path(STATE_DIR)
        target = directory / STATE_FILE
        data = load_json(target)
        if data is None:
            return None
        # Filter to only known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @classmethod
    def clear(cls, directory: Path | str | None = None) -> None:
        """Remove the state directory if it exists.

        Args:
            directory: Directory to remove.  Defaults to the standard state
                       directory location.
        """
        import shutil

        from src.build3_shared.constants import STATE_DIR

        directory = Path(directory) if directory else Path(STATE_DIR)
        if directory.exists():
            shutil.rmtree(directory)
