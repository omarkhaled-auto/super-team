"""Milestone 3 — Builder subprocess invocation tests.

REQ-016 through REQ-020, WIRE-013 through WIRE-016, WIRE-021.
Validates subprocess integration between Build 3 (Orchestration)
and Build 2 (Builder Fleet).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.build3_shared.models import ContractViolation
from src.run4.builder import (
    BuilderResult,
    feed_violations_to_builder,
    generate_builder_config,
    invoke_builder,
    parse_builder_state,
    run_parallel_builders,
    write_fix_instructions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_state_json(
    output_dir: Path,
    *,
    success: bool = True,
    test_passed: int = 42,
    test_total: int = 50,
    convergence_ratio: float = 0.84,
    total_cost: float = 1.23,
    health: str = "green",
    completed_phases: list[str] | None = None,
) -> Path:
    """Write a valid STATE.json into ``output_dir/.agent-team/``."""
    state_dir = output_dir / ".agent-team"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "STATE.json"
    data = {
        "run_id": "test-run-001",
        "health": health,
        "current_phase": "complete",
        "completed_phases": completed_phases or ["architect", "builders"],
        "total_cost": total_cost,
        "summary": {
            "success": success,
            "test_passed": test_passed,
            "test_total": test_total,
            "convergence_ratio": convergence_ratio,
        },
        "artifacts": {},
        "schema_version": 2,
    }
    state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return state_path


def _make_fake_builder_script(tmp_path: Path, exit_code: int = 0) -> Path:
    """Create a Python script that mimics ``agent_team`` CLI.

    Writes STATE.json and exits with the given exit code.
    """
    script = tmp_path / "_fake_builder.py"
    script.write_text(
        textwrap.dedent(f"""\
        import json, os, sys
        cwd = None
        depth = "thorough"
        args = sys.argv[1:]
        i = 0
        while i < len(args):
            if args[i] == "--cwd" and i + 1 < len(args):
                cwd = args[i + 1]
                i += 2
            elif args[i] == "--depth" and i + 1 < len(args):
                depth = args[i + 1]
                i += 2
            else:
                i += 1
        if cwd is None:
            cwd = os.getcwd()
        state_dir = os.path.join(cwd, ".agent-team")
        os.makedirs(state_dir, exist_ok=True)
        state = {{
            "run_id": "fake-run",
            "health": "green",
            "current_phase": "complete",
            "completed_phases": ["architect", "builders"],
            "total_cost": 0.50,
            "summary": {{
                "success": True,
                "test_passed": 10,
                "test_total": 10,
                "convergence_ratio": 1.0,
            }},
            "schema_version": 2,
        }}
        with open(os.path.join(state_dir, "STATE.json"), "w") as f:
            json.dump(state, f)
        print("Builder completed successfully")
        sys.exit({exit_code})
        """),
        encoding="utf-8",
    )
    return script


# ===================================================================
# REQ-016: test_builder_subprocess_invocation
# ===================================================================


class TestBuilderSubprocessInvocation:
    """REQ-016 -- Build 3 calls ``python -m agent_team --cwd {dir} --depth thorough``."""

    @pytest.mark.asyncio
    async def test_builder_subprocess_invocation(self, tmp_path: Path) -> None:
        """Builder starts, runs, exits 0; STATE.json written; stdout/stderr captured."""
        builder_dir = tmp_path / "auth-service"
        builder_dir.mkdir()
        script = _make_fake_builder_script(tmp_path)

        # Patch asyncio.create_subprocess_exec to run our fake script
        original_create = asyncio.create_subprocess_exec

        async def fake_create(*args: Any, **kwargs: Any) -> Any:
            # Replace `python -m agent_team` with our fake script
            new_args = [sys.executable, str(script)]
            # Forward --cwd and --depth args
            arg_list = list(args)
            for i, a in enumerate(arg_list):
                if a == "--cwd" or a == "--depth":
                    new_args.append(a)
                    if i + 1 < len(arg_list):
                        new_args.append(arg_list[i + 1])
            return await original_create(*new_args, **kwargs)

        with patch("src.run4.builder.asyncio.create_subprocess_exec", side_effect=fake_create):
            result = await invoke_builder(cwd=builder_dir, depth="thorough", timeout_s=30)

        assert isinstance(result, BuilderResult)
        assert result.exit_code == 0
        assert result.success is True
        assert result.test_passed == 10
        assert result.test_total == 10
        assert result.convergence_ratio == 1.0
        assert result.stdout  # stdout captured
        assert result.duration_s > 0

        # STATE.json was written
        state_path = builder_dir / ".agent-team" / "STATE.json"
        assert state_path.exists()

    @pytest.mark.asyncio
    async def test_builder_result_fields(self, tmp_path: Path) -> None:
        """BuilderResult has all required fields from REQUIREMENTS.md."""
        br = BuilderResult()
        required_fields = [
            "service_name", "success", "test_passed", "test_total",
            "convergence_ratio", "total_cost", "health",
            "completed_phases", "exit_code", "stdout", "stderr",
            "duration_s",
        ]
        for f in required_fields:
            assert hasattr(br, f), f"BuilderResult missing field: {f}"


# ===================================================================
# REQ-017: test_state_json_parsing_cross_build
# ===================================================================


class TestStateJsonParsingCrossBuild:
    """REQ-017 -- Verify Build 2's STATE.json summary is correctly parsed."""

    def test_state_json_parsing_cross_build(self, tmp_path: Path) -> None:
        """summary.success (bool), summary.test_passed (int),
        summary.test_total (int), summary.convergence_ratio (float),
        plus total_cost, health, completed_phases at top level."""
        _write_state_json(
            tmp_path,
            success=True,
            test_passed=42,
            test_total=50,
            convergence_ratio=0.84,
            total_cost=2.50,
            health="green",
            completed_phases=["architect", "builders", "integration"],
        )

        result = parse_builder_state(tmp_path)

        assert result["success"] is True
        assert isinstance(result["success"], bool)
        assert result["test_passed"] == 42
        assert isinstance(result["test_passed"], int)
        assert result["test_total"] == 50
        assert isinstance(result["test_total"], int)
        assert result["convergence_ratio"] == 0.84
        assert isinstance(result["convergence_ratio"], float)
        assert result["total_cost"] == 2.50
        assert isinstance(result["total_cost"], float)
        assert result["health"] == "green"
        assert result["completed_phases"] == ["architect", "builders", "integration"]

    def test_missing_state_json_returns_defaults(self, tmp_path: Path) -> None:
        """Missing STATE.json returns safe defaults."""
        result = parse_builder_state(tmp_path)
        assert result["success"] is False
        assert result["test_passed"] == 0
        assert result["test_total"] == 0
        assert result["convergence_ratio"] == 0.0
        assert result["total_cost"] == 0.0
        assert result["health"] == "unknown"
        assert result["completed_phases"] == []

    def test_corrupt_state_json(self, tmp_path: Path) -> None:
        """Corrupt JSON returns safe defaults."""
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir(parents=True)
        (state_dir / "STATE.json").write_text("not valid json{{{", encoding="utf-8")

        result = parse_builder_state(tmp_path)
        assert result["success"] is False


