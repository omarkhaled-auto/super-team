"""Configuration dataclasses and loader for Super Orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ArchitectConfig:
    """Configuration for the architect phase."""

    max_retries: int = 2
    timeout: int = 900
    auto_approve: bool = False


@dataclass
class BuilderConfig:
    """Configuration for the builder phase."""

    max_concurrent: int = 3
    timeout_per_builder: int = 1800
    depth: str = "thorough"


@dataclass
class IntegrationConfig:
    """Configuration for the integration phase."""

    timeout: int = 600
    traefik_image: str = "traefik:v3.6"
    compose_file: str = "docker-compose.yml"
    test_compose_file: str = "docker-compose.test.yml"


@dataclass
class QualityGateConfig:
    """Configuration for the quality gate phase."""

    max_fix_retries: int = 3
    layer3_scanners: list[str] = field(
        default_factory=lambda: [
            "security", "cors", "logging", "trace", "secrets", "docker", "health"
        ]
    )
    layer4_enabled: bool = True
    blocking_severity: str = "error"


@dataclass
class SuperOrchestratorConfig:
    """Top-level configuration composing all sub-configs."""

    architect: ArchitectConfig = field(default_factory=ArchitectConfig)
    builder: BuilderConfig = field(default_factory=BuilderConfig)
    integration: IntegrationConfig = field(default_factory=IntegrationConfig)
    quality_gate: QualityGateConfig = field(default_factory=QualityGateConfig)
    budget_limit: float | None = None
    depth: str = "standard"
    phase_timeouts: dict[str, int] = field(default_factory=dict)
    build1_services_dir: str = ""
    agent_team_config_path: str = ""
    mode: str = "auto"  # "docker", "mcp", or "auto" (auto-detect)
    output_dir: str = ".super-orchestrator"


def load_super_config(path: Path | str | None = None) -> SuperOrchestratorConfig:
    """Load Super Orchestrator configuration from a YAML file.

    Missing top-level sections fall back to defaults.  Unknown keys are
    silently ignored so that forward-compatible config files work.

    Args:
        path: Path to config YAML.  If ``None`` or the file does not
              exist, returns full defaults.

    Returns:
        Populated configuration dataclass.
    """
    if path is None:
        return SuperOrchestratorConfig()

    path = Path(path)
    if not path.exists():
        return SuperOrchestratorConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    def _pick(data: dict[str, Any], cls: type) -> dict[str, Any]:
        """Filter *data* to only keys accepted by *cls*."""
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return {k: v for k, v in data.items() if k in valid}

    architect_raw = raw.get("architect", {})
    builder_raw = raw.get("builder", {})
    integration_raw = raw.get("integration", {})
    quality_gate_raw = raw.get("quality_gate", {})

    top_level = _pick(raw, SuperOrchestratorConfig)
    # Remove sub-config keys that need special handling
    for key in ("architect", "builder", "integration", "quality_gate"):
        top_level.pop(key, None)

    return SuperOrchestratorConfig(
        architect=ArchitectConfig(**_pick(architect_raw, ArchitectConfig)),
        builder=BuilderConfig(**_pick(builder_raw, BuilderConfig)),
        integration=IntegrationConfig(**_pick(integration_raw, IntegrationConfig)),
        quality_gate=QualityGateConfig(**_pick(quality_gate_raw, QualityGateConfig)),
        **top_level,
    )
