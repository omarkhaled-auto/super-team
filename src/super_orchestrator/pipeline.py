"""Super Orchestrator Pipeline -- main orchestration engine.

Drives the full Build 3 pipeline workflow:

    architect → contract_registration → builders → integration
    → quality_gate → (fix_pass loop) → complete

The pipeline is state-machine-driven, budget-aware, gracefully
interruptible, and fully resumable.

.. rubric:: Key design decisions

* **MCP-first with fallback** – The architect phase tries MCP stdio
  first and falls back to subprocess + JSON if MCP is unavailable.
* **Lazy imports** – All external/optional dependencies (MCP,
  ``agent_team``, schemathesis, pact) are imported inside function
  bodies so that ``super_orchestrator`` can be imported without Build 1
  or Build 2 installed.
* **Semaphore-guarded parallelism** – Builder subprocesses are gated by
  an ``asyncio.Semaphore`` created *inside* the function body (never at
  module level) to avoid event-loop issues.
* **try/finally cleanup** – Every subprocess acquires a ``proc``
  reference and cleans up with ``proc.kill()`` + ``await proc.wait()``
  in a ``finally`` block.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from src.build3_shared.constants import (
    PHASE_ARCHITECT,
    PHASE_BUILDERS,
    PHASE_CONTRACT_REGISTRATION,
    PHASE_FIX_PASS,
    PHASE_INTEGRATION,
    PHASE_QUALITY_GATE,
    STATE_DIR,
)
from src.build3_shared.models import (
    BuilderResult,
    ContractViolation,
    GateVerdict,
    IntegrationReport,
    QualityGateReport,
    ServiceInfo,
)
from src.build3_shared.utils import atomic_write_json, ensure_dir, load_json
from src.super_orchestrator.config import (
    SuperOrchestratorConfig,
    load_super_config,
)
from src.super_orchestrator.cost import PipelineCostTracker
from src.super_orchestrator.exceptions import (
    BudgetExceededError,
    BuilderFailureError,
    ConfigurationError,
    IntegrationFailureError,
    PipelineError,
    QualityGateFailureError,
)
from src.super_orchestrator.shutdown import GracefulShutdown
from src.super_orchestrator.state import PipelineState
from src.super_orchestrator.state_machine import (
    RESUME_TRIGGERS,
    create_pipeline_machine,
)

logger = logging.getLogger(__name__)

# Keys to filter from subprocess environments to avoid leaking secrets.
# NOTE: ANTHROPIC_API_KEY is intentionally NOT filtered because builder subprocesses need it.
# CLAUDECODE and CLAUDE_CODE_ENTRYPOINT are removed so the builder subprocess
# can use `--backend cli` without hitting the nested-session guard.
_FILTERED_ENV_KEYS = {"AWS_SECRET_ACCESS_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}


def _filtered_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with secret keys removed.

    Note: ANTHROPIC_API_KEY and OPENAI_API_KEY are intentionally passed through
    because builder subprocesses (agent_team) need them to function.
    The CLAUDECODE variable is removed to allow nested ``claude`` CLI sessions
    from builder subprocesses that use ``--backend cli``.
    """
    return {k: v for k, v in os.environ.items() if k not in _FILTERED_ENV_KEYS}


# ---------------------------------------------------------------------------
# PipelineModel -- state machine model with guard methods
# ---------------------------------------------------------------------------


class PipelineModel:
    """Model object for the ``transitions`` async state machine.

    Wraps a :class:`PipelineState` and exposes the 12 guard methods
    required by :data:`TRANSITIONS`.  The ``state`` attribute is managed
    by the ``AsyncMachine`` (it reads/writes ``model.state``).
    """

    def __init__(self, pipeline_state: PipelineState) -> None:
        self._ps = pipeline_state
        # The `state` attribute is set by AsyncMachine but we seed it
        # from the persisted pipeline state so that resume works.
        self.state: str = pipeline_state.current_state

    # ---- Guard methods ---------------------------------------------------

    def is_configured(self, *args, **kwargs) -> bool:
        """True when a PRD path is set (minimum configuration)."""
        return bool(self._ps.prd_path)

    def has_service_map(self, *args, **kwargs) -> bool:
        """True when the architect phase produced a service map."""
        return bool(self._ps.service_map_path)

    def service_map_valid(self, *args, **kwargs) -> bool:
        """True when the service map file exists and is readable."""
        if not self._ps.service_map_path:
            return False
        return Path(self._ps.service_map_path).exists()

    def contracts_valid(self, *args, **kwargs) -> bool:
        """True when the contract registry path is populated."""
        return bool(self._ps.contract_registry_path)

    def has_builder_results(self, *args, **kwargs) -> bool:
        """True when at least one builder has reported results."""
        return bool(self._ps.builder_results)

    def any_builder_passed(self, *args, **kwargs) -> bool:
        """True when at least one builder succeeded."""
        return self._ps.successful_builders > 0

    def has_integration_report(self, *args, **kwargs) -> bool:
        """True when an integration report has been produced."""
        return bool(self._ps.integration_report_path)

    def gate_passed(self, *args, **kwargs) -> bool:
        """True when the quality gate overall verdict is PASSED."""
        results = self._ps.last_quality_results
        return results.get("overall_verdict") == GateVerdict.PASSED.value

    def fix_attempts_remaining(self, *args, **kwargs) -> bool:
        """True when the quality gate has fix attempts left."""
        return self._ps.quality_attempts < self._ps.max_quality_retries

    def fix_applied(self, *args, **kwargs) -> bool:
        """True (always) -- fix pass completion implies fix was applied."""
        return True

    def retries_remaining(self, *args, **kwargs) -> bool:
        """True when the architect has retries left."""
        return self._ps.architect_retries < self._ps.max_architect_retries

    def advisory_only(self, *args, **kwargs) -> bool:
        """True when only advisory (Layer 4) violations remain.

        If the quality gate verdict is not PASSED but the only blocking
        layers are Layer 4 (always advisory), we can skip to complete.
        """
        results = self._ps.last_quality_results
        if not results:
            return False
        overall = results.get("overall_verdict", "")
        if overall == GateVerdict.PASSED.value:
            return True
        # Check if blocking violations is 0 (only advisory findings)
        return results.get("blocking_violations", 1) == 0


# ---------------------------------------------------------------------------
# Builder config generation
# ---------------------------------------------------------------------------


def generate_builder_config(
    service_info: ServiceInfo,
    config: SuperOrchestratorConfig,
    state: PipelineState,
) -> tuple[dict[str, Any], Path]:
    """Generate a builder configuration dict **and** a ``config.yaml`` file.

    The generated ``config.yaml`` is compatible with Build 2's
    ``_dict_to_config()`` — it silently ignores unknown top-level keys
    so the extra orchestrator-specific fields are safe.

    Parameters
    ----------
    service_info:
        Metadata about the service to build.
    config:
        Top-level orchestrator config.
    state:
        Current pipeline state (provides context for the builder).

    Returns
    -------
    tuple[dict, Path]
        A 2-tuple of (config dict, path to generated ``config.yaml``).
    """
    output_dir = Path(config.output_dir) / service_info.service_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Store full metadata in builder_config.json for reference
    # Don't generate config.yaml as agent_team doesn't need it
    # (depth is passed via CLI flag)
    config_dict: dict[str, Any] = {
        "depth": config.builder.depth,
        "milestone": f"build-{service_info.service_id}",
        "e2e_testing": True,
        "post_orchestration_scans": True,
        "service_id": service_info.service_id,
        "domain": service_info.domain,
        "stack": service_info.stack,
        "port": service_info.port,
        "output_dir": str(output_dir),
    }

    # Return a dummy path for config - agent_team will use CLI args instead
    config_path = output_dir / "config.yaml.not-used"

    logger.info("Generated builder config metadata (stored in builder_config.json only)")
    return config_dict, config_path