# ===================================================================
# REQ-018: test_config_generation_compatibility
# ===================================================================


class TestConfigGenerationCompatibility:
    """REQ-018 -- generate_builder_config() produces config.yaml."""

    def test_config_generation_compatibility(self, tmp_path: Path) -> None:
        """Generate config.yaml for all depth levels, verify YAML loadable
        and parseable by Build 2's ``_dict_to_config()``; verify returns
        ``tuple[AgentTeamConfig, set[str]]``."""
        import yaml

        from src.super_orchestrator.pipeline import _dict_to_config

        for depth in ("quick", "standard", "thorough", "exhaustive"):
            output_dir = tmp_path / f"service-{depth}"
            config_path = generate_builder_config(
                service_name=f"test-{depth}",
                output_dir=output_dir,
                depth=depth,
            )

            assert config_path.exists()
            assert config_path.name == "config.yaml"

            with open(config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)

            assert loaded["depth"] == depth
            assert loaded["service_name"] == f"test-{depth}"
            assert loaded["milestone"] == f"build-test-{depth}"
            assert loaded["e2e_testing"] is True

            # REQ-018: verify _dict_to_config() can parse the generated config
            # and returns tuple[AgentTeamConfig, set[str]]
            result = _dict_to_config(loaded)
            assert isinstance(result, tuple), (
                f"_dict_to_config must return a tuple, got {type(result)}"
            )
            assert len(result) == 2
            parsed_config, unknown_keys = result

            # First element is AgentTeamConfig (dict with known builder keys)
            assert isinstance(parsed_config, dict)
            assert parsed_config["depth"] == depth
            assert parsed_config["e2e_testing"] is True
            assert "milestone" in parsed_config

            # Second element is set[str] of unknown keys
            assert isinstance(unknown_keys, set)
            # service_name is NOT a known builder key, so it should appear here
            assert "service_name" in unknown_keys

    def test_config_with_contracts(self, tmp_path: Path) -> None:
        """Config with contract-aware settings has MCP fields and is
        parseable by ``_dict_to_config()``."""
        import yaml

        from src.super_orchestrator.pipeline import _dict_to_config

        contracts = [{"name": "auth-contract", "type": "openapi"}]
        config_path = generate_builder_config(
            service_name="auth-service",
            output_dir=tmp_path / "auth",
            contracts=contracts,
            mcp_enabled=True,
        )

        with open(config_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)

        assert "mcp" in loaded
        assert loaded["mcp"]["enabled"] is True
        assert loaded["contracts"] == contracts

        # Verify _dict_to_config() recognises mcp and contracts as known keys
        parsed_config, unknown_keys = _dict_to_config(loaded)
        assert "mcp" in parsed_config
        assert "contracts" in parsed_config
        assert parsed_config["mcp"]["enabled"] is True
        assert parsed_config["contracts"] == contracts

    def test_config_returns_path(self, tmp_path: Path) -> None:
        """Returns a Path to the generated config.yaml."""
        result = generate_builder_config(
            service_name="svc", output_dir=tmp_path / "svc",
        )
        assert isinstance(result, Path)
        assert result.suffix == ".yaml"


