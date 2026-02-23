"""Builder invocation, configuration, and state parsing for Run 4.

Expanded from stub (Milestone 3). Implements:

- ``BuilderResult`` dataclass (REQ-016)
- ``invoke_builder()`` — subprocess invocation via asyncio (REQ-016)
- ``run_parallel_builders()`` — semaphore-gated concurrency (REQ-019)
- ``generate_builder_config()`` — config.yaml generation (REQ-018/SVC-020)
- ``parse_builder_state()`` — STATE.json extraction (REQ-017)
- ``feed_violations_to_builder()`` — fix-pass quick mode (REQ-020)
- ``write_fix_instructions()`` — FIX_INSTRUCTIONS.md generation (REQ-020)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Keys to filter from subprocess environments (SEC-001 compliance).
_FILTERED_ENV_KEYS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"}


@dataclass
class BuilderResult:
    """Result from a single builder execution.

    Maps all fields from the STATE.JSON summary contract between
    Build 2 and Build 3.
    """

    service_name: str = ""
    success: bool = False
    test_passed: int = 0
    test_total: int = 0
    convergence_ratio: float = 0.0
    total_cost: float = 0.0
    health: str = "unknown"
    completed_phases: list[str] = field(default_factory=list)
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0


# ---------------------------------------------------------------------------
# STATE.json parsing (REQ-017)
# ---------------------------------------------------------------------------


def parse_builder_state(output_dir: Path) -> dict:
    """Read ``.agent-team/STATE.json`` and extract a summary dict.

    Reads from the STATE.JSON contract:
    - ``summary.success`` (bool)
    - ``summary.test_passed`` (int)
    - ``summary.test_total`` (int)
    - ``summary.convergence_ratio`` (float)
    - ``total_cost`` (float, top-level)
    - ``health`` (str, top-level)
    - ``completed_phases`` (list[str], top-level)

    Args:
        output_dir: Root directory containing the ``.agent-team`` folder.

    Returns:
        Dict with ``success``, ``test_passed``, ``test_total``,
        ``convergence_ratio``, ``total_cost``, ``health``, and
        ``completed_phases`` keys.  Returns a failure dict if the
        state file is missing or unreadable.
    """
    state_path = output_dir / ".agent-team" / "STATE.json"
    result: dict[str, Any] = {
        "success": False,
        "test_passed": 0,
        "test_total": 0,
        "convergence_ratio": 0.0,
        "total_cost": 0.0,
        "health": "unknown",
        "completed_phases": [],
    }

    if not state_path.exists():
        logger.warning("Builder state not found: %s", state_path)
        return result

    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        summary = data.get("summary", {})
        result["success"] = summary.get("success", False)
        result["test_passed"] = int(summary.get("test_passed", 0))
        result["test_total"] = int(summary.get("test_total", 0))
        result["convergence_ratio"] = float(
            summary.get("convergence_ratio", 0.0)
        )
        result["total_cost"] = float(data.get("total_cost", 0.0))
        result["health"] = str(data.get("health", "unknown"))
        result["completed_phases"] = list(data.get("completed_phases", []))

        logger.info(
            "Builder state parsed: %d/%d tests, convergence=%.2f",
            result["test_passed"],
            result["test_total"],
            result["convergence_ratio"],
        )
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse builder state: %s", exc)

    return result


def _state_to_builder_result(
    service_name: str,
    output_dir: Path,
    exit_code: int = -1,
    stdout: str = "",
    stderr: str = "",
    duration_s: float = 0.0,
) -> BuilderResult:
    """Parse STATE.json and return a ``BuilderResult``."""
    state = parse_builder_state(output_dir)
    return BuilderResult(
        service_name=service_name,
        success=state["success"],
        test_passed=state["test_passed"],
        test_total=state["test_total"],
        convergence_ratio=state["convergence_ratio"],
        total_cost=state["total_cost"],
        health=state["health"],
        completed_phases=state["completed_phases"],
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_s=duration_s,
    )


# ---------------------------------------------------------------------------
# Subprocess invocation (REQ-016)
# ---------------------------------------------------------------------------


def _filtered_env() -> dict[str, str]:
    """Return ``os.environ`` minus secret keys (SEC-001)."""
    return {k: v for k, v in os.environ.items() if k not in _FILTERED_ENV_KEYS}


async def invoke_builder(
    cwd: Path,
    depth: str = "thorough",
    timeout_s: int = 1800,
    env: dict[str, str] | None = None,
) -> BuilderResult:
    """Invoke ``python -m agent_team --cwd {cwd} --depth {depth}``.

    Uses ``asyncio.create_subprocess_exec``.  Captures stdout/stderr.
    Returns a :class:`BuilderResult` parsed from STATE.json.
    """
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)

    proc_env = env if env is not None else _filtered_env()
    start = time.monotonic()
    proc: asyncio.subprocess.Process | None = None
    stdout_bytes = b""
    stderr_bytes = b""
    exit_code = -1

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "agent_team",
            "--cwd",
            str(cwd),
            "--depth",
            depth,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=proc_env,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_s
        )
        exit_code = proc.returncode or 0
    except asyncio.TimeoutError:
        logger.warning(
            "Builder subprocess timed out after %ds for %s", timeout_s, cwd
        )
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()

    duration = time.monotonic() - start
    stdout_text = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
    stderr_text = stderr_bytes.decode(errors="replace") if stderr_bytes else ""
    service_name = cwd.name

    return _state_to_builder_result(
        service_name=service_name,
        output_dir=cwd,
        exit_code=exit_code,
        stdout=stdout_text,
        stderr=stderr_text,
        duration_s=duration,
    )


# ---------------------------------------------------------------------------
# Parallel builder execution (REQ-019)
# ---------------------------------------------------------------------------


async def run_parallel_builders(
    builder_configs: list[dict[str, Any]],
    max_concurrent: int = 3,
    timeout_s: int = 1800,
) -> list[BuilderResult]:
    """Launch builders with ``asyncio.Semaphore(max_concurrent)``.

    Each builder writes to its own directory.  Returns list of
    :class:`BuilderResult`.

    Each dict in *builder_configs* must contain at least ``cwd`` (str or
    Path).  Optional keys: ``depth`` (str), ``env`` (dict).
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _run_one(cfg: dict[str, Any]) -> BuilderResult:
        async with semaphore:
            return await invoke_builder(
                cwd=Path(cfg["cwd"]),
                depth=cfg.get("depth", "thorough"),
                timeout_s=timeout_s,
                env=cfg.get("env"),
            )

    tasks = [_run_one(cfg) for cfg in builder_configs]
    return list(await asyncio.gather(*tasks))