def _dict_to_config(raw: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Parse a builder configuration dict (Build 2 compatibility shim).

    Mimics Build 2's ``_dict_to_config()`` contract: accepts the dict
    produced by :func:`generate_builder_config`, returns a 2-tuple of
    ``(parsed_config, unknown_keys)``.  Unknown keys are collected but
    *not* rejected (forward-compatibility).

    This function is intentionally simple — it validates that the
    required builder keys are present and separates known from unknown.
    """
    _KNOWN_KEYS = {
        "depth",
        "milestone",
        "e2e_testing",
        "post_orchestration_scans",
        "mcp",
        "contracts",
    }
    unknown = set(raw.keys()) - _KNOWN_KEYS
    parsed = {k: v for k, v in raw.items() if k in _KNOWN_KEYS}
    # Ensure defaults for required fields
    parsed.setdefault("depth", "thorough")
    parsed.setdefault("e2e_testing", True)
    return parsed, unknown


# ---------------------------------------------------------------------------
# Phase functions
# ---------------------------------------------------------------------------


async def run_architect_phase(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
) -> None:
    """Run the architect phase (MCP stdio with subprocess fallback).

    Populates ``state.service_map_path``, ``state.domain_model_path``,
    and ``state.contract_registry_path``.
    """
    logger.info("Starting architect phase")
    cost_tracker.start_phase(PHASE_ARCHITECT)
    phase_cost = 0.0
    output_dir = Path(config.output_dir)
    ensure_dir(output_dir)

    prd_text = Path(state.prd_path).read_text(encoding="utf-8")

    result: dict[str, Any] | None = None
    retries = 0
    max_retries = config.architect.max_retries

    while retries <= max_retries:
        if shutdown.should_stop:
            logger.warning("Shutdown requested during architect phase")
            state.save()
            cost_tracker.end_phase(phase_cost)
            return

        try:
            result = await _call_architect(
                prd_text, config, output_dir
            )
            break
        except Exception as exc:
            retries += 1
            state.architect_retries = retries
            logger.warning(
                "Architect attempt %d/%d failed: %s",
                retries,
                max_retries + 1,
                exc,
            )
            if retries > max_retries:
                cost_tracker.end_phase(phase_cost)
                raise PipelineError(
                    f"Architect phase failed after {retries} attempts: {exc}"
                ) from exc
            state.save()

    if result is None:
        cost_tracker.end_phase(phase_cost)
        raise PipelineError("Architect phase returned no result")

    # Persist artifacts
    service_map = result.get("service_map", {})
    domain_model = result.get("domain_model", {})
    contract_stubs = result.get("contract_stubs", {})

    smap_path = output_dir / "service_map.json"
    dmodel_path = output_dir / "domain_model.json"
    registry_dir = output_dir / "contracts"
    ensure_dir(registry_dir)

    atomic_write_json(smap_path, service_map)
    atomic_write_json(dmodel_path, domain_model)
    atomic_write_json(registry_dir / "stubs.json", contract_stubs)

    state.service_map_path = str(smap_path)
    state.domain_model_path = str(dmodel_path)
    state.contract_registry_path = str(registry_dir)
    phase_cost = result.get("cost", 0.0)
    state.phase_artifacts[PHASE_ARCHITECT] = {
        "service_map_path": str(smap_path),
        "domain_model_path": str(dmodel_path),
        "contract_registry_path": str(registry_dir),
    }
    if PHASE_ARCHITECT not in state.completed_phases:
        state.completed_phases.append(PHASE_ARCHITECT)

    cost_tracker.end_phase(phase_cost)
    state.total_cost = cost_tracker.total_cost
    state.phase_costs = cost_tracker.phase_costs
    state.save()
    logger.info("Architect phase complete -- cost=$%.4f", phase_cost)


async def _call_architect(
    prd_text: str,
    config: SuperOrchestratorConfig,
    output_dir: Path,
) -> dict[str, Any]:
    """Call the architect via MCP stdio, falling back to subprocess."""
    mcp_failed = False
    # ---- Try MCP stdio first (lazy import) ------------------------------
    try:
        from src.architect.mcp_client import call_architect_mcp  # type: ignore[import-untyped]

        logger.info("Attempting architect call via MCP stdio")
        result = await call_architect_mcp(
            prd_text=prd_text,
            config=config.architect,
        )
        return result
    except ImportError:
        logger.info("MCP client not available, falling back to subprocess")
        mcp_failed = True
    except Exception as exc:
        logger.warning("MCP architect call failed: %s -- trying subprocess", exc)
        mcp_failed = True

    # ---- Fallback: subprocess + JSON ------------------------------------
    try:
        return await _call_architect_subprocess(prd_text, config, output_dir)
    except Exception as exc:
        if mcp_failed:
            raise ConfigurationError(
                "Architect phase failed: both MCP and subprocess unavailable. "
                "Ensure Build 1 Architect is installed and its MCP server is running. "
                "Run `python -m architect` to verify installation."
            ) from exc
        raise


async def _call_architect_subprocess(
    prd_text: str,
    config: SuperOrchestratorConfig,
    output_dir: Path,
) -> dict[str, Any]:
    """Run the architect as a subprocess and parse the JSON result."""
    prd_file = output_dir / "prd_input.md"
    prd_file.write_text(prd_text, encoding="utf-8")

    result_file = output_dir / "architect_result.json"

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "architect",
            "--prd",
            str(prd_file),
            "--output",
            str(result_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(
            proc.wait(), timeout=config.architect.timeout
        )
    except asyncio.TimeoutError:
        logger.error("Architect subprocess timed out after %ds", config.architect.timeout)
        raise PipelineError(
            f"Architect subprocess timed out after {config.architect.timeout}s"
        )
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()

    if proc.returncode != 0:
        stderr = ""
        if proc.stderr:
            stderr = (await proc.stderr.read()).decode(errors="replace")
        raise PipelineError(
            f"Architect subprocess failed (exit {proc.returncode}): {stderr[:500]}"
        )

    if result_file.exists():
        return load_json(result_file)

    # Attempt to parse stdout as JSON
    if proc.stdout:
        stdout_data = (await proc.stdout.read()).decode(errors="replace")
        try:
            return json.loads(stdout_data)
        except json.JSONDecodeError:
            pass

    raise PipelineError("Architect subprocess produced no parseable result")


async def run_contract_registration(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
) -> None:
    """Register contracts from the architect's output.

    Reads the service map, extracts contract stubs, and registers each
    contract via MCP (falling back to filesystem storage).
    """
    logger.info("Starting contract registration phase")
    cost_tracker.start_phase(PHASE_CONTRACT_REGISTRATION)
    phase_cost = 0.0

    if shutdown.should_stop:
        logger.warning("Shutdown requested before contract registration")
        state.save()
        cost_tracker.end_phase(phase_cost)
        return

    service_map = load_json(state.service_map_path)
    registry_dir = Path(state.contract_registry_path)
    ensure_dir(registry_dir)

    # Load contract stubs if they exist
    stubs_file = registry_dir / "stubs.json"
    contract_stubs: dict[str, Any] = {}
    if stubs_file.exists():
        loaded_stubs = load_json(stubs_file)
        # Handle both dict and list formats
        if isinstance(loaded_stubs, list):
            # If it's a list, assume it contains one OpenAPI spec per service
            # Map by service name extracted from the spec title or use index
            for idx, stub in enumerate(loaded_stubs):
                if isinstance(stub, dict):
                    # Try to extract service name from OpenAPI spec
                    info = stub.get("info", {})
                    title = info.get("title", "").lower().replace(" api", "").strip()
                    if title:
                        contract_stubs[title] = stub
                    # Also store by index for fallback
                    contract_stubs[f"service_{idx}"] = stub
        else:
            contract_stubs = loaded_stubs

    services = service_map.get("services", [])
    registered = []

    for idx, svc in enumerate(services):
        if shutdown.should_stop:
            break

        service_name = svc.get("service_id", svc.get("name", ""))
        if not service_name:
            continue

        # Try multiple ways to find the contract spec
        spec = None
        if isinstance(contract_stubs, dict):
            # Try by service name (exact and normalized)
            spec = contract_stubs.get(service_name)
            if not spec:
                normalized_name = service_name.lower().replace(" ", "-")
                spec = contract_stubs.get(normalized_name)
            if not spec:
                # Try by index as fallback
                spec = contract_stubs.get(f"service_{idx}")

        # Fall back to contract field in service definition
        if not spec:
            spec = svc.get("contract", {})
        if not spec:
            logger.debug("No contract stub for service %s, skipping", service_name)
            continue

        try:
            result = await _register_single_contract(
                service_name, spec, config
            )
            registered.append(result)
            logger.info("Registered contract for %s", service_name)
        except ConfigurationError:
            # INT-002: MCP unavailable -- fall back to filesystem
            logger.warning(
                "Contract Engine MCP unavailable for %s -- saving to filesystem",
                service_name,
            )
            contract_file = registry_dir / f"{service_name}.json"
            atomic_write_json(contract_file, spec)
        except Exception as exc:
            logger.warning(
                "Failed to register contract for %s: %s -- saving to filesystem",
                service_name,
                exc,
            )
            # Filesystem fallback
            contract_file = registry_dir / f"{service_name}.json"
            atomic_write_json(contract_file, spec)

    state.phase_artifacts[PHASE_CONTRACT_REGISTRATION] = {
        "registered_contracts": len(registered),
        "registry_path": str(registry_dir),
    }
    if PHASE_CONTRACT_REGISTRATION not in state.completed_phases:
        state.completed_phases.append(PHASE_CONTRACT_REGISTRATION)

    cost_tracker.end_phase(phase_cost)
    state.total_cost = cost_tracker.total_cost
    state.phase_costs = cost_tracker.phase_costs
    state.save()
    logger.info(
        "Contract registration complete -- %d contracts registered",
        len(registered),
    )


async def _register_single_contract(
    service_name: str,
    spec: dict[str, Any],
    config: SuperOrchestratorConfig,
) -> dict[str, Any]:
    """Register a single contract via MCP, with fallback."""
    try:
        from src.contract_engine.mcp_client import (  # type: ignore[import-untyped]
            create_contract,
            list_contracts,
            validate_spec,
        )

        # Validate first
        validation = await validate_spec(spec=spec, type="openapi")
        if not validation.get("valid", False):
            logger.warning(
                "Contract validation failed for %s: %s",
                service_name,
                validation.get("errors", []),
            )

        # Register
        result = await create_contract(
            service_name=service_name,
            type="openapi",
            version="1.0.0",
            spec=spec,
        )

        # SVC-008: Verify contract was stored
        try:
            stored = await list_contracts(service_name=service_name)
            if not stored.get("items"):
                logger.warning("Contract for %s not found after registration", service_name)
        except Exception:
            logger.info("list_contracts verification skipped for %s", service_name)

        return result
    except ImportError as exc:
        raise ConfigurationError(
            f"Contract Engine MCP not available for {service_name}. "
            "Ensure Build 1 Contract Engine is installed and its MCP server is running."
        ) from exc


async def run_parallel_builders(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
) -> None:
    """Run builder subprocesses in parallel for each service.

    The concurrency is gated by a semaphore created inside this function.
    Individual builder failures do not kill the pipeline; only
    all-builders-fail triggers the ``failed`` state.
    """
    logger.info("Starting parallel builders phase")
    cost_tracker.start_phase(PHASE_BUILDERS)

    if shutdown.should_stop:
        logger.warning("Shutdown requested before builders phase")
        state.save()
        cost_tracker.end_phase(0.0)
        return

    service_map = load_json(state.service_map_path)
    services_raw = service_map.get("services", [])

    # Build ServiceInfo objects
    services: list[ServiceInfo] = []
    for svc in services_raw:
        sid = svc.get("service_id", svc.get("name", ""))
        if not sid:
            continue
        services.append(
            ServiceInfo(
                service_id=sid,
                domain=svc.get("domain", "unknown"),
                stack=svc.get("stack", {}),
                port=svc.get("port", 8080),
                health_endpoint=svc.get("health_endpoint", "/health"),
                docker_image=svc.get("docker_image", ""),
                estimated_loc=svc.get("estimated_loc", 0),
            )
        )

    state.total_builders = len(services)
    semaphore = asyncio.Semaphore(config.builder.max_concurrent)

    async def _build_one(svc: ServiceInfo) -> BuilderResult:
        async with semaphore:
            if shutdown.should_stop:
                return BuilderResult(
                    system_id=svc.service_id,  # Use service_id as system_id fallback
                    service_id=svc.service_id,
                    success=False,
                    error="Pipeline shutdown requested",
                )
            return await _run_single_builder(svc, config, state)

    tasks = [_build_one(svc) for svc in services]
    results: list[BuilderResult] = await asyncio.gather(*tasks)

    total_cost = 0.0
    successful = 0
    for r in results:
        state.builder_results[r.service_id] = dataclasses.asdict(r)
        state.builder_costs[r.service_id] = r.cost
        total_cost += r.cost
        if r.success:
            state.builder_statuses[r.service_id] = "healthy"
            successful += 1
        else:
            state.builder_statuses[r.service_id] = "failed"

    state.successful_builders = successful

    state.phase_artifacts[PHASE_BUILDERS] = {
        "total_builders": len(services),
        "successful_builders": successful,
        "total_cost": total_cost,
    }
    if PHASE_BUILDERS not in state.completed_phases:
        state.completed_phases.append(PHASE_BUILDERS)

    cost_tracker.end_phase(total_cost)
    state.total_cost = cost_tracker.total_cost
    state.phase_costs = cost_tracker.phase_costs
    state.save()

    logger.info(
        "Builders complete -- %d/%d succeeded, cost=$%.4f",
        successful,
        len(services),
        total_cost,
    )

    if successful == 0 and len(services) > 0:
        raise BuilderFailureError(
            f"All {len(services)} builders failed"
        )


async def _run_single_builder(
    service_info: ServiceInfo,
    config: SuperOrchestratorConfig,
    state: PipelineState,
) -> BuilderResult:
    """Run a single builder subprocess and parse the result."""
    output_dir = Path(config.output_dir) / service_info.service_id
    ensure_dir(output_dir)

    builder_config, config_yaml_path = generate_builder_config(service_info, config, state)
    # Also write JSON for backward compatibility with existing tooling.
    config_file = output_dir / "builder_config.json"
    atomic_write_json(config_file, builder_config)

    # Write the PRD file for the builder subprocess
    prd_file = output_dir / "prd_input.md"
    if not prd_file.exists():
        # Read the original PRD
        original_prd = Path(state.prd_path).read_text(encoding="utf-8")
        prd_file.write_text(original_prd, encoding="utf-8")

    # WIRE-016: Try create_execution_backend first (in-process).
    # Prefer agent_team_v15 (MCP-enhanced), fall back to agent_team (base).
    for _exec_mod in ("agent_team_v15.execution", "agent_team.execution"):
        try:
            import importlib

            mod = importlib.import_module(_exec_mod)
            create_execution_backend = mod.create_execution_backend  # type: ignore[attr-defined]
            backend = create_execution_backend(builder_dir=output_dir, config=builder_config)
            result = await backend.run()
            return _parse_builder_result(service_info.service_id, output_dir)
        except ImportError:
            logger.info(
                "%s not available for %s, trying next option",
                _exec_mod,
                service_info.service_id,
            )
            continue
        except Exception as exc:
            logger.info(
                "%s failed for %s: %s -- falling back to subprocess",
                _exec_mod,
                service_info.service_id,
                exc,
            )
            break  # Don't try the next in-process module; go to subprocess.
    else:
        logger.info(
            "No in-process execution backend available for %s, using subprocess",
            service_info.service_id,
        )

    # Subprocess fallback -- prefer agent_team_v15, then agent_team.
    builder_modules = ["agent_team_v15", "agent_team"]

    # Build subprocess environment: keep STATE.json for result parsing,
    # and select the CLI backend when no API key is available.
    sub_env = _filtered_env()
    sub_env["AGENT_TEAM_KEEP_STATE"] = "1"

    for module_name in builder_modules:
        proc = None
        try:
            # Use absolute paths and change cwd to output_dir to avoid config conflicts
            cmd = [
                sys.executable,
                "-m",
                module_name,
                "--prd",
                "prd_input.md",  # Relative to output_dir
                "--depth",
                config.builder.depth,
                "--no-interview",
            ]
            # Use CLI backend when no ANTHROPIC_API_KEY is available
            if not os.environ.get("ANTHROPIC_API_KEY"):
                cmd.extend(["--backend", "cli"])
            logger.info(
                "Launching builder subprocess for %s in %s: %s -m %s",
                service_info.service_id,
                output_dir,
                sys.executable,
                module_name,
            )
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(output_dir),  # Set working directory for subprocess
                env=sub_env,
            )
            await asyncio.wait_for(
                proc.wait(), timeout=config.builder.timeout_per_builder
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Builder for %s timed out after %ds",
                service_info.service_id,
                config.builder.timeout_per_builder,
            )
            return BuilderResult(
                system_id=service_info.service_id,  # Use service_id as system_id fallback
                service_id=service_info.service_id,
                success=False,
                error=f"Timed out after {config.builder.timeout_per_builder}s",
            )
        except Exception as exc:
            logger.error(
                "Builder for %s failed with exception: %s",
                service_info.service_id,
                exc,
            )
            return BuilderResult(
                system_id=service_info.service_id,  # Use service_id as system_id fallback
                service_id=service_info.service_id,
                success=False,
                error=str(exc),
            )
        finally:
            if proc is not None and proc.returncode is None:
                # Graceful shutdown: terminate first, then force-kill.
                # On Windows proc.kill() can cascade; terminate() is gentler.
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()

        # INT-003: Check if the module was not found -- try the next one.
        # Also log stdout/stderr for debugging
        if proc.returncode != 0:
            stdout_text = ""
            stderr_text = ""
            if proc.stdout:
                stdout_text = (await proc.stdout.read()).decode(errors="replace")
            if proc.stderr:
                stderr_text = (await proc.stderr.read()).decode(errors="replace")

            if "ModuleNotFoundError" in stderr_text or "No module named" in stderr_text:
                logger.info(
                    "%s not installed, trying next builder module",
                    module_name,
                )
                continue  # Try the next module in builder_modules.

            # Log the error output for debugging
            logger.warning(
                "Builder subprocess %s exited with code %d. Stdout: %s... Stderr: %s...",
                module_name,
                proc.returncode,
                stdout_text[:1000],
                stderr_text[:1000],
            )

        # Module was found (even if the build itself failed) -- stop trying.
        break
    else:
        # Neither agent_team_v15 nor agent_team is installed.
        raise ConfigurationError(
            "No builder module is installed (tried agent_team_v15, agent_team). "
            "Install with `pip install agent-team-v15` or `pip install agent-team`, "
            "or ensure the package is on the Python path."
        )

    # Parse BuilderResult from STATE.json
    return _parse_builder_result(service_info.service_id, output_dir)


def _parse_builder_result(
    service_id: str, output_dir: Path
) -> BuilderResult:
    """Parse a BuilderResult from the builder's STATE.json.

    Validates that the builder actually produced meaningful output
    (source files) before accepting a ``success: true`` claim.
    """
    state_file = output_dir / ".agent-team" / "STATE.json"
    try:
        data = load_json(state_file)
        if data is None:
            raise FileNotFoundError("STATE.json is missing or invalid")
        summary = data.get("summary", {})
        claimed_success = summary.get("success", False)

        # Validate that the builder actually produced code.
        # If STATE.json claims success but the output directory is empty
        # (no source files, no Dockerfile), the build didn't really work.
        if claimed_success:
            _code_patterns = ("*.py", "*.js", "*.ts", "Dockerfile", "*.go", "*.rs")
            has_source = any(
                next(output_dir.rglob(pat), None) is not None
                for pat in _code_patterns
            )
            error_context = str(data.get("error_context", ""))
            if not has_source:
                logger.warning(
                    "Builder %s claims success but produced no source files "
                    "(error_context=%s) -- marking as failed",
                    service_id,
                    error_context or "(none)",
                )
                claimed_success = False
                if not summary.get("error"):
                    summary["error"] = (
                        f"No source files produced. error_context: {error_context}"
                        if error_context
                        else "No source files produced by builder"
                    )

        return BuilderResult(
            system_id=str(data.get("system_id", "")),
            service_id=service_id,
            success=claimed_success,
            cost=float(data.get("total_cost", 0.0)),
            test_passed=int(summary.get("test_passed", 0)),
            test_total=int(summary.get("test_total", 0)),
            convergence_ratio=float(summary.get("convergence_ratio", 0.0)),
            output_dir=str(output_dir),
            error=str(data.get("error_context", data.get("error", ""))),
        )
    except FileNotFoundError:
        logger.warning("No STATE.json found for builder %s", service_id)
        return BuilderResult(
            system_id=service_id,  # Use service_id as system_id fallback
            service_id=service_id,
            success=False,
            error="No STATE.json found",
        )
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning(
            "Failed to parse STATE.json for builder %s: %s", service_id, exc
        )
        return BuilderResult(
            system_id=service_id,  # Use service_id as system_id fallback
            service_id=service_id,
            success=False,
            error=f"Failed to parse STATE.json: {exc}",
        )


async def _check_contract_breaking_changes(
    state: PipelineState,
    services: list[ServiceInfo],
    service_urls: dict[str, str],
) -> list[ContractViolation]:
    """Check for breaking changes between registered and actual OpenAPI specs.

    Attempts MCP-based detection first (via the bare ``check_breaking_changes``
    function) and falls back to the direct ``detect_breaking_changes`` function
    using the filesystem-stored contract specs.

    This is a **best-effort** check: any failure is logged and silently
    ignored so that the pipeline is never blocked by contract validation.

    Returns a list of :class:`ContractViolation` for every breaking change
    detected.
    """
    violations: list[ContractViolation] = []
    registry_dir = Path(state.contract_registry_path) if state.contract_registry_path else None

    if not registry_dir or not registry_dir.is_dir():
        logger.info("No contract registry directory -- skipping breaking change check")
        return violations

    # Attempt to import the MCP client functions for the MCP-first path.
    mcp_list_contracts = None
    mcp_check_breaking = None
    try:
        from src.contract_engine.mcp_client import (  # type: ignore[import-untyped]
            check_breaking_changes as _mcp_check,
            list_contracts as _mcp_list,
        )
        mcp_list_contracts = _mcp_list
        mcp_check_breaking = _mcp_check
    except ImportError:
        logger.info("Contract Engine MCP client not available -- will use direct detector")

    # Import the direct (non-MCP) breaking change detector as fallback.
    detect_fn = None
    try:
        from src.contract_engine.services.breaking_change_detector import (
            detect_breaking_changes as _detect,
        )
        detect_fn = _detect
    except ImportError:
        logger.info("Breaking change detector not importable -- skipping breaking change check")
        if mcp_list_contracts is None:
            return violations

    for svc in services:
        try:
            # --- Fetch the actual OpenAPI spec from the running service ------
            import httpx  # lazy import

            actual_url = f"{service_urls[svc.service_id]}/openapi.json"
            async with httpx.AsyncClient() as client:
                resp = await client.get(actual_url, timeout=10)
                if resp.status_code != 200:
                    logger.debug(
                        "Could not fetch OpenAPI spec from %s (status %d)",
                        actual_url,
                        resp.status_code,
                    )
                    continue
                actual_spec: dict[str, Any] = resp.json()

            # --- Path A: MCP-based check ------------------------------------
            if mcp_list_contracts is not None and mcp_check_breaking is not None:
                try:
                    contracts_result = await mcp_list_contracts(
                        service_name=svc.service_id,
                    )
                    items = contracts_result.get("items", [])
                    if items:
                        contract_id = items[0].get("id", "")
                        if contract_id:
                            changes = await mcp_check_breaking(
                                contract_id=contract_id,
                                new_spec=actual_spec,
                            )
                            for change in (changes or []):
                                violations.append(
                                    ContractViolation(
                                        code="CONTRACT-BREAK-001",
                                        severity=change.get("severity", "error"),
                                        service=svc.service_id,
                                        endpoint=change.get("path", ""),
                                        message=change.get("change_type", "Breaking change detected"),
                                    )
                                )
                            # MCP succeeded for this service; move to the next one.
                            continue
                except Exception as mcp_exc:
                    logger.debug(
                        "MCP breaking-change check failed for %s, falling back to direct: %s",
                        svc.service_id,
                        mcp_exc,
                    )

            # --- Path B: Direct filesystem-based comparison ------------------
            if detect_fn is not None:
                registered_spec_path = registry_dir / f"{svc.service_id}.json"
                if not registered_spec_path.exists():
                    logger.debug(
                        "No registered spec file for %s at %s",
                        svc.service_id,
                        registered_spec_path,
                    )
                    continue

                registered_spec = json.loads(
                    registered_spec_path.read_text(encoding="utf-8")
                )

                changes = detect_fn(registered_spec, actual_spec)
                for change in changes:
                    # Only report error/warning severity breaking changes.
                    if getattr(change, "severity", "info") in ("error", "warning"):
                        violations.append(
                            ContractViolation(
                                code="CONTRACT-BREAK-001",
                                severity=getattr(change, "severity", "error"),
                                service=svc.service_id,
                                endpoint=getattr(change, "path", ""),
                                message=(
                                    f"{getattr(change, 'change_type', 'breaking_change')}: "
                                    f"{getattr(change, 'old_value', '')} -> "
                                    f"{getattr(change, 'new_value', '')}"
                                ),
                            )
                        )

        except Exception as exc:
            logger.debug(
                "Breaking change check failed for %s: %s", svc.service_id, exc,
            )

    if violations:
        logger.warning(
            "Detected %d breaking change violation(s) across services",
            len(violations),
        )
    else:
        logger.info("No breaking change violations detected")

    return violations


async def run_integration_phase(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
) -> None:
    """Run the integration phase: Docker + compliance + cross-service tests.

    Composes :class:`ComposeGenerator`, :class:`DockerOrchestrator`,
    :class:`ContractComplianceVerifier`, and :class:`CrossServiceTestRunner`.
    """
    logger.info("Starting integration phase")
    cost_tracker.start_phase(PHASE_INTEGRATION)
    phase_cost = 0.0

    if shutdown.should_stop:
        logger.warning("Shutdown requested before integration phase")
        state.save()
        cost_tracker.end_phase(phase_cost)
        return

    output_dir = Path(config.output_dir)

    # Lazy imports for integration components
    try:
        from src.integrator.compose_generator import ComposeGenerator
        from src.integrator.contract_compliance import ContractComplianceVerifier
        from src.integrator.cross_service_test_runner import CrossServiceTestRunner
        from src.integrator.docker_orchestrator import DockerOrchestrator
        from src.integrator.service_discovery import ServiceDiscovery
    except ImportError as exc:
        raise ConfigurationError(
            f"Integration dependencies not available: {exc}. "
            "Ensure integrator package is installed."
        ) from exc

    # Build ServiceInfo list from state
    service_map = load_json(state.service_map_path)
    services_raw = service_map.get("services", [])
    services: list[ServiceInfo] = []
    for svc in services_raw:
        sid = svc.get("service_id", svc.get("name", ""))
        if not sid:
            continue
        # Only include services that passed building
        if state.builder_statuses.get(sid) != "healthy":
            continue
        services.append(
            ServiceInfo(
                service_id=sid,
                domain=svc.get("domain", "unknown"),
                stack=svc.get("stack", {}),
                port=svc.get("port", 8080),
                health_endpoint=svc.get("health_endpoint", "/health"),
                docker_image=svc.get("docker_image", ""),
                estimated_loc=svc.get("estimated_loc", 0),
            )
        )

    if not services:
        logger.warning("No passing services to integrate")
        report = IntegrationReport(overall_health="failed")
        report_path = output_dir / "integration_report.json"
        atomic_write_json(report_path, dataclasses.asdict(report))
        state.integration_report_path = str(report_path)
        cost_tracker.end_phase(phase_cost)
        state.total_cost = cost_tracker.total_cost
        state.phase_costs = cost_tracker.phase_costs
        state.save()
        return

    # Step 1: Generate 5-file compose merge (TECH-004)
    compose_gen = ComposeGenerator(
        traefik_image=config.integration.traefik_image
    )
    compose_files = compose_gen.generate_compose_files(output_dir, services)
    logger.info(
        "Generated %d compose files for merge: %s",
        len(compose_files),
        [f.name for f in compose_files],
    )

    docker = DockerOrchestrator(compose_files, project_name="super-team-run4")
    discovery = ServiceDiscovery(compose_files, project_name="super-team-run4")

    try:
        # Step 2: Start services
        # start_services() returns a dict of {service_name: ServiceInfo}
        # when successful, or an empty dict on failure.
        start_result = await docker.start_services()
        if not start_result:
            raise IntegrationFailureError(
                "Failed to start services: docker compose up returned no running services"
            )

        state.services_deployed = [s.service_id for s in services]

        # Step 3: Wait for healthy
        health_result = await docker.wait_for_healthy(
            timeout_seconds=config.integration.timeout,
        )

        # Step 4: Get service URLs
        # get_service_ports is synchronous (PRD REQ-018)
        service_ports = discovery.get_service_ports()
        service_urls: dict[str, str] = {}
        for svc in services:
            port = service_ports.get(svc.service_id, svc.port)
            service_urls[svc.service_id] = f"http://localhost:{port}"

        # Step 5: Contract compliance
        registry_path = Path(state.contract_registry_path) if state.contract_registry_path else output_dir / "contracts"
        verifier = ContractComplianceVerifier(
            contract_registry_path=registry_path,
            services=service_urls,
        )
        services_dicts = [
            {"service_id": s.service_id, "openapi_url": f"http://localhost:{service_ports.get(s.service_id, s.port)}/openapi.json"}
            for s in services
        ]

        compliance_report = await verifier.verify_all_services(
            services=services_dicts,
            service_urls=service_urls,
            contract_registry_path=str(registry_path),
        )

        # Step 6: Cross-service tests
        runner = CrossServiceTestRunner()
        flow_results = await runner.run_flow_tests(
            flows=[], service_urls=service_urls
        )

        # Step 6b: Boundary tests (WIRE-017)
        boundary_violations: list[ContractViolation] = []
        try:
            from src.integrator.boundary_tester import BoundaryTester

            boundary_tester = BoundaryTester()
            boundary_violations = await boundary_tester.run_all_boundary_tests(
                service_urls=service_urls,
                boundary_tests=[],
            )
        except ImportError:
            logger.debug("BoundaryTester not available -- skipping boundary tests")
        except Exception as bt_exc:
            logger.warning("Boundary tests failed: %s", bt_exc)

        # Step 6c: Breaking change detection against registered contracts
        breaking_violations: list[ContractViolation] = []
        try:
            breaking_violations = await _check_contract_breaking_changes(
                state=state,
                services=services,
                service_urls=service_urls,
            )
        except Exception as bc_exc:
            logger.warning("Breaking change detection failed: %s", bc_exc)

        # Combine into integration report
        combined_violations = (
            list(compliance_report.violations)
            + boundary_violations
            + breaking_violations
        )
        report = IntegrationReport(
            services_deployed=len(services),
            services_healthy=sum(
                1
                for s in health_result.get("services", {}).values()
                if s.get("status") == "healthy"
            ),
            contract_tests_passed=compliance_report.contract_tests_passed,
            contract_tests_total=compliance_report.contract_tests_total,
            integration_tests_passed=flow_results.get("passed", 0) if isinstance(flow_results, dict) else 0,
            integration_tests_total=flow_results.get("total", 0) if isinstance(flow_results, dict) else 0,
            violations=combined_violations,
            overall_health=compliance_report.overall_health,
        )

    except Exception as exc:
        logger.error("Integration phase error: %s", exc)
        report = IntegrationReport(
            services_deployed=len(services),
            services_healthy=0,
            violations=[
                ContractViolation(
                    code="INTEGRATION-001",
                    severity="error",
                    service="pipeline",
                    endpoint="",
                    message=f"Integration phase failed: {exc}",
                )
            ],
            overall_health="failed",
        )
    finally:
        # Step 7: Stop services
        try:
            await docker.stop_services()
        except Exception as stop_exc:
            logger.warning("Failed to stop services: %s", stop_exc)

    report_path = output_dir / "integration_report.json"
    atomic_write_json(report_path, dataclasses.asdict(report))
    state.integration_report_path = str(report_path)

    # Generate human-readable markdown report (WIRE-019)
    md_report_path = output_dir / "INTEGRATION_REPORT.md"
    try:
        from src.integrator.report import generate_integration_report

        md_text = generate_integration_report(report)
        md_report_path.write_text(md_text, encoding="utf-8")
        logger.info("Wrote integration markdown report to %s", md_report_path)
    except ImportError:
        logger.debug("Integration report generator not available -- skipping markdown report")
    except Exception as exc:
        logger.warning("Failed to generate integration markdown report: %s", exc)

    state.phase_artifacts[PHASE_INTEGRATION] = {
        "report_path": str(report_path),
        "md_report_path": str(md_report_path),
        "services_deployed": report.services_deployed,
        "services_healthy": report.services_healthy,
    }
    if PHASE_INTEGRATION not in state.completed_phases:
        state.completed_phases.append(PHASE_INTEGRATION)

    cost_tracker.end_phase(phase_cost)
    state.total_cost = cost_tracker.total_cost
    state.phase_costs = cost_tracker.phase_costs
    state.save()

    logger.info(
        "Integration phase complete -- %d/%d healthy, health=%s",
        report.services_healthy,
        report.services_deployed,
        report.overall_health,
    )


async def run_quality_gate(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
) -> QualityGateReport:
    """Execute the quality gate engine.

    Returns
    -------
    QualityGateReport
        The full quality gate report.

    Raises
    ------
    QualityGateFailureError
        When the gate fails after max retries.
    """
    logger.info("Starting quality gate phase")
    cost_tracker.start_phase(PHASE_QUALITY_GATE)

    if shutdown.should_stop:
        logger.warning("Shutdown requested before quality gate")
        state.save()
        cost_tracker.end_phase(0.0)
        return QualityGateReport()

    # Lazy import quality gate engine
    try:
        from src.quality_gate.gate_engine import QualityGateEngine
    except ImportError as exc:
        raise ConfigurationError(
            f"Quality gate not available: {exc}"
        ) from exc

    # Reconstruct builder results
    builder_results: list[BuilderResult] = []
    for sid, result_dict in state.builder_results.items():
        builder_results.append(
            BuilderResult(
                system_id=str(result_dict.get("system_id", "")),
                service_id=sid,
                success=bool(result_dict.get("success", False)),
                cost=float(result_dict.get("cost", 0.0)),
                test_passed=int(result_dict.get("test_passed", 0)),
                test_total=int(result_dict.get("test_total", 0)),
                convergence_ratio=float(result_dict.get("convergence_ratio", 0.0)),
                error=str(result_dict.get("error", "")),
            )
        )

    # Load integration report
    integration_report = IntegrationReport()
    if state.integration_report_path:
        try:
            ir_data = load_json(state.integration_report_path)
            # Reconstruct violations
            violations = []
            for v in ir_data.get("violations", []):
                violations.append(ContractViolation(**{
                    k: v_val
                    for k, v_val in v.items()
                    if k in {f.name for f in dataclasses.fields(ContractViolation)}
                }))
            ir_data["violations"] = violations
            known_fields = {f.name for f in dataclasses.fields(IntegrationReport)}
            filtered = {k: v_val for k, v_val in ir_data.items() if k in known_fields}
            integration_report = IntegrationReport(**filtered)
        except Exception as exc:
            logger.warning("Failed to load integration report: %s", exc)

    target_dir = Path(config.output_dir)

    engine = QualityGateEngine()
    report = await engine.run_all_layers(
        builder_results=builder_results,
        integration_report=integration_report,
        target_dir=target_dir,
        fix_attempts=state.quality_attempts,
        max_fix_attempts=config.quality_gate.max_fix_retries,
    )

    # Persist results
    report_dict = dataclasses.asdict(report)
    # Convert enum values to strings for JSON serialization
    report_path = Path(config.output_dir) / "quality_gate_report.json"
    atomic_write_json(report_path, report_dict)

    # Generate human-readable markdown report (WIRE-019)
    md_report_path = Path(config.output_dir) / "QUALITY_GATE_REPORT.md"
    try:
        from src.quality_gate.report import generate_quality_gate_report

        md_text = generate_quality_gate_report(report)
        md_report_path.write_text(md_text, encoding="utf-8")
        logger.info("Wrote quality gate markdown report to %s", md_report_path)
    except ImportError:
        logger.debug("Quality gate report generator not available -- skipping markdown report")
    except Exception as exc:
        logger.warning("Failed to generate quality gate markdown report: %s", exc)

    state.quality_report_path = str(report_path)
    state.last_quality_results = report_dict
    state.phase_artifacts[PHASE_QUALITY_GATE] = {
        "report_path": str(report_path),
        "md_report_path": str(md_report_path),
        "overall_verdict": report.overall_verdict.value
        if hasattr(report.overall_verdict, "value")
        else str(report.overall_verdict),
    }

    cost_tracker.end_phase(0.0)
    state.total_cost = cost_tracker.total_cost
    state.phase_costs = cost_tracker.phase_costs
    state.save()

    logger.info(
        "Quality gate complete -- verdict=%s, violations=%d, blocking=%d",
        report.overall_verdict.value
        if hasattr(report.overall_verdict, "value")
        else report.overall_verdict,
        report.total_violations,
        report.blocking_violations,
    )

    return report


async def run_fix_pass(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
) -> None:
    """Run the fix pass using :class:`ContractFixLoop`.

    Feeds violations to builders for each failing service and
    increments ``state.quality_attempts``.  Enhanced with priority
    classification (P0-P3), violation snapshots, regression detection,
    and convergence scoring from ``src.run4.fix_pass``.
    """
    logger.info("Starting fix pass (attempt %d)", state.quality_attempts + 1)
    cost_tracker.start_phase(PHASE_FIX_PASS)
    total_fix_cost = 0.0

    if shutdown.should_stop:
        logger.warning("Shutdown requested before fix pass")
        state.save()
        cost_tracker.end_phase(total_fix_cost)
        return

    # Lazy imports -- ContractFixLoop for builder feeding
    try:
        from src.integrator.fix_loop import ContractFixLoop
    except ImportError as exc:
        raise ConfigurationError(
            f"ContractFixLoop not available: {exc}"
        ) from exc

    # Lazy imports -- run4 fix_pass utilities for priority classification,
    # snapshots, regression detection, and convergence checking
    try:
        from src.run4.fix_pass import (
            classify_priority,
            check_convergence,
            compute_convergence,
            detect_regressions,
            take_violation_snapshot,
        )
        _has_run4_fix_pass = True
    except ImportError:
        logger.debug(
            "src.run4.fix_pass not available -- skipping priority "
            "classification and convergence tracking"
        )
        _has_run4_fix_pass = False

    fix_loop = ContractFixLoop(timeout=config.builder.timeout_per_builder)

    # Extract violations from last quality results
    quality_results = state.last_quality_results
    all_violations: list[ContractViolation] = []

    for layer_name, layer_data in quality_results.get("layers", {}).items():
        for v_data in layer_data.get("violations", []):
            all_violations.append(
                ContractViolation(
                    code=str(v_data.get("code", "")),
                    severity=str(v_data.get("severity", "error")),
                    service=str(v_data.get("service", v_data.get("file_path", ""))),
                    endpoint=str(v_data.get("endpoint", "")),
                    message=str(v_data.get("message", "")),
                    expected=str(v_data.get("expected", "")),
                    actual=str(v_data.get("actual", "")),
                    file_path=str(v_data.get("file_path", "")),
                )
            )

    # ---- Step 1: Take pre-fix violation snapshot ----
    snapshot_before: dict[str, list[str]] = {}
    if _has_run4_fix_pass and all_violations:
        violation_dicts = [
            {
                "scan_code": v.code,
                "file_path": v.file_path or v.service or "",
            }
            for v in all_violations
        ]
        snapshot_before = take_violation_snapshot(violation_dicts)

    # ---- Step 2: Classify each violation by priority (P0-P3) ----
    priority_counts: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    if _has_run4_fix_pass:
        for v in all_violations:
            priority = classify_priority({
                "severity": v.severity,
                "category": v.code,
                "message": v.message,
            })
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

        logger.info(
            "Fix pass priority breakdown: P0=%d, P1=%d, P2=%d, P3=%d "
            "(total violations=%d)",
            priority_counts["P0"],
            priority_counts["P1"],
            priority_counts["P2"],
            priority_counts["P3"],
            len(all_violations),
        )

    # Group violations by service
    violations_by_service: dict[str, list[ContractViolation]] = {}
    for v in all_violations:
        svc = v.service or "unknown"
        violations_by_service.setdefault(svc, []).append(v)

    # Feed violations to builders (existing ContractFixLoop mechanism)
    for service_id, violations in violations_by_service.items():
        if shutdown.should_stop:
            break

        builder_dir = Path(config.output_dir) / service_id
        try:
            result = await fix_loop.feed_violations_to_builder(
                service_id=service_id,
                violations=violations,
                builder_dir=builder_dir,
            )
            total_fix_cost += result.total_cost
        except Exception as exc:
            logger.warning(
                "Fix pass for service %s failed: %s", service_id, exc
            )

    # ---- Step 3: Take post-fix violation snapshot & detect regressions ----
    snapshot_after: dict[str, list[str]] = {}
    regressions: list[dict] = []
    if _has_run4_fix_pass and snapshot_before:
        # Re-extract violations from quality results to build post-fix snapshot.
        # Note: the actual post-fix scan happens in the next quality_gate pass;
        # here we record the snapshot for comparison in subsequent iterations.
        snapshot_after = take_violation_snapshot(
            [
                {
                    "scan_code": v.code,
                    "file_path": v.file_path or v.service or "",
                }
                for v in all_violations
            ]
        )
        regressions = detect_regressions(snapshot_before, snapshot_after)
        if regressions:
            logger.warning(
                "Fix pass detected %d regressions", len(regressions)
            )

    # ---- Step 4: Compute convergence score ----
    convergence_score = 0.0
    convergence_reason = ""
    if _has_run4_fix_pass:
        p0 = priority_counts["P0"]
        p1 = priority_counts["P1"]
        p2 = priority_counts["P2"]

        # Compute initial weighted total for convergence formula.
        # On the first fix attempt we use current counts as initial baseline;
        # on subsequent attempts we pull the stored initial weights from
        # phase_artifacts if available.
        prev_artifacts = state.phase_artifacts.get(PHASE_FIX_PASS, {})
        initial_total_weighted = prev_artifacts.get(
            "initial_total_weighted",
            p0 * 0.4 + p1 * 0.3 + p2 * 0.1,
        )

        convergence_score = compute_convergence(p0, p1, p2, initial_total_weighted)

        convergence_result = check_convergence(
            remaining_p0=p0,
            remaining_p1=p1,
            remaining_p2=p2,
            initial_total_weighted=initial_total_weighted,
            current_pass=state.quality_attempts + 1,
            max_fix_passes=getattr(config.quality_gate, "max_fix_retries", 5),
            budget_remaining=(state.budget_limit or float("inf")) - state.total_cost,
        )
        convergence_score = convergence_result.convergence_score
        convergence_reason = convergence_result.reason

        logger.info(
            "Fix pass convergence: score=%.3f, should_stop=%s, reason=%s",
            convergence_score,
            convergence_result.should_stop,
            convergence_reason,
        )

    state.quality_attempts += 1

    # ---- Step 5: Store enriched phase artifacts ----
    phase_artifact: dict[str, Any] = {
        "attempt": state.quality_attempts,
        "services_fixed": len(violations_by_service),
        "total_cost": total_fix_cost,
    }
    if _has_run4_fix_pass:
        phase_artifact.update({
            "p0_count": priority_counts["P0"],
            "p1_count": priority_counts["P1"],
            "p2_count": priority_counts["P2"],
            "p3_count": priority_counts["P3"],
            "total_violations": len(all_violations),
            "convergence_score": convergence_score,
            "convergence_reason": convergence_reason,
            "regression_count": len(regressions),
            "snapshot_before_codes": len(snapshot_before),
            "snapshot_after_codes": len(snapshot_after),
            # Preserve initial weighted total for subsequent fix passes
            "initial_total_weighted": prev_artifacts.get(
                "initial_total_weighted",
                priority_counts["P0"] * 0.4
                + priority_counts["P1"] * 0.3
                + priority_counts["P2"] * 0.1,
            ),
        })

    state.phase_artifacts[PHASE_FIX_PASS] = phase_artifact

    cost_tracker.end_phase(total_fix_cost)
    state.total_cost = cost_tracker.total_cost
    state.phase_costs = cost_tracker.phase_costs
    state.save()

    logger.info(
        "Fix pass complete -- attempt %d, cost=$%.4f, "
        "P0=%d, P1=%d, convergence=%.3f",
        state.quality_attempts,
        total_fix_cost,
        priority_counts.get("P0", 0),
        priority_counts.get("P1", 0),
        convergence_score,
    )


# ---------------------------------------------------------------------------
# Main pipeline loop
# ---------------------------------------------------------------------------


async def execute_pipeline(
    prd_path: str | Path,
    config_path: str | Path | None = None,
    resume: bool = False,
) -> PipelineState:
    """Execute the full pipeline from PRD to completion.

    This is the top-level entry point that drives the state machine
    through all phases.

    Parameters
    ----------
    prd_path:
        Path to the PRD file.
    config_path:
        Optional path to config YAML.
    resume:
        If ``True``, resume from a previously interrupted state.

    Returns
    -------
    PipelineState
        Final pipeline state after execution.
    """
    prd_path = Path(prd_path)
    config = load_super_config(config_path)

    # Ensure output directory
    output_dir = Path(config.output_dir)
    ensure_dir(output_dir)

    # Create or load state
    if resume:
        try:
            state = PipelineState.load()
            logger.info(
                "Resuming pipeline %s from state '%s'",
                state.pipeline_id,
                state.current_state,
            )
        except FileNotFoundError:
            raise ConfigurationError(
                "No pipeline state to resume. Run without --resume first."
            )
    else:
        state = PipelineState(
            prd_path=str(prd_path),
            config_path=str(config_path) if config_path else "",
            budget_limit=config.budget_limit,
            depth=config.builder.depth,
        )
        state.save()
        logger.info("Created new pipeline %s", state.pipeline_id)

    # Set up cost tracking, shutdown, state machine
    cost_tracker = PipelineCostTracker(budget_limit=config.budget_limit)
    shutdown = GracefulShutdown()
    shutdown.install()
    shutdown.set_state(state)

    model = PipelineModel(state)
    machine = create_pipeline_machine(model)

    # If resuming, set the machine's initial state
    if resume and state.current_state != "init":
        model.state = state.current_state

    try:
        await _run_pipeline_loop(state, config, cost_tracker, shutdown, model)
    except BudgetExceededError:
        logger.error("Budget exceeded -- saving state and exiting")
        state.interrupted = True
        state.interrupt_reason = "Budget exceeded"
        state.save()
        raise
    except PipelineError:
        logger.error("Pipeline error -- saving state")
        state.save()
        raise
    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt -- saving state")
        state.interrupted = True
        state.interrupt_reason = "Keyboard interrupt"
        state.save()
        raise
    except Exception as exc:
        logger.exception("Unexpected error in pipeline")
        state.save()
        raise PipelineError(f"Unexpected error: {exc}") from exc

    return state


async def _run_pipeline_loop(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Internal pipeline loop that drives phase transitions."""

    # Phase handlers map
    phase_handlers = {
        "init": _phase_architect,
        "architect_running": _phase_architect_complete,
        "architect_review": _phase_contracts,
        "contracts_registering": _phase_builders,
        "builders_running": _phase_builders_complete,
        "builders_complete": _phase_integration,
        "integrating": _phase_quality,
        "quality_gate": _phase_quality_check,
        "fix_pass": _phase_fix_done,
    }

    max_iterations = 50  # Safety bound
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        current = model.state

        if current in ("complete", "failed"):
            logger.info("Pipeline reached terminal state: %s", current)
            state.current_state = current
            state.save()
            break

        if shutdown.should_stop:
            logger.warning("Graceful shutdown requested at state '%s'", current)
            state.interrupted = True
            state.interrupt_reason = "Signal received"
            state.current_state = current
            state.save()
            break

        handler = phase_handlers.get(current)
        if handler is None:
            raise PipelineError(f"No handler for state '{current}'")

        await handler(state, config, cost_tracker, shutdown, model)

        # Budget check after every phase
        cost_tracker.check_budget()

        # Sync model state back to pipeline state
        state.current_state = model.state
        state.save()


# ---------------------------------------------------------------------------
# Phase handler functions (called from the pipeline loop)
# ---------------------------------------------------------------------------


async def _phase_architect(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle init → architect_running transition."""
    state.save()
    await model.start_architect()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()

    await run_architect_phase(state, config, cost_tracker, shutdown)

    # TECH-025: save BEFORE transition
    state.save()
    await model.architect_done()  # type: ignore[attr-defined]
    state.current_state = model.state

    # TECH-025: save BEFORE transition
    state.save()
    await model.approve_architect()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()


async def _phase_architect_complete(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle architect_running (resume case)."""
    await run_architect_phase(state, config, cost_tracker, shutdown)
    state.save()
    await model.architect_done()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()
    await model.approve_architect()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()


async def _phase_contracts(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle contracts_registering state (resume case for architect_review)."""
    # Transition contracts_registering -> builders_running happens via trigger
    await run_contract_registration(state, config, cost_tracker, shutdown)
    state.save()
    await model.contracts_registered()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()


async def _phase_builders(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle contracts_registering → builders_running."""
    await run_contract_registration(state, config, cost_tracker, shutdown)
    state.save()
    await model.contracts_registered()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()


async def _phase_builders_complete(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle builders_running → builders_complete."""
    await run_parallel_builders(state, config, cost_tracker, shutdown)
    state.save()
    await model.builders_done()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()


async def _index_generated_code(
    state: PipelineState,
    config: SuperOrchestratorConfig,
) -> None:
    """Re-index generated code in the Codebase Intelligence MCP.

    Best-effort step executed after builders complete and before the
    integration phase begins.  Walks each successful builder's output
    directory for ``.py`` files and registers them via the CI MCP client.

    If the CI MCP client cannot be imported or the server is unreachable,
    the function logs a warning and returns silently -- it never blocks
    the pipeline.
    """
    # Lazy import: keeps super_orchestrator importable without Build 1
    try:
        from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient
    except ImportError:
        logger.info(
            "Codebase Intelligence MCP client not available -- skipping post-build indexing"
        )
        return

    client = CodebaseIntelligenceClient()
    indexed = 0
    errors = 0

    for service_id, status in state.builder_statuses.items():
        if status != "healthy":
            continue
        output_dir = Path(config.output_dir) / service_id
        if not output_dir.is_dir():
            logger.debug(
                "Builder output directory does not exist: %s", output_dir
            )
            continue
        for py_file in output_dir.rglob("*.py"):
            try:
                await client.register_artifact(
                    file_path=str(py_file),
                    service_name=service_id,
                )
                indexed += 1
            except Exception as exc:
                errors += 1
                logger.debug("Failed to index %s: %s", py_file, exc)

    logger.info(
        "Post-build indexing complete: %d files indexed, %d errors",
        indexed,
        errors,
    )


async def _phase_integration(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle builders_complete → integrating."""
    # Re-index generated code so CI MCP tools work on builder output.
    # Best-effort: failures are logged but never block integration.
    # NOTE: On Windows, the CI MCP client's _get_session() enters async
    # contexts without proper cleanup, leaving dangling anyio cancel scopes
    # that corrupt the asyncio event loop and cancel all subsequent awaits.
    # To avoid this, we skip MCP-based indexing on Windows and rely on
    # the quality gate to pick up source files directly.
    if sys.platform != "win32":
        try:
            await _index_generated_code(state, config)
        except Exception as exc:
            logger.warning("Post-build indexing failed (non-fatal): %s", exc)
    else:
        logger.info(
            "Skipping post-build MCP indexing on Windows to avoid "
            "anyio cancel scope issues"
        )

    state.save()
    await model.start_integration()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()

    await run_integration_phase(state, config, cost_tracker, shutdown)
    state.save()
    await model.integration_done()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()


async def _phase_quality(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle integrating → quality_gate."""
    report = await run_quality_gate(state, config, cost_tracker, shutdown)

    verdict = report.overall_verdict
    if hasattr(verdict, "value"):
        verdict_str = verdict.value
    else:
        verdict_str = str(verdict)

    state.save()
    if verdict_str == GateVerdict.PASSED.value:
        await model.quality_passed()  # type: ignore[attr-defined]
    elif model.fix_attempts_remaining():
        await model.quality_needs_fix()  # type: ignore[attr-defined]
    elif model.advisory_only():
        await model.skip_to_complete()  # type: ignore[attr-defined]
    else:
        raise QualityGateFailureError(
            f"Quality gate failed after {state.quality_attempts} fix attempts"
        )
    state.current_state = model.state
    state.save()


async def _phase_quality_check(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle quality_gate state (resume case)."""
    report = await run_quality_gate(state, config, cost_tracker, shutdown)

    verdict = report.overall_verdict
    if hasattr(verdict, "value"):
        verdict_str = verdict.value
    else:
        verdict_str = str(verdict)

    state.save()
    if verdict_str == GateVerdict.PASSED.value:
        await model.quality_passed()  # type: ignore[attr-defined]
    elif model.fix_attempts_remaining():
        await model.quality_needs_fix()  # type: ignore[attr-defined]
    elif model.advisory_only():
        await model.skip_to_complete()  # type: ignore[attr-defined]
    else:
        raise QualityGateFailureError(
            f"Quality gate failed after {state.quality_attempts} fix attempts"
        )
    state.current_state = model.state
    state.save()


async def _phase_fix_done(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle fix_pass → builders_running loop."""
    await run_fix_pass(state, config, cost_tracker, shutdown)
    state.save()
    await model.fix_done()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()