# ===================================================================
# REQ-019: test_parallel_builder_isolation
# ===================================================================


class TestParallelBuilderIsolation:
    """REQ-019 -- Semaphore-gated parallel builders, no cross-contamination."""

    @pytest.mark.asyncio
    async def test_parallel_builder_isolation(self, tmp_path: Path) -> None:
        """Launch 3 builders; each writes to own dir; no cross-contamination."""
        max_concurrent = 3
        concurrent_count = 0
        max_seen = 0
        lock = asyncio.Lock()

        configs = []
        for i in range(4):
            d = tmp_path / f"svc-{i}"
            d.mkdir()
            # Write a marker file unique to each builder
            (d / "marker.txt").write_text(f"builder-{i}", encoding="utf-8")
            configs.append({"cwd": str(d), "depth": "quick"})

        original_invoke = invoke_builder

        async def tracked_invoke(**kwargs: Any) -> BuilderResult:
            nonlocal concurrent_count, max_seen
            async with lock:
                concurrent_count += 1
                max_seen = max(max_seen, concurrent_count)

            # Simulate work
            await asyncio.sleep(0.05)

            # Write STATE.json
            cwd = Path(kwargs["cwd"])
            _write_state_json(cwd, success=True, test_passed=5, test_total=5)

            async with lock:
                concurrent_count -= 1

            from src.run4.builder import _state_to_builder_result
            return _state_to_builder_result(
                service_name=cwd.name, output_dir=cwd, exit_code=0
            )

        with patch("src.run4.builder.invoke_builder", side_effect=tracked_invoke):
            results = await run_parallel_builders(
                configs, max_concurrent=max_concurrent, timeout_s=30
            )

        assert len(results) == 4
        assert max_seen <= max_concurrent  # Semaphore enforced

        # Verify no cross-contamination: each directory has its own marker
        for i in range(4):
            d = tmp_path / f"svc-{i}"
            marker = (d / "marker.txt").read_text(encoding="utf-8")
            assert marker == f"builder-{i}", f"Cross-contamination in svc-{i}"

    @pytest.mark.asyncio
    async def test_semaphore_prevents_4th_concurrent(self, tmp_path: Path) -> None:
        """Verify Semaphore(3) blocks the 4th concurrent builder."""
        max_concurrent = 3
        peak_concurrent = 0
        current = 0
        lock = asyncio.Lock()

        configs = []
        for i in range(6):
            d = tmp_path / f"svc-{i}"
            d.mkdir()
            configs.append({"cwd": str(d)})

        async def slow_invoke(**kwargs: Any) -> BuilderResult:
            nonlocal current, peak_concurrent
            async with lock:
                current += 1
                peak_concurrent = max(peak_concurrent, current)
            await asyncio.sleep(0.1)
            cwd = Path(kwargs["cwd"])
            _write_state_json(cwd, success=True)
            async with lock:
                current -= 1
            from src.run4.builder import _state_to_builder_result
            return _state_to_builder_result(
                service_name=cwd.name, output_dir=cwd, exit_code=0
            )

        with patch("src.run4.builder.invoke_builder", side_effect=slow_invoke):
            results = await run_parallel_builders(
                configs, max_concurrent=max_concurrent, timeout_s=60
            )

        assert len(results) == 6
        assert peak_concurrent <= max_concurrent