# ---------------------------------------------------------------------------
# Config generation (REQ-018 / SVC-020)
# ---------------------------------------------------------------------------


def generate_builder_config(
    service_name: str,
    output_dir: Path,
    depth: str = "thorough",
    contracts: list[dict[str, Any]] | None = None,
    mcp_enabled: bool = True,
) -> Path:
    """Generate ``config.yaml`` compatible with Build 2's ``_dict_to_config()``.

    Returns the path to the generated ``config.yaml``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config_dict: dict[str, Any] = {
        "milestone": f"build-{service_name}",
        "depth": depth,
        "e2e_testing": True,
        "post_orchestration_scans": True,
        "service_name": service_name,
    }

    if mcp_enabled:
        config_dict["mcp"] = {
            "enabled": True,
            "servers": {},
        }

    if contracts:
        config_dict["contracts"] = contracts

    config_path = output_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(config_dict, fh, default_flow_style=False, sort_keys=False)

    logger.info("Generated builder config: %s", config_path)
    return config_path


# ---------------------------------------------------------------------------
# FIX_INSTRUCTIONS.md generation (REQ-020)
# ---------------------------------------------------------------------------

_PRIORITY_LABELS = {
    "P0": "P0 (Must Fix)",
    "P1": "P1 (Should Fix)",
    "P2": "P2 (Nice to Have)",
}


def write_fix_instructions(
    cwd: Path,
    violations: list[dict[str, Any]],
    priority_order: list[str] | None = None,
    graph_rag_context: str = "",
) -> Path:
    """Generate ``FIX_INSTRUCTIONS.md`` with categorized violations.

    Violations are grouped by a ``priority`` field (defaulting to ``"P1"``
    if absent).  The file follows the priority-based format specified in
    REQUIREMENTS.md.

    Args:
        cwd: Directory in which to write ``FIX_INSTRUCTIONS.md``.
        violations: List of violation dicts.  Each should have at least
            ``code``, ``component``, ``evidence``, ``action``, and
            optionally ``priority``.
        priority_order: Priority tiers to emit, in order.
        graph_rag_context: Optional cross-service dependency context from
            Graph RAG to append to the instructions.

    Returns:
        Path to the written ``FIX_INSTRUCTIONS.md``.
    """
    if priority_order is None:
        priority_order = ["P0", "P1", "P2"]

    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)

    # Bucket violations by priority
    buckets: dict[str, list[dict[str, Any]]] = {p: [] for p in priority_order}
    for v in violations:
        prio = v.get("priority", "P1")
        if prio in buckets:
            buckets[prio].append(v)
        else:
            buckets.setdefault(prio, []).append(v)

    lines: list[str] = ["# Fix Instructions", ""]

    finding_num = 0
    for prio in priority_order:
        group = buckets.get(prio, [])
        if not group:
            continue
        label = _PRIORITY_LABELS.get(prio, prio)
        lines.append(f"## Priority: {label}")
        lines.append("")
        for v in group:
            finding_num += 1
            code = v.get("code", f"FINDING-{finding_num:03d}")
            component = v.get("component", "unknown")
            evidence = v.get("evidence", "")
            action = v.get("action", "")
            lines.append(f"### {code}: {v.get('message', code)}")
            lines.append(f"- **Component**: {component}")
            if evidence:
                lines.append(f"- **Evidence**: {evidence}")
            if action:
                lines.append(f"- **Action**: {action}")
            lines.append("")

    if graph_rag_context:
        lines.append("\n## Cross-Service Dependency Context\n")
        lines.append("The following context describes how other services depend on this one.")
        lines.append("Consider cross-service impact when applying fixes.\n")
        lines.append(graph_rag_context)

    instructions_path = cwd / "FIX_INSTRUCTIONS.md"
    instructions_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s (%d violations)", instructions_path, len(violations))
    return instructions_path


# ---------------------------------------------------------------------------
# Fix pass builder invocation (REQ-020)
# ---------------------------------------------------------------------------


async def feed_violations_to_builder(
    cwd: Path,
    violations: list[dict[str, Any]],
    timeout_s: int = 600,
) -> BuilderResult:
    """Write ``FIX_INSTRUCTIONS.md`` to *cwd*, invoke builder in quick mode.

    Returns a :class:`BuilderResult` parsed from the updated STATE.json.
    """
    write_fix_instructions(cwd, violations)
    return await invoke_builder(cwd=cwd, depth="quick", timeout_s=timeout_s)
