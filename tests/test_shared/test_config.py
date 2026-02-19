"""Tests for configuration management."""
from __future__ import annotations

import os

import pytest

from src.shared.config import (
    ArchitectConfig,
    CodebaseIntelConfig,
    ContractEngineConfig,
    SharedConfig,
)


class TestSharedConfig:
    def test_default_values(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DATABASE_PATH", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        config = SharedConfig()
        assert config.log_level == "info"
        assert config.database_path == "./data/service.db"

    def test_env_override_log_level(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        config = SharedConfig()
        assert config.log_level == "debug"

    def test_env_override_database_path(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_PATH", "/custom/path.db")
        config = SharedConfig()
        assert config.database_path == "/custom/path.db"


class TestArchitectConfig:
    def test_default_values(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CONTRACT_ENGINE_URL", raising=False)
        monkeypatch.delenv("CODEBASE_INTEL_URL", raising=False)
        config = ArchitectConfig()
        assert config.contract_engine_url == "http://contract-engine:8000"
        assert config.codebase_intel_url == "http://codebase-intel:8000"

    def test_inherits_shared_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DATABASE_PATH", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        config = ArchitectConfig()
        assert config.log_level == "info"
        assert config.database_path == "./data/service.db"

    def test_env_override_contract_engine_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CONTRACT_ENGINE_URL", "http://localhost:9000")
        config = ArchitectConfig()
        assert config.contract_engine_url == "http://localhost:9000"

    def test_env_override_codebase_intel_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CODEBASE_INTEL_URL", "http://localhost:9001")
        config = ArchitectConfig()
        assert config.codebase_intel_url == "http://localhost:9001"


class TestContractEngineConfig:
    def test_default_values(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DATABASE_PATH", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        config = ContractEngineConfig()
        assert config.log_level == "info"
        assert config.database_path == "./data/service.db"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_PATH", "/data/contracts.db")
        config = ContractEngineConfig()
        assert config.database_path == "/data/contracts.db"


class TestCodebaseIntelConfig:
    def test_default_values(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CONTRACT_ENGINE_URL", raising=False)
        monkeypatch.delenv("CODEBASE_INTEL_URL", raising=False)
        monkeypatch.delenv("CHROMA_PATH", raising=False)
        monkeypatch.delenv("GRAPH_PATH", raising=False)
        config = CodebaseIntelConfig()
        assert config.chroma_path == "./data/chroma"
        assert config.graph_path == "./data/graph.json"
        assert config.contract_engine_url == "http://contract-engine:8000"

    def test_inherits_shared_defaults(self):
        config = CodebaseIntelConfig()
        assert config.log_level == "info"

    def test_env_override_chroma_path(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CHROMA_PATH", "/custom/chroma")
        config = CodebaseIntelConfig()
        assert config.chroma_path == "/custom/chroma"

    def test_env_override_graph_path(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GRAPH_PATH", "/custom/graph.json")
        config = CodebaseIntelConfig()
        assert config.graph_path == "/custom/graph.json"

    def test_env_override_all(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LOG_LEVEL", "error")
        monkeypatch.setenv("DATABASE_PATH", "/db.sqlite")
        monkeypatch.setenv("CHROMA_PATH", "/chroma")
        monkeypatch.setenv("GRAPH_PATH", "/graph.json")
        monkeypatch.setenv("CONTRACT_ENGINE_URL", "http://remote:8000")
        config = CodebaseIntelConfig()
        assert config.log_level == "error"
        assert config.database_path == "/db.sqlite"
        assert config.chroma_path == "/chroma"
        assert config.graph_path == "/graph.json"
        assert config.contract_engine_url == "http://remote:8000"


class TestConfigInheritance:
    """Tests for config class inheritance patterns."""

    def test_architect_inherits_shared_config(self):
        assert issubclass(ArchitectConfig, SharedConfig)

    def test_contract_engine_inherits_shared_config(self):
        assert issubclass(ContractEngineConfig, SharedConfig)

    def test_codebase_intel_inherits_shared_config(self):
        assert issubclass(CodebaseIntelConfig, SharedConfig)

    def test_shared_config_has_log_level(self):
        config = SharedConfig()
        assert hasattr(config, "log_level")

    def test_shared_config_has_database_path(self):
        config = SharedConfig()
        assert hasattr(config, "database_path")


class TestConfigMultipleInstances:
    """Tests for creating multiple config instances."""

    def test_different_env_produces_different_configs(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        c1 = SharedConfig()
        monkeypatch.setenv("LOG_LEVEL", "error")
        c2 = SharedConfig()
        assert c1.log_level == "debug"
        assert c2.log_level == "error"

    def test_architect_config_defaults_independent(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CONTRACT_ENGINE_URL", raising=False)
        monkeypatch.delenv("CODEBASE_INTEL_URL", raising=False)
        config = ArchitectConfig()
        assert "contract-engine" in config.contract_engine_url
        assert "codebase-intel" in config.codebase_intel_url