# ===================================================================
# REQ-020: test_fix_pass_invocation
# ===================================================================


class TestFixPassInvocation:
    """REQ-020 -- Write FIX_INSTRUCTIONS.md, invoke builder quick, parse STATE.json."""

    @pytest.mark.asyncio
    async def test_fix_pass_invocation(self, tmp_path: Path) -> None:
        """Write FIX_INSTRUCTIONS.md with categorized violations; invoke quick mode;
        parse updated STATE.json; verify cost field updated."""
        builder_dir = tmp_path / "auth-service"
        builder_dir.mkdir()

        violations = [
            {
                "code": "FINDING-001",
                "component": "auth-service/main.py",
                "evidence": "GET /health returns 404",
                "action": "Add GET /health endpoint",
                "message": "Missing health endpoint",
                "priority": "P0",
            },
            {
                "code": "FINDING-002",
                "component": "order-service/routes.py",
                "evidence": "POST /orders response missing total field",
                "action": "Add total field to CreateOrderResponse",
                "message": "Schema violation",
                "priority": "P1",
            },
        ]

        # Mock invoke_builder to write STATE.json and return result
        async def mock_invoke(cwd: Path, depth: str = "thorough",
                              timeout_s: int = 600, env: Any = None) -> BuilderResult:
            _write_state_json(cwd, success=True, total_cost=0.75,
                              test_passed=8, test_total=10)
            from src.run4.builder import _state_to_builder_result
            return _state_to_builder_result(
                service_name=cwd.name, output_dir=cwd, exit_code=0
            )

        with patch("src.run4.builder.invoke_builder", side_effect=mock_invoke):
            result = await feed_violations_to_builder(
                cwd=builder_dir, violations=violations, timeout_s=30
            )

        # Verify FIX_INSTRUCTIONS.md was written
        fix_path = builder_dir / "FIX_INSTRUCTIONS.md"
        assert fix_path.exists()
        content = fix_path.read_text(encoding="utf-8")
        assert "P0" in content
        assert "FINDING-001" in content
        assert "FINDING-002" in content

        # Verify BuilderResult returned (not float)
        assert isinstance(result, BuilderResult)
        assert result.total_cost == 0.75
        assert result.success is True

    def test_write_fix_instructions_priority_format(self, tmp_path: Path) -> None:
        """write_fix_instructions uses P0/P1/P2 format, not severity-based."""
        violations = [
            {"code": "V-001", "message": "Critical issue",
             "component": "svc/a.py", "evidence": "broke", "action": "fix", "priority": "P0"},
            {"code": "V-002", "message": "Minor issue",
             "component": "svc/b.py", "evidence": "slow", "action": "optimize", "priority": "P2"},
        ]
        path = write_fix_instructions(tmp_path, violations)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "## Priority: P0 (Must Fix)" in content
        assert "## Priority: P2 (Nice to Have)" in content
        assert "V-001" in content
        assert "V-002" in content

    def test_write_fix_instructions_returns_path(self, tmp_path: Path) -> None:
        """write_fix_instructions returns Path to FIX_INSTRUCTIONS.md."""
        path = write_fix_instructions(tmp_path, [])
        assert isinstance(path, Path)
        assert path.name == "FIX_INSTRUCTIONS.md"


