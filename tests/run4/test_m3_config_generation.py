"""Milestone 3 — Config generation & BuilderResult mapping tests.

TEST-009, TEST-010, and SVC-020 tests verifying that BuilderResult
correctly maps STATE.JSON summary fields, parallel builder results
aggregate properly, and generated config.yaml files are valid across
all depth levels.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from src.run4.builder import (
    BuilderResult,
    _state_to_builder_result,
    generate_builder_config,
    parse_builder_state,
    run_parallel_builders,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_state_json(output_dir: Path, data: dict[str, Any]) -> Path:
    """Write a STATE.json fixture into ``output_dir/.agent-team/``."""
    agent_dir = output_dir / ".agent-team"
    agent_dir.mkdir(parents=True, exist_ok=True)
    state_path = agent_dir / "STATE.json"
    state_path.write_text(json.dumps(data), encoding="utf-8")
    return state_path


# ===================================================================
# TEST-009: BuilderResult dataclass maps all STATE.JSON summary fields
# ===================================================================


class TestBuilderResultDataclassMapping:
    """TEST-009 -- Verify BuilderResult correctly maps all STATE.JSON fields.

    The STATE.JSON cross-build contract specifies:
    - summary.success (bool)
    - summary.test_passed (int)
    - summary.test_total (int)
    - summary.convergence_ratio (float)
    - total_cost (float, top-level)
    - health (str, top-level)
    - completed_phases (list[str], top-level)

    BuilderResult must have fields for all of these PLUS process metadata
    (service_name, exit_code, stdout, stderr, duration_s).
    """

    def test_builder_result_dataclass_mapping(self) -> None:
        """TEST-009 -- BuilderResult correctly maps all STATE.JSON summary fields."""
        field_names = {f.name for f in dataclass_fields(BuilderResult)}

        # STATE.JSON summary fields
        state_json_fields = {
            "success",
            "test_passed",
            "test_total",
            "convergence_ratio",
            "total_cost",
            "health",
            "completed_phases",
        }
        for expected in state_json_fields:
            assert expected in field_names, (
                f"BuilderResult missing STATE.JSON field '{expected}'"
            )

        # Process metadata fields
        process_fields = {
            "service_name",
            "exit_code",
            "stdout",
            "stderr",
            "duration_s",
        }
        for expected in process_fields:
            assert expected in field_names, (
                f"BuilderResult missing process metadata field '{expected}'"
            )

    def test_builder_result_from_state_json_roundtrip(
        self, tmp_path: Path
    ) -> None:
        """Construct BuilderResult from a realistic STATE.JSON fixture."""
        state_data = {
            "run_id": "build-auth-001",
            "health": "green",
            "current_phase": "complete",
            "completed_phases": ["init", "scaffold", "implement", "test"],
            "total_cost": 3.42,
            "summary": {
                "success": True,
                "test_passed": 42,
                "test_total": 50,
                "convergence_ratio": 0.85,
            },
            "artifacts": {},
            "schema_version": 2,
        }
        _write_state_json(tmp_path, state_data)

        result = _state_to_builder_result(
            service_name="auth-service",
            output_dir=tmp_path,
            exit_code=0,
            stdout="Build complete.",
            stderr="",
            duration_s=120.5,
        )

        # Verify all STATE.JSON fields are mapped correctly
        assert result.service_name == "auth-service"
        assert result.success is True
        assert result.test_passed == 42
        assert result.test_total == 50
        assert result.convergence_ratio == 0.85
        assert result.total_cost == 3.42
        assert result.health == "green"
        assert result.completed_phases == [
            "init",
            "scaffold",
            "implement",
            "test",
        ]
        assert result.exit_code == 0
        assert result.stdout == "Build complete."
        assert result.stderr == ""
        assert result.duration_s == 120.5

    def test_builder_result_defaults_on_missing_state(
        self, tmp_path: Path
    ) -> None:
        """BuilderResult returns safe defaults when STATE.json is absent."""
        result = _state_to_builder_result(
            service_name="missing-service",
            output_dir=tmp_path,
        )
        assert result.success is False
        assert result.test_passed == 0
        assert result.test_total == 0
        assert result.convergence_ratio == 0.0
        assert result.total_cost == 0.0
        assert result.health == "unknown"
        assert result.completed_phases == []
        assert result.exit_code == -1

    def test_builder_result_partial_state_json(self, tmp_path: Path) -> None:
        """BuilderResult handles STATE.JSON with missing optional fields."""
        # STATE.JSON with summary but no top-level health/completed_phases
        state_data = {
            "summary": {
                "success": True,
                "test_passed": 10,
                "test_total": 10,
                "convergence_ratio": 1.0,
            },
        }
        _write_state_json(tmp_path, state_data)

        result = _state_to_builder_result(
            service_name="partial-service",
            output_dir=tmp_path,
            exit_code=0,
        )
        assert result.success is True
        assert result.test_passed == 10
        assert result.test_total == 10
        assert result.convergence_ratio == 1.0
        # Missing top-level fields get defaults
        assert result.total_cost == 0.0
        assert result.health == "unknown"
        assert result.completed_phases == []

    def test_parse_builder_state_field_types(self, tmp_path: Path) -> None:
        """parse_builder_state returns correct types for all fields."""
        state_data = {
            "health": "yellow",
            "completed_phases": ["init"],
            "total_cost": 1.5,
            "summary": {
                "success": True,
                "test_passed": 5,
                "test_total": 8,
                "convergence_ratio": 0.625,
            },
        }
        _write_state_json(tmp_path, state_data)

        parsed = parse_builder_state(tmp_path)
        assert isinstance(parsed["success"], bool)
        assert isinstance(parsed["test_passed"], int)
        assert isinstance(parsed["test_total"], int)
        assert isinstance(parsed["convergence_ratio"], float)
        assert isinstance(parsed["total_cost"], float)
        assert isinstance(parsed["health"], str)
        assert isinstance(parsed["completed_phases"], list)


# ===================================================================
# TEST-010: Parallel builder result aggregation
# ===================================================================


class TestParallelBuilderResultAggregation:
    """TEST-010 -- Collect BuilderResult from 3 builders; verify per-service
    results preserved in aggregate list.
    """

    @pytest.mark.asyncio
    async def test_parallel_builder_result_aggregation(
        self, tmp_path: Path
    ) -> None:
        """3 parallel builders each produce distinct BuilderResults."""
        services = [
            {
                "name": "auth-service",
                "success": True,
                "test_passed": 42,
                "test_total": 50,
                "convergence_ratio": 0.85,
                "total_cost": 3.42,
                "health": "green",
                "completed_phases": ["init", "scaffold", "implement", "test"],
            },
            {
                "name": "order-service",
                "success": True,
                "test_passed": 30,
                "test_total": 35,
                "convergence_ratio": 0.90,
                "total_cost": 2.80,
                "health": "green",
                "completed_phases": ["init", "scaffold", "implement"],
            },
            {
                "name": "notification-service",
                "success": False,
                "test_passed": 5,
                "test_total": 20,
                "convergence_ratio": 0.25,
                "total_cost": 1.10,
                "health": "red",
                "completed_phases": ["init", "scaffold"],
            },
        ]

        # Set up STATE.json files for each builder
        builder_configs: list[dict[str, Any]] = []
        for svc in services:
            svc_dir = tmp_path / svc["name"]
            svc_dir.mkdir()
            state_data = {
                "health": svc["health"],
                "completed_phases": svc["completed_phases"],
                "total_cost": svc["total_cost"],
                "summary": {
                    "success": svc["success"],
                    "test_passed": svc["test_passed"],
                    "test_total": svc["test_total"],
                    "convergence_ratio": svc["convergence_ratio"],
                },
            }
            _write_state_json(svc_dir, state_data)
            builder_configs.append({"cwd": str(svc_dir), "depth": "quick"})

        # Mock invoke_builder to skip actual subprocess but still parse
        # STATE.json via _state_to_builder_result
        async def _mock_invoke(
            cwd: Path,
            depth: str = "thorough",
            timeout_s: int = 1800,
            env: dict | None = None,
        ) -> BuilderResult:
            return _state_to_builder_result(
                service_name=Path(cwd).name,
                output_dir=Path(cwd),
                exit_code=0,
                stdout=f"Built {Path(cwd).name}",
                stderr="",
                duration_s=10.0,
            )

        with patch("src.run4.builder.invoke_builder", side_effect=_mock_invoke):
            results = await run_parallel_builders(
                builder_configs, max_concurrent=3, timeout_s=60
            )

        # Verify we got 3 results
        assert len(results) == 3

        # Build lookup by service_name
        by_name = {r.service_name: r for r in results}

        # Verify auth-service
        auth = by_name["auth-service"]
        assert auth.success is True
        assert auth.test_passed == 42
        assert auth.test_total == 50
        assert auth.convergence_ratio == 0.85
        assert auth.total_cost == 3.42
        assert auth.health == "green"
        assert auth.completed_phases == [
            "init",
            "scaffold",
            "implement",
            "test",
        ]

        # Verify order-service
        order = by_name["order-service"]
        assert order.success is True
        assert order.test_passed == 30
        assert order.test_total == 35
        assert order.convergence_ratio == 0.90
        assert order.total_cost == 2.80
        assert order.health == "green"

        # Verify notification-service (failed builder)
        notif = by_name["notification-service"]
        assert notif.success is False
        assert notif.test_passed == 5
        assert notif.test_total == 20
        assert notif.convergence_ratio == 0.25
        assert notif.health == "red"
        assert notif.completed_phases == ["init", "scaffold"]

    @pytest.mark.asyncio
    async def test_aggregate_cost_and_stats(self, tmp_path: Path) -> None:
        """Aggregated results allow computing total cost and pass rate."""
        services_data = [
            ("svc-a", True, 10, 10, 1.0, 2.0, "green"),
            ("svc-b", True, 8, 10, 0.8, 1.5, "yellow"),
            ("svc-c", False, 3, 10, 0.3, 0.5, "red"),
        ]
        builder_configs: list[dict[str, Any]] = []
        for name, success, tp, tt, cr, cost, health in services_data:
            svc_dir = tmp_path / name
            svc_dir.mkdir()
            _write_state_json(svc_dir, {
                "health": health,
                "completed_phases": [],
                "total_cost": cost,
                "summary": {
                    "success": success,
                    "test_passed": tp,
                    "test_total": tt,
                    "convergence_ratio": cr,
                },
            })
            builder_configs.append({"cwd": str(svc_dir)})

        async def _mock_invoke(
            cwd: Path, depth: str = "thorough",
            timeout_s: int = 1800, env: dict | None = None,
        ) -> BuilderResult:
            return _state_to_builder_result(
                service_name=Path(cwd).name,
                output_dir=Path(cwd),
                exit_code=0,
                duration_s=5.0,
            )

        with patch("src.run4.builder.invoke_builder", side_effect=_mock_invoke):
            results = await run_parallel_builders(
                builder_configs, max_concurrent=3
            )

        # Compute aggregates
        total_cost = sum(r.total_cost for r in results)
        total_passed = sum(r.test_passed for r in results)
        total_tests = sum(r.test_total for r in results)
        success_count = sum(1 for r in results if r.success)

        assert total_cost == pytest.approx(4.0, abs=0.01)
        assert total_passed == 21
        assert total_tests == 30
        assert success_count == 2


# ===================================================================
# SVC-020: Config YAML generation tests
# ===================================================================


class TestConfigYamlAllDepths:
    """SVC-020 -- Generate config for each depth level; verify
    ``_dict_to_config()`` loads without error."""

    @pytest.mark.parametrize(
        "depth", ["quick", "standard", "thorough", "exhaustive"]
    )
    def test_config_yaml_all_depths(
        self, tmp_path: Path, depth: str
    ) -> None:
        """generate_builder_config produces loadable YAML for every depth,
        parseable by Build 2's ``_dict_to_config()``."""
        from src.super_orchestrator.pipeline import _dict_to_config

        config_path = generate_builder_config(
            service_name="test-service",
            output_dir=tmp_path,
            depth=depth,
        )

        assert config_path.exists()
        assert config_path.name == "config.yaml"

        # Load and verify
        with open(config_path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)

        assert loaded["depth"] == depth
        assert loaded["service_name"] == "test-service"
        assert loaded["milestone"] == "build-test-service"
        assert loaded["e2e_testing"] is True
        assert loaded["post_orchestration_scans"] is True

        # SVC-020: verify _dict_to_config() parses without error
        parsed_config, unknown_keys = _dict_to_config(loaded)
        assert isinstance(parsed_config, dict)
        assert isinstance(unknown_keys, set)
        assert parsed_config["depth"] == depth
        assert parsed_config["e2e_testing"] is True
        # service_name is forward-compatible (not in _KNOWN_KEYS)
        assert "service_name" in unknown_keys


