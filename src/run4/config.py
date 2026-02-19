"""Run4Config — configuration dataclass with path validation and YAML loading."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Run4Config:
    """Configuration for a Run 4 verification pipeline execution.

    All path fields are validated on construction to ensure they reference
    existing directories.  The ``from_yaml`` factory reads the ``run4:``
    section of a YAML config file.
    """

    # Build paths
    build1_project_root: Path = field(default_factory=lambda: Path("."))
    build2_project_root: Path = field(default_factory=lambda: Path("."))
    build3_project_root: Path = field(default_factory=lambda: Path("."))
    output_dir: str = ".run4"

    # Docker settings
    compose_project_name: str = "super-team-run4"
    docker_compose_files: list[str] = field(default_factory=list)

    # MCP timeouts
    health_check_timeout_s: int = 120
    health_check_interval_s: float = 3.0
    mcp_startup_timeout_ms: int = 30000
    mcp_tool_timeout_ms: int = 60000
    mcp_first_start_timeout_ms: int = 120000

    # Builder settings
    max_concurrent_builders: int = 3
    builder_timeout_s: int = 1800
    builder_depth: str = "thorough"

    # Fix pass limits
    max_fix_passes: int = 5
    fix_effectiveness_floor: float = 0.30
    regression_rate_ceiling: float = 0.25

    # Budget
    max_budget_usd: float = 100.0

    # Paths
    sample_prd_path: str = "tests/run4/fixtures/sample_prd.md"

    def __post_init__(self) -> None:
        """Validate that all path fields reference existing directories."""
        self.build1_project_root = Path(self.build1_project_root)
        self.build2_project_root = Path(self.build2_project_root)
        self.build3_project_root = Path(self.build3_project_root)

        for name in ("build1_project_root", "build2_project_root", "build3_project_root"):
            path = getattr(self, name)
            if not path.exists():
                raise ValueError(
                    f"Run4Config.{name} path does not exist: {path}"
                )
        logger.debug("Run4Config validated — all paths exist")

    @classmethod
    def from_yaml(cls, path: str) -> Run4Config:
        """Parse a ``run4:`` section from a YAML configuration file.

        Unknown keys are silently ignored for forward-compatibility.

        Args:
            path: Filesystem path to the YAML config file.

        Returns:
            Populated ``Run4Config`` instance.

        Raises:
            FileNotFoundError: If *path* does not exist.
            ValueError: If the ``run4:`` section is missing.
        """
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(config_path, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        run4_section = raw.get("run4", {})
        if not run4_section:
            raise ValueError(f"No 'run4:' section found in {path}")

        # Filter to known field names
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in run4_section.items() if k in known_fields}

        logger.info("Loaded Run4Config from %s (%d keys)", path, len(filtered))
        return cls(**filtered)