# ===================================================================
# REQ-020: test_fix_pass_invocation (ContractFixLoop variant)
# ===================================================================


class TestContractFixLoopReturnsBuilderResult:
    """REQ-020 -- ContractFixLoop.feed_violations_to_builder returns BuilderResult."""

    @pytest.mark.asyncio
    async def test_fix_loop_returns_builder_result(self, tmp_path: Path) -> None:
        """ContractFixLoop.feed_violations_to_builder returns BuilderResult not float."""
        from src.integrator.fix_loop import ContractFixLoop

        builder_dir = tmp_path / "fix-svc"
        builder_dir.mkdir()

        violations = [
            ContractViolation(
                code="CV-001", severity="critical", service="auth-service",
                endpoint="/health", message="Missing health endpoint",
                expected="200", actual="404",
            ),
        ]

        # Mock the subprocess to just write STATE.json
        async def fake_create(*args: Any, **kwargs: Any) -> MagicMock:
            # Write STATE.json
            _write_state_json(
                builder_dir, success=True, total_cost=0.30,
                test_passed=5, test_total=5
            )
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
            proc.wait = AsyncMock(return_value=0)
            proc.kill = MagicMock()
            return proc

        with patch("src.integrator.fix_loop.asyncio.create_subprocess_exec",
                    side_effect=fake_create):
            loop = ContractFixLoop(timeout=30)
            result = await loop.feed_violations_to_builder(
                service_id="auth-service",
                violations=violations,
                builder_dir=builder_dir,
            )

        assert isinstance(result, BuilderResult)
        assert result.success is True
        assert result.total_cost == 0.30


# ===================================================================
# WIRE-013: test_agent_teams_fallback_cli_unavailable
# ===================================================================


class TestAgentTeamsFallbackCLIUnavailable:
    """WIRE-013 -- agent_teams.enabled=True but CLI unavailable;
    create_execution_backend() returns CLIBackend with logged warning."""

    def test_agent_teams_fallback_cli_unavailable(self) -> None:
        """When agent_teams.enabled=True but Claude CLI is unavailable,
        create_execution_backend() returns CLIBackend with a logged warning."""
        from src.run4.execution_backend import (
            AgentTeamsConfig,
            CLIBackend,
            create_execution_backend,
        )

        config = AgentTeamsConfig(enabled=True, fallback_to_cli=True)

        # Mock Claude CLI as unavailable
        with patch("src.run4.execution_backend.shutil.which", return_value=None):
            with patch("src.run4.execution_backend.logger") as mock_logger:
                backend = create_execution_backend(agent_teams_config=config)

        assert isinstance(backend, CLIBackend)
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "falling back" in warning_msg.lower() or "fallback" in warning_msg.lower()

    def test_agent_teams_disabled_returns_cli_backend(self) -> None:
        """When agent_teams.enabled=False, always returns CLIBackend."""
        from src.run4.execution_backend import (
            AgentTeamsConfig,
            CLIBackend,
            create_execution_backend,
        )

        config = AgentTeamsConfig(enabled=False)
        backend = create_execution_backend(agent_teams_config=config)
        assert isinstance(backend, CLIBackend)


# ===================================================================
# WIRE-014: test_agent_teams_hard_failure_no_fallback
# ===================================================================