class TestConfigYamlWithContracts:
    """SVC-020 -- Generate config with contract-aware settings."""

    def test_config_yaml_with_contracts(self, tmp_path: Path) -> None:
        """Config includes contracts and MCP fields when provided."""
        contracts = [
            {
                "type": "openapi",
                "path": "contracts/auth-service.yaml",
                "service": "auth-service",
            },
            {
                "type": "asyncapi",
                "path": "contracts/order-events.yaml",
                "service": "order-service",
            },
        ]
        config_path = generate_builder_config(
            service_name="auth-service",
            output_dir=tmp_path,
            depth="thorough",
            contracts=contracts,
            mcp_enabled=True,
        )

        with open(config_path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)

        # MCP section present
        assert "mcp" in loaded
        assert loaded["mcp"]["enabled"] is True
        assert "servers" in loaded["mcp"]

        # Contracts section present
        assert "contracts" in loaded
        assert len(loaded["contracts"]) == 2
        assert loaded["contracts"][0]["type"] == "openapi"
        assert loaded["contracts"][1]["type"] == "asyncapi"

    def test_config_yaml_mcp_disabled(self, tmp_path: Path) -> None:
        """Config omits MCP section when mcp_enabled=False."""
        config_path = generate_builder_config(
            service_name="simple-service",
            output_dir=tmp_path,
            depth="quick",
            mcp_enabled=False,
        )

        with open(config_path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)

        assert "mcp" not in loaded


