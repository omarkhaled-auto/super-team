"""Phase 5 wiring verification tests -- one test per gap closure."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestGap1FailureContextReachesBuilder:
    """Gap 1: build_failure_context() must appear in builder config."""

    def test_generate_builder_config_includes_failure_context(
        self, tmp_path: Path
    ) -> None:
        """generate_builder_config() populates 'failure_context' key."""
        from src.super_orchestrator.config import (
            SuperOrchestratorConfig,
            PersistenceConfig,
        )
        from src.super_orchestrator.pipeline import generate_builder_config
        from src.build3_shared.models import ServiceInfo
        from src.super_orchestrator.state import PipelineState

        # Set up a config with persistence disabled (default) -- should get ""
        config = SuperOrchestratorConfig()
        config.output_dir = str(tmp_path / "output")

        svc = ServiceInfo(
            service_id="user-svc",
            domain="users",
            stack={"language": "python", "framework": "fastapi"},
            port=8080,
        )

        state = PipelineState(
            pipeline_id="test-pipe",
            prd_path=str(tmp_path / "prd.md"),
        )

        config_dict, _ = generate_builder_config(svc, config, state)

        # Key MUST exist regardless of whether persistence is enabled
        assert "failure_context" in config_dict
        # When disabled, it should be empty string
        assert config_dict["failure_context"] == ""


class TestGap1FixContextReachesFixInstructions:
    """Gap 1: build_fix_context() output must appear in FIX_INSTRUCTIONS.md."""

    def test_write_fix_instructions_includes_fix_context(
        self, tmp_path: Path
    ) -> None:
        """fix_context parameter is appended to FIX_INSTRUCTIONS.md."""
        from src.run4.builder import write_fix_instructions

        violations = [
            {"code": "SEC-001", "component": "auth.py", "evidence": "no auth",
             "action": "add auth", "message": "Missing auth", "priority": "P1"},
        ]
        fake_context = (
            "\n\n"
            "================================================\n"
            "FIX EXAMPLES FROM PRIOR RUNS\n"
            "================================================\n"
            "[SEC-001] Prior fix:\n- old\n+ new\n"
            "================================================\n"
        )

        path = write_fix_instructions(
            tmp_path, violations, fix_context=fake_context,
        )
        content = path.read_text(encoding="utf-8")

        assert "FIX EXAMPLES FROM PRIOR RUNS" in content
        assert "SEC-001" in content
        assert "================================================" in content


class TestGap2AcceptanceTestsReachBuilder:
    """Gap 2: ACCEPTANCE_TESTS.md content must appear in builder config."""

    def test_generate_builder_config_reads_acceptance_tests_md(
        self, tmp_path: Path
    ) -> None:
        """When ACCEPTANCE_TESTS.md exists, it appears in config_dict."""
        from src.super_orchestrator.config import SuperOrchestratorConfig
        from src.super_orchestrator.pipeline import generate_builder_config
        from src.build3_shared.models import ServiceInfo
        from src.super_orchestrator.state import PipelineState

        output_dir = tmp_path / "output"
        config = SuperOrchestratorConfig()
        config.output_dir = str(output_dir)

        svc = ServiceInfo(
            service_id="order-svc",
            domain="orders",
            stack={"language": "python", "framework": "fastapi"},
            port=8081,
        )

        state = PipelineState(
            pipeline_id="test-pipe",
            prd_path=str(tmp_path / "prd.md"),
        )

        # Pre-create the ACCEPTANCE_TESTS.md file in the service output dir
        svc_dir = output_dir / "order-svc"
        svc_dir.mkdir(parents=True, exist_ok=True)
        acceptance_md = svc_dir / "ACCEPTANCE_TESTS.md"
        acceptance_md.write_text(
            "# Acceptance Tests\n\npytest tests/acceptance/\n",
            encoding="utf-8",
        )

        config_dict, _ = generate_builder_config(svc, config, state)

        assert "acceptance_test_requirements" in config_dict
        assert "ACCEPTANCE TEST REQUIREMENTS" in config_dict["acceptance_test_requirements"]
        assert "Acceptance Tests" in config_dict["acceptance_test_requirements"]


class TestGap3DepthGating:
    """Gap 3: persistence.enabled must follow depth-gating rules."""

    def test_thorough_depth_enables_persistence(self, tmp_path: Path) -> None:
        """depth=thorough with no explicit persistence config -> enabled=True."""
        from src.super_orchestrator.config import load_super_config
        import yaml

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"depth": "thorough"}), encoding="utf-8"
        )

        cfg = load_super_config(config_file)
        assert cfg.persistence.enabled is True

    def test_quick_depth_keeps_persistence_disabled(self, tmp_path: Path) -> None:
        """depth=quick with no explicit persistence config -> enabled=False."""
        from src.super_orchestrator.config import load_super_config
        import yaml

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"depth": "quick"}), encoding="utf-8"
        )

        cfg = load_super_config(config_file)
        assert cfg.persistence.enabled is False

    def test_standard_depth_keeps_persistence_disabled(self, tmp_path: Path) -> None:
        """depth=standard with no explicit persistence config -> enabled=False."""
        from src.super_orchestrator.config import load_super_config
        import yaml

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"depth": "standard"}), encoding="utf-8"
        )

        cfg = load_super_config(config_file)
        assert cfg.persistence.enabled is False

    def test_explicit_disabled_overrides_depth_gating(self, tmp_path: Path) -> None:
        """depth=thorough but persistence.enabled=false -> stays disabled."""
        from src.super_orchestrator.config import load_super_config
        import yaml

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"depth": "thorough", "persistence": {"enabled": False}}),
            encoding="utf-8",
        )

        cfg = load_super_config(config_file)
        assert cfg.persistence.enabled is False