class TestAgentTeamsHardFailureNoFallback:
    """WIRE-014 -- agent_teams.enabled=True, fallback_to_cli=False, CLI unavailable;
    verify RuntimeError raised."""

    def test_agent_teams_hard_failure_no_fallback(self) -> None:
        """When agent_teams.enabled=True, fallback_to_cli=False, and CLI
        is unavailable, create_execution_backend() raises RuntimeError."""
        from src.run4.execution_backend import (
            AgentTeamsConfig,
            create_execution_backend,
        )

        config = AgentTeamsConfig(enabled=True, fallback_to_cli=False)

        with patch("src.run4.execution_backend.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="fallback_to_cli=False"):
                create_execution_backend(agent_teams_config=config)

    def test_fallback_to_cli_default_is_true(self) -> None:
        """AgentTeamsConfig.fallback_to_cli defaults to True."""
        from src.run4.execution_backend import AgentTeamsConfig

        config = AgentTeamsConfig(enabled=True)
        assert config.fallback_to_cli is True


# ===================================================================
# WIRE-015: test_builder_timeout_enforcement
# ===================================================================


class TestBuilderTimeoutEnforcement:
    """WIRE-015 -- Set builder_timeout_s=5; invoke on long task;
    verify proc.kill() + await proc.wait() in finally block."""

    @pytest.mark.asyncio
    async def test_builder_timeout_enforcement(self, tmp_path: Path) -> None:
        """Builder subprocess killed after timeout."""
        builder_dir = tmp_path / "timeout-svc"
        builder_dir.mkdir()

        kill_called = False
        wait_called = False

        class SlowProc:
            returncode = None

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(100)  # Simulate long-running builder
                return b"", b""

            def kill(self) -> None:
                nonlocal kill_called
                kill_called = True
                self.returncode = -9

            async def wait(self) -> int:
                nonlocal wait_called
                wait_called = True
                return -9

        async def slow_create(*args: Any, **kwargs: Any) -> SlowProc:
            return SlowProc()

        with patch("src.run4.builder.asyncio.create_subprocess_exec",
                    side_effect=slow_create):
            result = await invoke_builder(
                cwd=builder_dir, depth="thorough", timeout_s=1
            )

        assert kill_called, "proc.kill() should be called on timeout"
        assert wait_called, "proc.wait() should be called after kill"
        assert isinstance(result, BuilderResult)

    @pytest.mark.asyncio
    async def test_builder_timeout_enforcement_fix_loop(self, tmp_path: Path) -> None:
        """WIRE-015 -- ContractFixLoop.feed_violations_to_builder also enforces
        proc.kill() + await proc.wait() in its finally block (fix_loop.py:140-143)."""
        from src.integrator.fix_loop import ContractFixLoop

        builder_dir = tmp_path / "timeout-fix-svc"
        builder_dir.mkdir()

        kill_called = False
        wait_called = False

        class SlowProc:
            returncode = None

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(100)  # Simulate long-running builder
                return b"", b""

            def kill(self) -> None:
                nonlocal kill_called
                kill_called = True
                self.returncode = -9

            async def wait(self) -> int:
                nonlocal wait_called
                wait_called = True
                return -9

        async def slow_create(*args: Any, **kwargs: Any) -> SlowProc:
            return SlowProc()

        violations = [
            ContractViolation(
                code="CV-001", severity="critical", service="auth-service",
                endpoint="/health", message="Missing endpoint",
                expected="200", actual="404",
            ),
        ]

        with patch("src.integrator.fix_loop.asyncio.create_subprocess_exec",
                    side_effect=slow_create):
            loop = ContractFixLoop(timeout=1)
            result = await loop.feed_violations_to_builder(
                service_id="auth-service",
                violations=violations,
                builder_dir=builder_dir,
            )

        assert kill_called, "proc.kill() should be called on timeout in fix_loop"
        assert wait_called, "proc.wait() should be called after kill in fix_loop"
        assert isinstance(result, BuilderResult)

    @pytest.mark.asyncio
    async def test_builder_timeout_enforcement_with_timeout_s_5(self, tmp_path: Path) -> None:
        """WIRE-015 -- Verify proc.kill() + await proc.wait() in finally block
        when builder_timeout_s=5 (the specific scenario from REQUIREMENTS.md).

        This validates the timeout enforcement pattern used in both
        pipeline.py:705-708 and run4/builder.py:202-205."""
        kill_called = False
        wait_called = False

        class SlowProc:
            returncode = None

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(100)  # Simulate long-running builder
                return b"", b""

            def kill(self) -> None:
                nonlocal kill_called
                kill_called = True
                self.returncode = -9

            async def wait(self) -> int:
                nonlocal wait_called
                wait_called = True
                return -9

        async def slow_create(*args: Any, **kwargs: Any) -> SlowProc:
            return SlowProc()

        builder_dir = tmp_path / "pipeline-timeout-svc"
        builder_dir.mkdir()

        with patch("src.run4.builder.asyncio.create_subprocess_exec",
                    side_effect=slow_create):
            result = await invoke_builder(
                cwd=builder_dir, depth="thorough", timeout_s=5
            )

        assert kill_called, "proc.kill() should be called with builder_timeout_s=5"
        assert wait_called, "proc.wait() should be called after kill"
        assert isinstance(result, BuilderResult)


# ===================================================================
# WIRE-016: test_builder_environment_isolation
# ===================================================================


class TestBuilderEnvironmentIsolation:
    """WIRE-016 -- Builders inherit parent env; ANTHROPIC_API_KEY NOT passed."""

    @pytest.mark.asyncio
    async def test_builder_environment_isolation(self, tmp_path: Path) -> None:
        """Verify ANTHROPIC_API_KEY is filtered from builder environment (SEC-001)."""
        builder_dir = tmp_path / "env-svc"
        builder_dir.mkdir()
        _write_state_json(builder_dir, success=True)

        captured_env: dict[str, str] = {}

        async def capture_create(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal captured_env
            captured_env = kwargs.get("env", {}) or {}
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
            proc.wait = AsyncMock(return_value=0)
            proc.kill = MagicMock()
            return proc

        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "sk-secret-key",
            "OPENAI_API_KEY": "sk-openai-key",
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", os.environ.get("USERPROFILE", "")),
        }):
            with patch("src.run4.builder.asyncio.create_subprocess_exec",
                        side_effect=capture_create):
                await invoke_builder(cwd=builder_dir, depth="thorough", timeout_s=10)

        assert "ANTHROPIC_API_KEY" not in captured_env
        assert "OPENAI_API_KEY" not in captured_env
        # Verify PATH is still inherited
        assert "PATH" in captured_env