class TestConfigRoundtripPreservesFields:
    """SVC-020 -- Generate -> write -> read -> parse; all fields intact."""

    def test_config_roundtrip_preserves_fields(self, tmp_path: Path) -> None:
        """All fields survive YAML roundtrip and _dict_to_config() parsing."""
        from src.super_orchestrator.pipeline import _dict_to_config

        contracts = [
            {
                "type": "pact",
                "path": "contracts/pact.json",
                "service": "order-service",
            }
        ]
        config_path = generate_builder_config(
            service_name="order-service",
            output_dir=tmp_path,
            depth="standard",
            contracts=contracts,
            mcp_enabled=True,
        )

        # Read back
        with open(config_path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)

        # Write again to a second path
        roundtrip_path = tmp_path / "config_roundtrip.yaml"
        with open(roundtrip_path, "w", encoding="utf-8") as fh:
            yaml.dump(loaded, fh, default_flow_style=False, sort_keys=False)

        # Read second copy
        with open(roundtrip_path, "r", encoding="utf-8") as fh:
            reloaded = yaml.safe_load(fh)

        # Full equality
        assert reloaded == loaded

        # Verify individual fields
        assert reloaded["milestone"] == "build-order-service"
        assert reloaded["depth"] == "standard"
        assert reloaded["e2e_testing"] is True
        assert reloaded["post_orchestration_scans"] is True
        assert reloaded["service_name"] == "order-service"
        assert reloaded["mcp"]["enabled"] is True
        assert len(reloaded["contracts"]) == 1
        assert reloaded["contracts"][0]["type"] == "pact"
        assert reloaded["contracts"][0]["path"] == "contracts/pact.json"
        assert reloaded["contracts"][0]["service"] == "order-service"

        # Verify _dict_to_config() works on roundtripped config
        parsed_config, unknown_keys = _dict_to_config(reloaded)
        assert isinstance(parsed_config, dict)
        assert isinstance(unknown_keys, set)
        # Known keys preserved after roundtrip
        assert parsed_config["depth"] == "standard"
        assert parsed_config["e2e_testing"] is True
        assert parsed_config["mcp"]["enabled"] is True
        assert parsed_config["contracts"] == contracts
        # Forward-compatible unknown keys
        assert "service_name" in unknown_keys
