"""Tests for SuperOrchestratorConfig and load_super_config.

TEST-004: >= 12 test cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.super_orchestrator.config import (
    ArchitectConfig,
    BuilderConfig,
    IntegrationConfig,
    QualityGateConfig,
    SuperOrchestratorConfig,
    load_super_config,
)


class TestConfigDefaults:
    """Test default config values."""

    def test_architect_defaults(self) -> None:
        cfg = ArchitectConfig()
        assert cfg.timeout == 900
        assert cfg.max_retries == 2
        assert cfg.auto_approve is False

    def test_builder_defaults(self) -> None:
        cfg = BuilderConfig()
        assert cfg.max_concurrent == 3
        assert cfg.timeout_per_builder == 1800
        assert cfg.depth == "thorough"

    def test_integration_defaults(self) -> None:
        cfg = IntegrationConfig()
        assert cfg.timeout == 600
        assert cfg.traefik_image == "traefik:v3.6"
        assert cfg.compose_file == "docker-compose.yml"
        assert cfg.test_compose_file == "docker-compose.test.yml"

    def test_quality_gate_defaults(self) -> None:
        cfg = QualityGateConfig()
        assert cfg.max_fix_retries == 3
        assert cfg.layer4_enabled is True
        assert cfg.blocking_severity == "error"
        assert "security" in cfg.layer3_scanners

    def test_super_config_defaults(self) -> None:
        cfg = SuperOrchestratorConfig()
        assert cfg.budget_limit is None
        assert cfg.output_dir == ".super-orchestrator"
        assert isinstance(cfg.architect, ArchitectConfig)
        assert isinstance(cfg.builder, BuilderConfig)
        assert isinstance(cfg.integration, IntegrationConfig)
        assert isinstance(cfg.quality_gate, QualityGateConfig)
        assert cfg.depth == "standard"
        assert cfg.mode == "auto"


class TestLoadSuperConfig:
    """Test YAML config loading."""

    def test_load_none_returns_defaults(self) -> None:
        cfg = load_super_config(None)
        assert cfg.budget_limit is None

    def test_load_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        cfg = load_super_config(tmp_path / "nonexistent.yaml")
        assert cfg.budget_limit is None

    def test_load_full_config(self, tmp_path: Path) -> None:
        config_data = {
            "architect": {"timeout": 600, "max_retries": 3},
            "builder": {"max_concurrent": 5, "depth": "quick"},
            "integration": {"timeout": 180},
            "quality_gate": {"max_fix_retries": 5},
            "budget_limit": 100.0,
        }
        path = tmp_path / "config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        cfg = load_super_config(path)
        assert cfg.architect.timeout == 600
        assert cfg.architect.max_retries == 3
        assert cfg.builder.max_concurrent == 5
        assert cfg.builder.depth == "quick"
        assert cfg.integration.timeout == 180
        assert cfg.quality_gate.max_fix_retries == 5
        assert cfg.budget_limit == 100.0

    def test_load_partial_config_uses_defaults(self, tmp_path: Path) -> None:
        config_data = {"architect": {"timeout": 999}}
        path = tmp_path / "config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        cfg = load_super_config(path)
        assert cfg.architect.timeout == 999
        assert cfg.architect.max_retries == 2  # default
        assert cfg.builder.max_concurrent == 3  # default

    def test_load_unknown_keys_ignored(self, tmp_path: Path) -> None:
        config_data = {
            "architect": {"timeout": 100, "unknown_key": "ignored"},
            "some_future_section": {"foo": "bar"},
        }
        path = tmp_path / "config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        cfg = load_super_config(path)
        assert cfg.architect.timeout == 100

    def test_load_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        cfg = load_super_config(path)
        assert cfg.budget_limit is None

    def test_load_missing_sections(self, tmp_path: Path) -> None:
        config_data = {"budget_limit": 75.0}
        path = tmp_path / "config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        cfg = load_super_config(path)
        assert cfg.budget_limit == 75.0
        assert cfg.architect.timeout == 900  # default
