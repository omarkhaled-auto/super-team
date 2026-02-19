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
_FILTERED_ENV_KEYS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"}


def _filtered_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with secret keys removed."""
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

    # Write config.yaml compatible with Build 2's _dict_to_config()
    config_path = output_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(config_dict, fh, default_flow_style=False, sort_keys=False)

    logger.info("Generated builder config: %s", config_path)
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
        contract_stubs = load_json(stubs_file)

    services = service_map.get("services", [])
    registered = []

    for svc in services:
        if shutdown.should_stop:
            break

        service_name = svc.get("service_id", svc.get("name", ""))
        if not service_name:
            continue

        spec = contract_stubs.get(service_name, svc.get("contract", {}))
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

    # WIRE-016: Try create_execution_backend first (Build 2 in-process)
    try:
        from agent_team.execution import create_execution_backend  # type: ignore[import-untyped]

        backend = create_execution_backend(builder_dir=output_dir, config=builder_config)
        result = await backend.run()
        return _parse_builder_result(service_info.service_id, output_dir)
    except ImportError:
        logger.info(
            "create_execution_backend not available for %s, falling back to subprocess",
            service_info.service_id,
        )
    except Exception as exc:
        logger.info(
            "create_execution_backend failed for %s: %s -- falling back to subprocess",
            service_info.service_id,
            exc,
        )

    # Subprocess fallback
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "agent_team",
            "--cwd",
            str(output_dir),
            "--depth",
            config.builder.depth,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_filtered_env(),
        )
        await asyncio.wait_for(
            proc.wait(), timeout=config.builder.timeout
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Builder for %s timed out after %ds",
            service_info.service_id,
            config.builder.timeout,
        )
        return BuilderResult(
            service_id=service_info.service_id,
            success=False,
            error=f"Timed out after {config.builder.timeout}s",
        )
    except Exception as exc:
        logger.error(
            "Builder for %s failed with exception: %s",
            service_info.service_id,
            exc,
        )
        return BuilderResult(
            service_id=service_info.service_id,
            success=False,
            error=str(exc),
        )
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()

    # INT-003: Check if agent_team module was not found
    if proc.returncode != 0 and proc.stderr:
        stderr_text = (await proc.stderr.read()).decode(errors="replace")
        if "ModuleNotFoundError" in stderr_text or "No module named" in stderr_text:
            raise ConfigurationError(
                f"Build 2 agent_team is not installed (ModuleNotFoundError). "
                "Install Build 2 with `pip install agent-team` or ensure it is "
                "on the Python path."
            )

    # Parse BuilderResult from STATE.json
    return _parse_builder_result(service_info.service_id, output_dir)


def _parse_builder_result(
    service_id: str, output_dir: Path
) -> BuilderResult:
    """Parse a BuilderResult from the builder's STATE.json."""
    state_file = output_dir / ".agent-team" / "STATE.json"
    try:
        data = load_json(state_file)
        summary = data.get("summary", {})
        return BuilderResult(
            system_id=str(data.get("system_id", "")),
            service_id=service_id,
            success=summary.get("success", False),
            cost=float(data.get("total_cost", 0.0)),
            test_passed=int(summary.get("test_passed", 0)),
            test_total=int(summary.get("test_total", 0)),
            convergence_ratio=float(summary.get("convergence_ratio", 0.0)),
            output_dir=str(output_dir),
            error=str(data.get("error", "")),
        )
    except FileNotFoundError:
        logger.warning("No STATE.json found for builder %s", service_id)
        return BuilderResult(
            service_id=service_id,
            success=False,
            error="No STATE.json found",
        )
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning(
            "Failed to parse STATE.json for builder %s: %s", service_id, exc
        )
        return BuilderResult(
            service_id=service_id,
            success=False,
            error=f"Failed to parse STATE.json: {exc}",
        )


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

    # Step 1: Generate docker-compose
    compose_gen = ComposeGenerator(
        traefik_image=config.integration.traefik_image
    )
    compose_path = compose_gen.generate(services, output_dir)

    docker = DockerOrchestrator(compose_path)
    discovery = ServiceDiscovery(compose_path)

    try:
        # Step 2: Start services
        start_result = await docker.start_services()
        if not start_result.get("success"):
            raise IntegrationFailureError(
                f"Failed to start services: {start_result.get('error', 'unknown')}"
            )

        state.services_deployed = [s.service_id for s in services]

        # Step 3: Wait for healthy
        health_result = await docker.wait_for_healthy(
            timeout_seconds=config.integration.compose_timeout,
        )

        # Step 4: Get service URLs
        service_ports = await discovery.get_service_ports()
        service_urls: dict[str, str] = {}
        for svc in services:
            port = service_ports.get(svc.service_id, svc.port)
            service_urls[svc.service_id] = f"http://localhost:{port}"

        # Step 5: Contract compliance
        verifier = ContractComplianceVerifier()
        services_dicts = [
            {"service_id": s.service_id, "openapi_url": f"http://localhost:{service_ports.get(s.service_id, s.port)}/openapi.json"}
            for s in services
        ]

        compliance_report = await verifier.verify_all_services(
            services=services_dicts,
            service_urls=service_urls,
            contract_registry_path=state.contract_registry_path,
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

        # Combine into integration report
        combined_violations = list(compliance_report.violations) + boundary_violations
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
    increments ``state.quality_attempts``.
    """
    logger.info("Starting fix pass (attempt %d)", state.quality_attempts + 1)
    cost_tracker.start_phase(PHASE_FIX_PASS)
    total_fix_cost = 0.0

    if shutdown.should_stop:
        logger.warning("Shutdown requested before fix pass")
        state.save()
        cost_tracker.end_phase(total_fix_cost)
        return

    # Lazy import
    try:
        from src.integrator.fix_loop import ContractFixLoop
    except ImportError as exc:
        raise ConfigurationError(
            f"ContractFixLoop not available: {exc}"
        ) from exc

    fix_loop = ContractFixLoop(timeout=config.builder.timeout)

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
                    line=int(v_data.get("line", 0)),
                )
            )

    # Group violations by service
    violations_by_service: dict[str, list[ContractViolation]] = {}
    for v in all_violations:
        svc = v.service or "unknown"
        violations_by_service.setdefault(svc, []).append(v)

    # Feed violations to builders
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

    state.quality_attempts += 1

    state.phase_artifacts[PHASE_FIX_PASS] = {
        "attempt": state.quality_attempts,
        "services_fixed": len(violations_by_service),
        "total_cost": total_fix_cost,
    }

    cost_tracker.end_phase(total_fix_cost)
    state.total_cost = cost_tracker.total_cost
    state.phase_costs = cost_tracker.phase_costs
    state.save()

    logger.info(
        "Fix pass complete -- attempt %d, cost=$%.4f",
        state.quality_attempts,
        total_fix_cost,
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


async def _phase_integration(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle builders_complete → integrating."""
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