# ===================================================================
# WIRE-021: test_agent_teams_positive_path
# ===================================================================


class TestAgentTeamsPositivePath:
    """WIRE-021 -- agent_teams.enabled=True, CLI available;
    AgentTeamsBackend.execute_wave() completes with task state progression."""

    @pytest.mark.asyncio
    async def test_agent_teams_positive_path(self) -> None:
        """When agent_teams.enabled=True and CLI is available,
        create_execution_backend() returns AgentTeamsBackend and
        execute_wave() processes tasks with state progression:
        pending -> in_progress -> completed.

        Verifies TaskCreate, TaskUpdate, and SendMessage invocations.
        """
        from src.run4.execution_backend import (
            AgentTeamsBackend,
            AgentTeamsConfig,
            create_execution_backend,
        )

        config = AgentTeamsConfig(enabled=True, fallback_to_cli=True)

        # Mock Claude CLI as available
        with patch("src.run4.execution_backend.shutil.which", return_value="/usr/bin/claude"):
            backend = create_execution_backend(agent_teams_config=config)

        assert isinstance(backend, AgentTeamsBackend)

        # Execute a wave of tasks
        tasks = [
            {"id": "task-001", "service": "auth-service", "status": "pending"},
            {"id": "task-002", "service": "order-service", "status": "pending"},
        ]
        results = await backend.execute_wave(tasks)

        # Verify all tasks completed
        assert len(results) == 2
        for r in results:
            assert r["status"] == "completed"
            assert r["backend"] == "agent_teams"

        # Verify task state progression via internal tracking
        # TaskCreate invoked for each task
        assert len(backend._task_creates) == 2
        for tc in backend._task_creates:
            assert tc["action"] == "create"

        # TaskUpdate invoked twice per task (in_progress + completed)
        assert len(backend._task_updates) == 4
        statuses = [u["status"] for u in backend._task_updates]
        # Each task goes: in_progress, completed
        assert statuses == ["in_progress", "completed", "in_progress", "completed"]

        # SendMessage invoked for each task
        assert len(backend._send_messages) == 2
        for sm in backend._send_messages:
            assert sm["action"] == "send_message"

    @pytest.mark.asyncio
    async def test_cli_backend_execute_wave(self) -> None:
        """CLIBackend.execute_wave() processes tasks and marks as completed."""
        from src.run4.execution_backend import CLIBackend

        backend = CLIBackend(builder_dir="/tmp/test")
        tasks = [
            {"id": "task-001", "service": "auth-service", "status": "pending"},
        ]
        results = await backend.execute_wave(tasks)

        assert len(results) == 1
        assert results[0]["status"] == "completed"
        assert results[0]["backend"] == "cli"
