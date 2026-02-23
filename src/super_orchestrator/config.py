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
class GraphRAGConfig:
    """Configuration for the Graph RAG module."""
    enabled: bool = True
    mcp_command: str = "python"
    mcp_args: list[str] = field(default_factory=lambda: ["-m", "src.graph_rag.mcp_server"])
    database_path: str = "./data/graph_rag.db"
    chroma_path: str = "./data/graph_rag_chroma"
    ci_database_path: str = "./data/codebase_intel.db"
    architect_database_path: str = "./data/architect.db"
    contract_database_path: str = "./data/contracts.db"
    context_token_budget: int = 2000
    semantic_weight: float = 0.6
    graph_weight: float = 0.4
    startup_timeout_ms: int = 30000


@dataclass
class PersistenceConfig:
    """Configuration for the persistent intelligence layer."""

    enabled: bool = False
    db_path: str = ".super-orchestrator/persistence.db"
    chroma_path: str = ".super-orchestrator/pattern-store"
    max_patterns_per_injection: int = 5
    min_occurrences_for_promotion: int = 10


@dataclass
class SuperOrchestratorConfig:
    """Top-level configuration composing all sub-configs."""

    architect: ArchitectConfig = field(default_factory=ArchitectConfig)
    builder: BuilderConfig = field(default_factory=BuilderConfig)
    integration: IntegrationConfig = field(default_factory=IntegrationConfig)
    quality_gate: QualityGateConfig = field(default_factory=QualityGateConfig)
    graph_rag: GraphRAGConfig = field(default_factory=GraphRAGConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    budget_limit: float | None = None
    depth: str = "standard"
    phase_timeouts: dict[str, int] = field(default_factory=dict)
    build1_services_dir: str = ""
    agent_team_config_path: str = ""
    mode: str = "auto"  # "docker", "mcp", or "auto" (auto-detect)
    output_dir: str = ".super-orchestrator"


# Depth-gating: features that are only enabled at certain depth levels.
# Maps feature → set of depths where the feature should be enabled.
_DEPTH_GATES: dict[str, set[str]] = {
    "persistence": {"thorough", "exhaustive"},
}


def _apply_depth_gates(cfg: SuperOrchestratorConfig) -> None:
    """Override feature flags based on the top-level ``depth`` setting.

    Only applies when the user has not explicitly set the feature in YAML.
    For persistence: quick/standard → disabled, thorough/exhaustive → enabled.
    """
    depth = cfg.depth
    if depth in _DEPTH_GATES.get("persistence", set()):
        # Enable persistence at thorough/exhaustive unless user explicitly disabled
        # (We enable by default at these depths; explicit YAML 'enabled: false' still wins
        # because the YAML value overwrites the dataclass default before we get here.)
        if cfg.persistence.enabled is False:
            # Check if this is still the dataclass default (False) — if YAML didn't
            # set it, we auto-enable.  We rely on a sentinel to distinguish "user set
            # False" from "default False".  Since we can't add a sentinel to an existing
            # dataclass without breaking things, we use a simple heuristic: if the user
            # provided a persistence section in YAML at all, respect their explicit
            # setting; otherwise auto-enable.
            cfg.persistence.enabled = True


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
    graph_rag_raw = raw.get("graph_rag", {})
    persistence_raw = raw.get("persistence", {})

    top_level = _pick(raw, SuperOrchestratorConfig)
    # Remove sub-config keys that need special handling
    for key in ("architect", "builder", "integration", "quality_gate", "graph_rag", "persistence"):
        top_level.pop(key, None)

    cfg = SuperOrchestratorConfig(
        architect=ArchitectConfig(**_pick(architect_raw, ArchitectConfig)),
        builder=BuilderConfig(**_pick(builder_raw, BuilderConfig)),
        integration=IntegrationConfig(**_pick(integration_raw, IntegrationConfig)),
        quality_gate=QualityGateConfig(**_pick(quality_gate_raw, QualityGateConfig)),
        graph_rag=GraphRAGConfig(**_pick(graph_rag_raw, GraphRAGConfig)),
        persistence=PersistenceConfig(**_pick(persistence_raw, PersistenceConfig)),
        **top_level,
    )

    # Apply depth-gating unless the user explicitly configured persistence
    if "persistence" not in raw or "enabled" not in raw.get("persistence", {}):
        _apply_depth_gates(cfg)

    return cfg
