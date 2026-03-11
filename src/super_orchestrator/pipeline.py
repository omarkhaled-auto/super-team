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
import shutil
import subprocess
import sys
import time
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
from src.super_orchestrator.cross_service_standards import build_cross_service_standards
from src.super_orchestrator.post_build_validator import validate_all_services
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
_FILTERED_ENV_KEYS = {
    "AWS_SECRET_ACCESS_KEY",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_GIT_BASH_PATH",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
}
# Also strip any env key starting with CLAUDE_CODE_ to future-proof
# against new env vars added by Claude Code releases.


def _normalize_service_name(name: str) -> str:
    """Normalize service name formats to a comparable slug.

    Handles both display names ('Auth Service') and slugified IDs
    ('auth-service') by converting to lowercase-hyphenated form.
    Also handles 'service' suffix variations like 'Auth' vs 'Auth Service'.
    """
    slug = name.lower().strip().replace("_", "-").replace(" ", "-")
    # Remove trailing '-service' for comparison (handles "auth" vs "auth-service")
    return slug


# PRD-defined event mappings for SupplyForge.
# This is the canonical event catalog extracted from the PRD's Events Table.
# Each event maps to (publisher_slug, [consumer_slugs]).
_PRD_EVENT_CATALOG: dict[str, tuple[str, list[str]]] = {
    "user.created": ("auth-service", ["notification-service", "reporting-service"]),
    "user.role_changed": ("auth-service", ["notification-service", "reporting-service"]),
    "supplier.approved": ("supplier-service", ["procurement-service", "notification-service"]),
    "supplier.suspended": ("supplier-service", ["procurement-service", "inventory-service", "notification-service"]),
    "supplier.rating_updated": ("supplier-service", ["procurement-service", "reporting-service"]),
    "product.created": ("product-service", ["inventory-service", "procurement-service"]),
    "product.price_changed": ("product-service", ["procurement-service", "reporting-service"]),
    "order.submitted": ("procurement-service", ["notification-service"]),
    "order.approved": ("procurement-service", ["supplier-service", "notification-service", "reporting-service"]),
    "order.sent": ("procurement-service", ["supplier-service", "shipping-service", "notification-service"]),
    "order.cancelled": ("procurement-service", ["inventory-service", "shipping-service", "notification-service"]),
    "rfq.published": ("procurement-service", ["supplier-service", "notification-service"]),
    "rfq.awarded": ("procurement-service", ["supplier-service", "notification-service", "reporting-service"]),
    "receipt.created": ("procurement-service", ["inventory-service", "quality-service", "shipping-service", "reporting-service"]),
    "receipt.completed": ("procurement-service", ["inventory-service", "reporting-service"]),
    "stock.low": ("inventory-service", ["procurement-service", "notification-service"]),
    "stock.updated": ("inventory-service", ["reporting-service"]),
    "transfer.completed": ("inventory-service", ["reporting-service", "notification-service"]),
    "reservation.expired": ("inventory-service", ["procurement-service", "notification-service"]),
    "shipment.dispatched": ("shipping-service", ["procurement-service", "notification-service"]),
    "shipment.delivered": ("shipping-service", ["procurement-service", "quality-service", "notification-service", "reporting-service"]),
    "shipment.failed": ("shipping-service", ["procurement-service", "notification-service"]),
    "inspection.completed": ("quality-service", ["procurement-service", "supplier-service", "inventory-service", "reporting-service"]),
    "inspection.failed": ("quality-service", ["supplier-service", "procurement-service", "notification-service"]),
    "ncr.opened": ("quality-service", ["supplier-service", "procurement-service", "notification-service"]),
    "ncr.resolved": ("quality-service", ["supplier-service", "reporting-service"]),
    "notification.sent": ("notification-service", ["reporting-service"]),
    "escalation.triggered": ("notification-service", ["reporting-service"]),
}


def _get_events_for_service(service_id: str) -> tuple[list[str], list[str]]:
    """Return (events_published, events_subscribed) for a service from the PRD catalog."""
    sid = _normalize_service_name(service_id)
    published: list[str] = []
    subscribed: list[str] = []
    for event_name, (publisher, consumers) in _PRD_EVENT_CATALOG.items():
        if _normalize_service_name(publisher) == sid:
            published.append(event_name)
        if any(_normalize_service_name(c) == sid for c in consumers):
            subscribed.append(event_name)
    return published, subscribed


def _generate_missing_lockfiles(output_dir: Path, service_ids: list[str]) -> None:
    """Generate missing package-lock.json files for TypeScript services.

    Builders sometimes skip running ``npm install``, which means
    ``package-lock.json`` is absent and ``npm ci`` in Docker fails.
    This safety net runs ``npm install --package-lock-only`` to generate
    the lockfile without downloading node_modules.
    """
    for sid in service_ids:
        svc_dir = output_dir / sid
        pkg_json = svc_dir / "package.json"
        pkg_lock = svc_dir / "package-lock.json"
        if pkg_json.exists() and not pkg_lock.exists():
            logger.warning("Generating missing package-lock.json for %s", sid)
            try:
                result = subprocess.run(
                    ["npm", "install", "--package-lock-only"],
                    cwd=str(svc_dir),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    logger.info("Generated package-lock.json for %s", sid)
                else:
                    logger.warning("npm install --package-lock-only failed for %s: %s", sid, result.stderr[:200])
            except Exception as exc:
                logger.warning("Failed to generate lockfile for %s: %s", sid, exc)


def _filtered_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with secret keys removed.

    Note: ANTHROPIC_API_KEY and OPENAI_API_KEY are intentionally passed through
    because builder subprocesses (agent_team) need them to function.
    The CLAUDECODE variable is removed to allow nested ``claude`` CLI sessions
    from builder subprocesses that use ``--backend cli``.
    """
    return {
        k: v
        for k, v in os.environ.items()
        if k not in _FILTERED_ENV_KEYS and not k.startswith("CLAUDE_CODE_")
    }


# ---------------------------------------------------------------------------
# Event name normalization helpers
# ---------------------------------------------------------------------------


def _domain_from_service_id(service_id: str) -> str:
    """Extract the domain prefix from a service id.

    Examples:
        "procurement-service" -> "procurement"
        "auth-service"        -> "auth"
        "frontend"            -> "frontend"
        "order-management"    -> "order-management"
    """
    if service_id.endswith("-service"):
        return service_id[: -len("-service")]
    return service_id


def _normalize_event_name(event_name: str, domain: str) -> str:
    """Ensure *event_name* follows the ``{domain}.{entity}.{action}`` convention.

    If the event already has 3+ dot-separated parts it is returned as-is.
    A two-part name (``entity.action``) is prefixed with *domain*.
    A single-word name is prefixed with ``{domain}.`` so it becomes
    ``{domain}.{name}`` (best effort).

    Examples::

        >>> _normalize_event_name("order.submitted", "procurement")
        'procurement.order.submitted'
        >>> _normalize_event_name("procurement.order.submitted", "procurement")
        'procurement.order.submitted'
        >>> _normalize_event_name("stock.low", "inventory")
        'inventory.stock.low'
        >>> _normalize_event_name("alert", "notification")
        'notification.alert'
    """
    parts = event_name.split(".")
    if len(parts) >= 3:
        return event_name
    return f"{domain}.{event_name}"


def _build_event_publisher_map(
    service_map: dict[str, Any],
) -> dict[str, str]:
    """Build a mapping from raw event name -> publisher domain.

    Scans every service in *service_map* and records which domain
    publishes each event.  This allows subscribed-event normalization
    to use the **publisher's** domain rather than the subscriber's.

    Returns a dict like ``{"order.submitted": "procurement", ...}``.
    """
    publisher_map: dict[str, str] = {}
    for svc in service_map.get("services", []):
        sid = svc.get("service_id", svc.get("name", ""))
        svc_domain = svc.get("domain", sid)
        domain = _domain_from_service_id(svc_domain if svc_domain else sid)
        for ev in svc.get("events_published", []):
            publisher_map[ev] = domain
    return publisher_map


# ---------------------------------------------------------------------------
# Dockerfile templates for fallback generation when builders don't create one
# ---------------------------------------------------------------------------

_FASTAPI_DOCKERFILE_TEMPLATE = """\
FROM python:3.12-slim-bookworm
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc libpq-dev && \\
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN if [ -d "alembic" ] || [ -d "migrations" ]; then \\
    if [ ! -f "alembic.ini" ]; then \\
        echo "[alembic]" > alembic.ini && \\
        echo "script_location = alembic" >> alembic.ini && \\
        echo "sqlalchemy.url = %%(DATABASE_URL)s" >> alembic.ini; \\
    fi; fi

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/{service_id}/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

_NESTJS_DOCKERFILE_TEMPLATE = """\
FROM node:20-slim AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY tsconfig*.json ./
COPY nest-cli.json* ./
COPY src/ ./src/
RUN npm run build

FROM node:20-slim
WORKDIR /app

COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\
    CMD node -e "const http = require('http'); http.get('http://127.0.0.1:8080/api/{service_id}/health', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "dist/main.js"]
"""

_GENERIC_DOCKERFILE_TEMPLATE = """\
FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\
    CMD wget -qO- http://127.0.0.1:8080/api/{service_id}/health || exit 1
CMD ["node", "dist/main.js"]
"""


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
    # Build failure memory context (no-op when persistence disabled)
    failure_context = ""
    try:
        from src.persistence.context_builder import build_failure_context
        from src.persistence.run_tracker import RunTracker
        from src.persistence.pattern_store import PatternStore

        if getattr(config.persistence, "enabled", False):
            _tracker = RunTracker(config.persistence.db_path)
            _pstore = PatternStore(config.persistence.chroma_path)
            tech_stack = ""
            if isinstance(service_info.stack, dict):
                lang = service_info.stack.get("language", "")
                fw = service_info.stack.get("framework", "")
                tech_stack = f"{lang}/{fw}" if fw else lang
            elif isinstance(service_info.stack, str):
                tech_stack = service_info.stack
            failure_context = build_failure_context(
                service_info.service_id, tech_stack, config, _pstore, _tracker,
            )
    except Exception as exc:
        logger.debug("Failure context injection skipped: %s", exc)

    # Read ACCEPTANCE_TESTS.md if it was generated for this service
    acceptance_test_requirements = ""
    acceptance_md = output_dir / "ACCEPTANCE_TESTS.md"
    try:
        if acceptance_md.exists():
            acceptance_test_requirements = (
                "\n\n"
                "================================================\n"
                "ACCEPTANCE TEST REQUIREMENTS\n"
                "================================================\n"
                + acceptance_md.read_text(encoding="utf-8")
                + "\n================================================\n"
            )
    except Exception as exc:
        logger.debug("Acceptance test injection skipped: %s", exc)

    # ---- FIX-6/7: Enrich config with entities, state machines, contracts ----
    # Load domain model to get entity details and state machines
    entities_for_service: list[dict[str, Any]] = []
    state_machines_for_service: list[dict[str, Any]] = []
    events_published: list[str] = []
    events_subscribed: list[str] = []

    # We need is_frontend early to decide entity loading strategy (Fix 3)
    # Pre-read is_frontend from service map before loading domain model
    is_frontend = False
    try:
        if state.service_map_path and Path(state.service_map_path).exists():
            _smap_pre = load_json(state.service_map_path)
            for _svc_pre in _smap_pre.get("services", []):
                _sid_pre = _svc_pre.get("service_id", _svc_pre.get("name", ""))
                if _sid_pre == service_info.service_id:
                    is_frontend = bool(_svc_pre.get("is_frontend", False))
                    break
    except Exception:
        pass

    try:
        if state.domain_model_path and Path(state.domain_model_path).exists():
            domain_model = load_json(state.domain_model_path)
            dm_entities = domain_model.get("entities", [])
            # Populate top-level state_machines if empty (they live in entities)
            if not domain_model.get("state_machines"):
                _top_sms = []
                for _ent in dm_entities:
                    _sm = _ent.get("state_machine")
                    if _sm and isinstance(_sm, dict):
                        _top_sms.append({"entity": _ent.get("name", ""), **_sm})
                if _top_sms:
                    domain_model["state_machines"] = _top_sms
                    logger.info("Populated %d top-level state machines from entities", len(_top_sms))
            if is_frontend:
                # Fix 3: Frontend gets ALL entities (for type definitions / API clients)
                for ent in dm_entities:
                    ent_dict: dict[str, Any] = {
                        "name": ent.get("name", ""),
                        "description": ent.get("description", ""),
                        "fields": ent.get("fields", []),
                    }
                    entities_for_service.append(ent_dict)
                    sm = ent.get("state_machine")
                    if sm:
                        state_machines_for_service.append({
                            "entity": ent.get("name", ""),
                            **sm,
                        })
            else:
                for ent in dm_entities:
                    owning = ent.get("owning_service", "")
                    _owning_norm = _normalize_service_name(owning)
                    _sid_norm = _normalize_service_name(service_info.service_id)
                    _domain_norm = _normalize_service_name(service_info.domain) if service_info.domain else ""
                    if _owning_norm == _sid_norm or _owning_norm == _domain_norm or _owning_norm == _sid_norm.removesuffix("-service") or _sid_norm == _owning_norm.removesuffix("-service"):
                        ent_dict = {
                            "name": ent.get("name", ""),
                            "description": ent.get("description", ""),
                            "fields": ent.get("fields", []),
                        }
                        entities_for_service.append(ent_dict)
                        sm = ent.get("state_machine")
                        if sm:
                            state_machines_for_service.append({
                                "entity": ent.get("name", ""),
                                **sm,
                            })
    except Exception as exc:
        logger.debug("Domain model enrichment skipped: %s", exc)

    # Extract business rules from domain model if present
    business_rules: list[str] = []
    try:
        if state.domain_model_path and Path(state.domain_model_path).exists():
            domain_model = load_json(state.domain_model_path)
            # Look for business_rules in domain model
            dm_rules = domain_model.get("business_rules", [])
            if isinstance(dm_rules, list):
                for rule in dm_rules:
                    if isinstance(rule, dict):
                        rule_text = rule.get("description", rule.get("rule", ""))
                        rule_svc = rule.get("service", rule.get("service_id", ""))
                        if (not rule_svc) or _normalize_service_name(rule_svc) == _normalize_service_name(service_info.service_id) or _normalize_service_name(rule_svc) == _normalize_service_name(service_info.service_id).removesuffix("-service"):
                            business_rules.append(str(rule_text))
                    elif isinstance(rule, str):
                        business_rules.append(rule)
    except Exception:
        pass

    # Determine is_frontend from service map (already pre-read above)
    # Re-read for contracts and events
    provides_contracts: list[str] = []
    consumes_contracts: list[str] = []
    try:
        if state.service_map_path and Path(state.service_map_path).exists():
            smap = load_json(state.service_map_path)
            for svc in smap.get("services", []):
                sid = svc.get("service_id", svc.get("name", ""))
                if sid == service_info.service_id:
                    is_frontend = bool(svc.get("is_frontend", False))
                    provides_contracts = svc.get("provides_contracts", [])
                    consumes_contracts = svc.get("consumes_contracts", [])
                    events_published = svc.get("events_published", [])
                    events_subscribed = svc.get("events_subscribed", [])
                    # Enrich from PRD catalog if architect didn't parse events
                    if not events_published and not events_subscribed:
                        events_published, events_subscribed = _get_events_for_service(service_info.service_id)
                        if events_published or events_subscribed:
                            logger.info(
                                "Enriched %s with %d published + %d subscribed events from PRD catalog",
                                service_info.service_id, len(events_published), len(events_subscribed),
                            )
                    break
    except Exception as exc:
        logger.debug("Service map enrichment skipped: %s", exc)

    # ---- Normalize event names to {domain}.{entity}.{action} convention ----
    if events_published or events_subscribed:
        own_domain = _domain_from_service_id(
            service_info.domain if service_info.domain else service_info.service_id
        )
        # Published events: prefix with the current service's domain
        events_published = [
            _normalize_event_name(ev, own_domain) for ev in events_published
        ]
        # Subscribed events: prefix with the *publisher's* domain when known
        if events_subscribed:
            try:
                pub_map: dict[str, str] = {}
                if state.service_map_path and Path(state.service_map_path).exists():
                    pub_map = _build_event_publisher_map(
                        load_json(state.service_map_path)
                    )
                normalized_sub: list[str] = []
                for ev in events_subscribed:
                    pub_domain = pub_map.get(ev)
                    if pub_domain:
                        normalized_sub.append(
                            _normalize_event_name(ev, pub_domain)
                        )
                    else:
                        # Publisher unknown — fall back to subscriber's domain
                        normalized_sub.append(
                            _normalize_event_name(ev, own_domain)
                        )
                events_subscribed = normalized_sub
            except Exception as exc:
                logger.debug("Event subscription normalization skipped: %s", exc)

    # Load contract specs for this service (FIX-7)
    contracts: dict[str, Any] = {}
    cross_service_contracts: dict[str, Any] = {}
    registry_dir_path = (
        Path(state.contract_registry_path) if state.contract_registry_path else None
    )
    try:
        if registry_dir_path and registry_dir_path.is_dir():
            for suffix in ("-openapi.json", "-asyncapi.json", ".json"):
                cfile = registry_dir_path / f"{service_info.service_id}{suffix}"
                if cfile.exists():
                    ctype = "asyncapi" if "asyncapi" in suffix else "openapi"
                    spec_data = load_json(cfile)
                    if spec_data:
                        contracts[ctype] = spec_data
            for consumed_name in consumes_contracts:
                consumed_sid = consumed_name.replace("-api", "")
                for suffix in ("-openapi.json", "-asyncapi.json", ".json"):
                    cfile = registry_dir_path / f"{consumed_sid}{suffix}"
                    if cfile.exists():
                        ctype = "asyncapi" if "asyncapi" in suffix else "openapi"
                        spec_data = load_json(cfile)
                        if spec_data:
                            cross_service_contracts.setdefault(
                                consumed_sid, {}
                            )[ctype] = spec_data
                        break
            # Write contract files to the builder's output directory
            contracts_dir = output_dir / "contracts"
            contracts_dir.mkdir(parents=True, exist_ok=True)
            for ctype, cspec in contracts.items():
                cpath = contracts_dir / f"{ctype}.json"
                atomic_write_json(cpath, cspec)
            for consumed_sid, cspecs in cross_service_contracts.items():
                for ctype, cspec in cspecs.items():
                    cpath = contracts_dir / f"{consumed_sid}_{ctype}.json"
                    atomic_write_json(cpath, cspec)
    except Exception as exc:
        logger.debug("Contract enrichment skipped: %s", exc)

    # Look up Graph RAG context using both service_id and service name
    # to handle potential service_id/name mismatch (FIX-8)
    graph_rag_contexts = state.phase_artifacts.get("graph_rag_contexts", {})
    graph_rag_context = graph_rag_contexts.get(service_info.service_id, "")
    if not graph_rag_context:
        graph_rag_context = graph_rag_contexts.get(service_info.domain, "")
    if not graph_rag_context:
        for key, val in graph_rag_contexts.items():
            if (
                key.replace("-", "").lower()
                == service_info.service_id.replace("-", "").lower()
            ):
                graph_rag_context = val
                break

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
        "graph_rag_context": graph_rag_context,
        "failure_context": failure_context,
        "acceptance_test_requirements": acceptance_test_requirements,
        # FIX-6: Entity & state machine enrichment
        "entities": entities_for_service,
        "state_machines": state_machines_for_service,
        "is_frontend": is_frontend,
        "provides_contracts": provides_contracts,
        "consumes_contracts": consumes_contracts,
        "events_published": events_published,
        "events_subscribed": events_subscribed,
        # FIX-7: Contract specs
        "contracts": contracts,
        "cross_service_contracts": cross_service_contracts,
        # Business rules from domain model
        "business_rules": business_rules,
    }

    # FIX-6: Frontend-specific config additions
    if is_frontend:
        config_dict["pages"] = []
        api_urls: dict[str, str] = {}
        try:
            if state.service_map_path and Path(state.service_map_path).exists():
                smap = load_json(state.service_map_path)
                for svc in smap.get("services", []):
                    sid = svc.get("service_id", svc.get("name", ""))
                    if sid != service_info.service_id and not svc.get(
                        "is_frontend", False
                    ):
                        port = svc.get("port", 8080)
                        api_urls[sid] = f"http://{sid}:{port}"
        except Exception:
            pass
        config_dict["api_urls"] = api_urls

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
    except (asyncio.CancelledError, BaseException) as exc:
        logger.warning("MCP architect call failed: %s -- trying subprocess", exc)
        print(f"  [architect] MCP call failed ({type(exc).__name__}), falling back to subprocess")
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
            # Fix 16: Handle wrapper format {type, service_id, spec} and
            # unwrap to get the pure OpenAPI/AsyncAPI spec for validation.
            for idx, stub in enumerate(loaded_stubs):
                if not isinstance(stub, dict):
                    continue
                # Detect wrapper format: has "service_id" + "spec" keys
                if "service_id" in stub and "spec" in stub:
                    inner_spec = stub["spec"]
                    svc_id = stub["service_id"]
                    contract_stubs[svc_id] = inner_spec
                    normalized = svc_id.lower().replace(" ", "-")
                    if normalized != svc_id:
                        contract_stubs[normalized] = inner_spec
                else:
                    # Legacy flat format: strip leaked metadata keys
                    inner_spec = {
                        k: v for k, v in stub.items()
                        if k not in ("service_id", "type")
                    } if ("service_id" in stub or "type" in stub) else stub
                    info = inner_spec.get("info", {})
                    title = info.get("title", "").lower().replace(" api", "").strip()
                    if title:
                        contract_stubs[title] = inner_spec
                    inner_spec = inner_spec  # for fallback index below
                # Also store by index for fallback
                contract_stubs[f"service_{idx}"] = inner_spec
        else:
            contract_stubs = loaded_stubs

    services = service_map.get("services", [])
    registered = []
    mcp_disabled = False  # Fast-fail: skip MCP after first CancelledError

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

        # Fix 16: Strip non-OpenAPI metadata keys that cause validation errors
        if "service_id" in spec or "type" in spec:
            spec = {k: v for k, v in spec.items() if k not in ("service_id", "type")}

        # Fast-fail: if MCP already failed with CancelledError, skip to filesystem
        if mcp_disabled:
            contract_file = registry_dir / f"{service_name}.json"
            atomic_write_json(contract_file, spec)
            registered.append({"service_name": service_name, "status": "filesystem", "id": ""})
            print(f"  [contract-reg] {service_name} -> filesystem (MCP disabled)")
            continue

        try:
            result = await _register_single_contract(
                service_name, spec, config
            )
            # Check if MCP returned a fallback (CancelledError was caught inside)
            if result.get("status") == "fallback":
                mcp_disabled = True
                print(f"  [contract-reg] {service_name} -> MCP fallback, disabling MCP for remaining")
                contract_file = registry_dir / f"{service_name}.json"
                atomic_write_json(contract_file, spec)
            registered.append(result)
            logger.info("Registered contract for %s", service_name)
        except ConfigurationError:
            # INT-002: MCP unavailable -- fall back to filesystem
            mcp_disabled = True
            logger.warning(
                "Contract Engine MCP unavailable for %s -- saving to filesystem",
                service_name,
            )
            contract_file = registry_dir / f"{service_name}.json"
            atomic_write_json(contract_file, spec)
        except BaseException as exc:
            mcp_disabled = True
            logger.warning(
                "Failed to register contract for %s: %s -- saving to filesystem",
                service_name,
                exc,
            )
            # Filesystem fallback (covers CancelledError from MCP)
            contract_file = registry_dir / f"{service_name}.json"
            atomic_write_json(contract_file, spec)

    # FIX-4: Generate Schemathesis test files for each registered contract.
    # Best-effort -- failures never crash the pipeline.
    # NOTE: Schemathesis MCP generate_tests corrupts anyio cancel scopes,
    # causing CancelledError to propagate to subsequent pipeline phases.
    # Run generation in a subprocess-isolated way to prevent contamination.
    generated_test_files: list[str] = []
    test_services: list[str] = []
    schemathesis_mcp_ok = True  # Fast-fail on first MCP failure
    for reg_result in registered:
        _svc_name_4 = reg_result.get("service_name", "?")
        try:
            contract_id = reg_result.get("id", "")
            svc_name = reg_result.get("service_name", "")
            if not contract_id or not svc_name:
                continue

            if not schemathesis_mcp_ok:
                logger.debug("Skipping Schemathesis for %s (MCP disabled)", svc_name)
                continue

            from src.contract_engine.mcp_client import (
                generate_tests as _gen_tests,
            )

            test_code = await _gen_tests(
                contract_id=contract_id,
                framework="pytest",
                include_negative=False,
            )
            if test_code and not test_code.startswith("{"):
                test_dir = Path(config.output_dir) / "tests" / "contract"
                test_dir.mkdir(parents=True, exist_ok=True)
                test_file = test_dir / f"test_schemathesis_{svc_name}.py"
                test_file.write_text(test_code, encoding="utf-8")
                generated_test_files.append(str(test_file))
                test_services.append(svc_name)
                logger.info(
                    "Generated Schemathesis tests for %s at %s",
                    svc_name, test_file,
                )
        except (asyncio.CancelledError, KeyboardInterrupt):
            schemathesis_mcp_ok = False
            logger.info(
                "[schemathesis] %s failed (known MCP cancel scope issue), "
                "continuing without property-based tests",
                _svc_name_4,
            )
        except BaseException as exc:
            schemathesis_mcp_ok = False
            logger.info(
                "[schemathesis] %s failed (%s), "
                "continuing without property-based tests",
                _svc_name_4,
                type(exc).__name__,
            )

    # FIX-5: Generate Pact contract files for cross-service dependencies.
    # Best-effort -- failures never crash the pipeline.
    pact_files_generated: list[str] = []
    try:
        pact_files_generated = _generate_pact_files(
            registry_dir, service_map, contract_stubs, registered,
        )
        if pact_files_generated:
            logger.info(
                "Generated %d Pact contract file(s) in %s/pacts/",
                len(pact_files_generated), registry_dir,
            )
    except Exception as exc:
        logger.warning("Pact file generation failed (non-fatal): %s", exc)

    state.phase_artifacts[PHASE_CONTRACT_REGISTRATION] = {
        "registered_contracts": len(registered),
        "registry_path": str(registry_dir),
        "generated_test_files": generated_test_files,
        "test_services": test_services,
        "pact_files": pact_files_generated,
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


def _generate_pact_files(
    registry_dir: Path,
    service_map: dict,
    contract_stubs: dict[str, Any],
    registered: list[dict[str, Any]],
) -> list[str]:
    """Generate Pact v3 JSON files for cross-service dependencies.

    Creates consumer-driven contract files in ``{registry_dir}/pacts/``
    by examining cross-service relationships in the service map.

    Returns a list of generated pact file paths.
    """
    pacts_dir = registry_dir / "pacts"
    pacts_dir.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []

    services = service_map.get("services", [])
    if not isinstance(services, list):
        return generated

    # Build a mapping of service_id -> OpenAPI spec for quick lookup
    spec_by_service: dict[str, dict[str, Any]] = {}
    for reg in registered:
        svc_name = reg.get("service_name", "")
        if svc_name:
            spec_file = registry_dir / f"{svc_name}.json"
            if spec_file.exists():
                try:
                    spec_by_service[svc_name] = load_json(spec_file)
                except Exception:
                    pass

    for svc in services:
        if not isinstance(svc, dict):
            continue
        consumer_name = svc.get("service_id", svc.get("name", ""))
        consumes = svc.get("consumes_contracts", [])
        if not consumer_name or not consumes:
            continue

        for consumed_contract in consumes:
            provider_name = consumed_contract.replace("-api", "")
            provider_spec = spec_by_service.get(provider_name, {})

            interactions: list[dict[str, Any]] = []
            paths = provider_spec.get("paths", {})
            for path, methods in paths.items():
                if not isinstance(methods, dict):
                    continue
                for method, operation in methods.items():
                    if method.startswith("x-") or method == "parameters":
                        continue
                    if not isinstance(operation, dict):
                        continue

                    responses = operation.get("responses", {})
                    expected_status = 200
                    expected_body: dict[str, Any] = {}
                    for status_code in ("200", "201", "204"):
                        if status_code in responses:
                            expected_status = int(status_code)
                            resp_def = responses[status_code]
                            if isinstance(resp_def, dict):
                                content = resp_def.get("content", {})
                                json_content = content.get(
                                    "application/json", {}
                                )
                                schema = json_content.get("schema", {})
                                if schema:
                                    expected_body = {"schema": schema}
                            break

                    interaction: dict[str, Any] = {
                        "description": (
                            f"{consumer_name} calls "
                            f"{method.upper()} {path}"
                        ),
                        "providerState": (
                            f"{provider_name} has default data"
                        ),
                        "request": {
                            "method": method.upper(),
                            "path": path,
                        },
                        "response": {
                            "status": expected_status,
                            "headers": {
                                "Content-Type": "application/json",
                            },
                        },
                    }
                    if expected_body:
                        interaction["response"]["body"] = expected_body
                    interactions.append(interaction)

            if not interactions:
                continue

            pact_doc: dict[str, Any] = {
                "consumer": {"name": consumer_name},
                "provider": {"name": provider_name},
                "interactions": interactions,
                "metadata": {
                    "pactSpecification": {"version": "3.0.0"},
                },
            }

            pact_file = pacts_dir / f"{consumer_name}-{provider_name}.json"
            try:
                pact_file.write_text(
                    json.dumps(pact_doc, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                generated.append(str(pact_file))
            except OSError as exc:
                logger.warning(
                    "Failed to write pact file %s: %s", pact_file, exc,
                )

    return generated


async def _register_single_contract(
    service_name: str,
    spec: dict[str, Any],
    config: SuperOrchestratorConfig,
) -> dict[str, Any]:
    """Register a single contract via MCP, with fallback."""
    # Fix 16: Strip non-OpenAPI metadata keys (service_id, type) that the
    # contract generator injects for indexing.  These cause "Unevaluated
    # properties are not allowed" validation errors.
    clean_spec = {
        k: v for k, v in spec.items()
        if k not in ("service_id", "type")
    }
    try:
        from src.contract_engine.mcp_client import (  # type: ignore[import-untyped]
            create_contract,
            list_contracts,
            validate_spec,
        )

        # Validate first
        validation = await validate_spec(spec=clean_spec, type="openapi")
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
            spec=clean_spec,
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
    except (asyncio.CancelledError, BaseException) as exc:
        logger.warning(
            "MCP call cancelled/crashed for %s: %s -- falling back",
            service_name,
            type(exc).__name__,
        )
        return {"service_name": service_name, "status": "fallback", "id": ""}


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
    print("  [builders] Starting parallel builders")
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


# ---------------------------------------------------------------------------
# Builder CLAUDE.md injection — bridge enrichment data to the subprocess
# ---------------------------------------------------------------------------

_STACK_INSTRUCTIONS: dict[str, str] = {
    "python": (
        "## Framework Requirements: FastAPI/Python\n\n"
        "### Dependencies (MUST be in requirements.txt)\n"
        "- fastapi>=0.100.0\n"
        "- uvicorn[standard]>=0.23.0\n"
        "- sqlalchemy[asyncio]>=2.0\n"
        "- asyncpg>=0.28.0\n"
        "- alembic>=1.12.0\n"
        "- pydantic>=2.0\n"
        "- pydantic[email]\n"
        "- email-validator\n"
        "- python-jose[cryptography]\n"
        "- passlib[bcrypt]\n"
        "- httpx\n"
        "- redis>=5.0\n\n"
        "### Database Connection\n"
        "- Use `postgresql+asyncpg://` scheme (NOT `postgresql://`)\n"
        "- Read DATABASE_URL from environment variable\n"
        "- All DB operations via async SQLAlchemy sessions\n\n"
        "### Alembic Setup (MANDATORY)\n"
        "- Create `alembic.ini` at project root with [alembic] section\n"
        "- Create `alembic/env.py` that reads DATABASE_URL from environment\n"
        "- Create `alembic/versions/` directory\n\n"
        "### Health Endpoint (MANDATORY)\n"
        "- Create `GET /api/{service-name}/health` endpoint\n"
        "- Must return {\"status\": \"healthy\", \"service\": \"{service-name}\", \"timestamp\": \"...\"} with HTTP 200\n"
        "- This endpoint is used by Docker HEALTHCHECK — it MUST work\n\n"
        "### Project Structure\n"
        "main.py              — FastAPI app entry point (uvicorn target)\n"
        "requirements.txt     — All dependencies listed above\n"
        "alembic.ini          — Alembic configuration\n"
        "alembic/env.py       — Alembic env (reads DATABASE_URL)\n"
        "alembic/versions/    — Migration scripts\n"
        "src/models/          — SQLAlchemy models\n"
        "src/routes/          — FastAPI route handlers\n"
        "src/services/        — Business logic services\n"
        "src/schemas/         — Pydantic request/response schemas\n"
        "src/middleware/       — Auth, CORS, logging middleware\n\n"
        "### Testing (MANDATORY)\n"
        "- Add `pytest`, `httpx`, `pytest-asyncio` to requirements-dev.txt (or requirements.txt)\n"
        "- Create `pytest.ini` or `pyproject.toml` with `[tool.pytest.ini_options]`\n"
        "- Create `tests/conftest.py` with database fixtures (use in-memory SQLite for tests)\n"
        "- Create `tests/test_*.py` files for EVERY module (models, routes, services, state machines)\n"
        "- Every test file MUST have meaningful assertions — no trivial 'assert True' tests\n"
        "- Minimum: 5 test files, 20+ test cases total, at least 3 tests per endpoint (happy path, validation error, auth/tenant error)\n\n"
        "### Migrations (MANDATORY)\n"
        "- You MUST create at least one Alembic migration in `alembic/versions/`\n"
        "- Do NOT use `Base.metadata.create_all()` — use Alembic migrations exclusively\n\n"
    ),
    "typescript": (
        "## Framework Requirements: NestJS/TypeScript\n\n"
        "### Dependencies (MUST be in package.json)\n"
        "- @nestjs/core, @nestjs/common, @nestjs/platform-express\n"
        "- @nestjs/typeorm, typeorm, pg\n"
        "- @nestjs/jwt, @nestjs/passport, passport, passport-jwt\n"
        "- @nestjs/config\n"
        "- class-validator, class-transformer\n"
        "- @nestjs/swagger\n\n"
        "### Dependency Injection (CRITICAL — READ CAREFULLY)\n"
        "- Every module that uses JwtAuthGuard MUST import AuthModule\n"
        "- If OrdersModule has a controller with @UseGuards(JwtAuthGuard), then OrdersModule MUST have imports: [AuthModule]\n"
        "- Every @Injectable service MUST be in its module's providers array\n"
        "- Every module MUST properly import required modules\n"
        "- Use @Module({ imports: [...], controllers: [...], providers: [...], exports: [...] }) pattern\n\n"
        "### Database Connection\n"
        "- Use individual env vars: DB_HOST, DB_PORT, DB_USERNAME, DB_PASSWORD, DB_DATABASE\n"
        "- TypeORM config in app.module.ts reads from ConfigService\n"
        "- Set synchronize: false in production\n\n"
        "### Health Endpoint (MANDATORY)\n"
        "- Create GET /api/{service-name}/health endpoint via HealthController\n"
        "- Must return {\"status\": \"healthy\", \"service\": \"{service-name}\", \"timestamp\": \"...\"} with HTTP 200\n"
        "- Register HealthModule in AppModule imports\n\n"
        "### Port Configuration\n"
        "- Listen on port from PORT env var, default 8080: await app.listen(process.env.PORT || 8080)\n"
        "- Do NOT use 3000 — use 8080 to match Docker HEALTHCHECK\n\n"
        "### Project Structure\n"
        "src/main.ts            — Bootstrap (listen on PORT || 8080)\n"
        "src/app.module.ts      — Root module with TypeORM, Auth, Health\n"
        "src/auth/              — AuthModule with JwtStrategy, JwtAuthGuard\n"
        "src/health/            — HealthModule with HealthController\n"
        "src/{domain}/          — Feature modules\n"
        "package.json\n"
        "tsconfig.json\n"
        "tsconfig.build.json\n"
        "nest-cli.json\n\n"
        "### Testing (MANDATORY)\n"
        "- Add `jest`, `@nestjs/testing`, `supertest` to devDependencies\n"
        "- Create `jest.config.ts` with proper moduleNameMapper\n"
        "- Add `\"test\": \"jest --coverage\"` to package.json scripts\n"
        "- Create `src/**/*.spec.ts` unit tests for every service\n"
        "- Create `test/*.e2e-spec.ts` e2e tests for every controller\n"
        "- Every test MUST have meaningful assertions\n"
        "- Minimum: 5 .spec.ts files, 20+ test cases total, at least 3 tests per controller method\n\n"
        "### Migrations (MANDATORY)\n"
        "- Create at least one migration in `src/database/migrations/`\n"
        "- Set `synchronize: false` (NOT conditional on NODE_ENV)\n"
        "- Use the DataSource CLI for migration generation\n\n"
        "### Redis Events (MANDATORY)\n"
        "- Add `ioredis` to dependencies for Redis Pub/Sub\n"
        "- Create `src/events/` module for event publishing and subscribing\n\n"
    ),
    "frontend": (
        "## Framework Requirements: Angular 18\n\n"
        "### What You MUST Create\n"
        "- Angular standalone components for each page/feature\n"
        "- TypeScript interfaces matching ALL entity schemas\n"
        "- HTTP service classes consuming ALL backend APIs\n"
        "- Angular Router with lazy-loaded feature modules\n"
        "- Reactive Forms for all CRUD operations\n"
        "- JWT authentication interceptor\n"
        "- Environment configuration with API base URLs\n"
        "- Dockerfile (multi-stage: node build -> nginx serve)\n"
        "- package.json with Angular 18+ dependencies\n"
        "- Unit tests (.spec.ts) for ALL services and components (MANDATORY — not optional)\n"
        "- jest.config.ts or karma.conf.js for test runner\n"
        "- `\"test\"` script in package.json\n\n"
        "### CRITICAL: Do NOT Create Backend Code\n"
        "- Do NOT create any Python (.py) files\n"
        "- Do NOT create a `services/` directory with backend implementations\n"
        "- Do NOT create docker-compose.yml\n"
        "- Your output is ONLY the frontend application\n\n"
        "### API Proxy\n"
        "- All API calls go to /api/{service-name}/...\n"
        "- Traefik handles routing — frontend nginx proxies /api/ to http://traefik:80\n"
        "- Environment config: apiBaseUrl: '/api'\n\n"
        "### Dockerfile (MANDATORY)\n"
        "- Multi-stage build: node:20-slim for build, nginx:stable-alpine for serve\n"
        "- Angular SSR is NOT required — client-side SPA only\n"
    ),
}


def _detect_stack_category(stack: dict[str, str] | str | None) -> str:
    """Categorise a stack dict into python / typescript / frontend."""
    if not stack or not isinstance(stack, dict):
        return "python"
    language = (stack.get("language") or "").lower()
    framework = (stack.get("framework") or "").lower()

    frontend_frameworks = {
        "angular", "react", "vue", "next", "nextjs", "nuxt", "svelte",
    }
    if framework in frontend_frameworks or language in frontend_frameworks:
        return "frontend"
    if language in ("typescript", "javascript", "node", "nodejs"):
        return "typescript"
    if framework in ("nestjs", "nest", "express", "koa", "hapi", "fastify"):
        return "typescript"
    return "python"


def _write_builder_claude_md(
    output_dir: Path,
    builder_config: dict[str, Any],
) -> Path:
    """Write a ``.claude/CLAUDE.md`` in the builder output directory.

    The file contains all enrichment data (tech stack, entities, state
    machines, events, contracts, cross-service deps) so that the builder
    subprocess has full service context.

    When agent-team-v15's ``write_teammate_claude_md()`` runs later inside
    the builder subprocess, it will find this file and **append** its own
    generated role instructions after our content (because the file
    will not yet contain the ``<!-- AGENT-TEAMS:BEGIN -->`` markers).

    Parameters
    ----------
    output_dir :
        The builder's working directory (``{config.output_dir}/{service_id}``).
    builder_config :
        The enriched config dict produced by ``generate_builder_config()``.

    Returns
    -------
    Path
        Path to the written ``.claude/CLAUDE.md`` file.
    """
    service_id = builder_config.get("service_id", "unknown")
    domain = builder_config.get("domain", "")
    stack = builder_config.get("stack", {})
    port = builder_config.get("port", 8080)

    # Determine tech stack details
    if isinstance(stack, dict):
        language = stack.get("language", "python")
        framework = stack.get("framework", "")
        database = stack.get("database", "PostgreSQL")
    else:
        language = str(stack) if stack else "python"
        framework = ""
        database = "PostgreSQL"

    stack_category = _detect_stack_category(stack)
    is_frontend_svc = bool(builder_config.get("is_frontend", False))

    # Override stack category to "frontend" when is_frontend is True
    if is_frontend_svc:
        stack_category = "frontend"

    stack_instructions = _STACK_INSTRUCTIONS.get(stack_category, _STACK_INSTRUCTIONS["python"])

    schema_name = service_id.replace("-", "_") + "_schema"

    lines: list[str] = []
    lines.append(f"# Service Context: {service_id}\n")

    if is_frontend_svc:
        # Fix 5: Explicit frontend warning and guidance
        lines.append("## *** THIS IS A FRONTEND SERVICE ***\n")
        lines.append(
            "This service is a **frontend/UI application**. "
            "It does NOT create database tables, REST API endpoints, or backend logic.\n"
        )
        lines.append("## Technology Stack\n")
        lines.append(f"- **Language:** {language}")
        if framework:
            lines.append(f"- **Framework:** {framework}")
        lines.append(f"- **Port:** {port}")
        lines.append("")

        lines.append(f"## THIS SERVICE MUST USE {language}")
        if framework:
            lines[-1] += f" / {framework}"
        lines.append("")
        lines.append(stack_instructions)

        # Framework-specific guidance
        fw_lower = framework.lower() if framework else ""
        if "angular" in fw_lower:
            lines.append("## Angular-Specific Requirements\n")
            lines.append("- Use **standalone components** (NO NgModules)")
            lines.append("- Use `HttpClient` from `@angular/common/http` for API calls")
            lines.append("- Use `Router` from `@angular/router` for navigation")
            lines.append("- Use `ReactiveFormsModule` for form handling")
            lines.append("- Create an HTTP interceptor for JWT token injection")
            lines.append("- Use `environment.ts` for API base URLs")
            lines.append("- Implement lazy-loaded routes for each feature module")
            lines.append("")
        elif "react" in fw_lower or "next" in fw_lower:
            lines.append("## React-Specific Requirements\n")
            lines.append("- Use functional components with hooks")
            lines.append("- Use `fetch` or `axios` for API calls")
            lines.append("- Use React Router for navigation")
            lines.append("- Create auth context/provider for JWT management")
            lines.append("")
        elif "vue" in fw_lower or "nuxt" in fw_lower:
            lines.append("## Vue-Specific Requirements\n")
            lines.append("- Use Composition API with `<script setup>`")
            lines.append("- Use `fetch` or `axios` for API calls")
            lines.append("- Use Vue Router for navigation")
            lines.append("")

        lines.append("## What You MUST Create\n")
        lines.append("- UI components for each entity (list, detail, create, edit)")
        lines.append("- API service/client layer to call backend endpoints")
        lines.append("- TypeScript interfaces matching all entity schemas")
        lines.append("- Routing configuration for all pages")
        lines.append("- Authentication interceptor/guard for JWT tokens")
        lines.append("- Form validation matching entity field requirements")
        lines.append("- **Dockerfile** serving the built app via nginx (multi-stage: node build + nginx serve)")
        lines.append("- package.json with framework dependencies")
        lines.append("- Unit tests for all services and key components")
        lines.append("")

        lines.append("## What You Must NOT Create (VIOLATIONS WILL BE DELETED)\n")
        lines.append("- **NO Python files** (.py) anywhere in your output")
        lines.append("- **NO backend service implementations** (no Express, FastAPI, NestJS server code)")
        lines.append("- **NO `services/` directory** with backend code")
        lines.append("- **NO docker-compose.yml** files (the pipeline generates these)")
        lines.append("- **NO database models**, migrations, or ORM entities")
        lines.append("- **NO database seed data** or mock data files")
        lines.append("- **NO SQLAlchemy, TypeORM, or Prisma code**")
        lines.append("")
        lines.append("Your ENTIRE output should be a single frontend application.")
        lines.append("The backend services are built by SEPARATE processes — do NOT duplicate them.")
        lines.append("")

        # API URLs from builder config
        api_urls = builder_config.get("api_urls", {})
        if api_urls:
            lines.append("## Backend API Base URLs\n")
            for api_sid, api_url in api_urls.items():
                lines.append(f"- **{api_sid}:** `{api_url}`")
            lines.append("")
    else:
        # Normal backend service
        lines.append("## Technology Stack\n")
        lines.append(f"- **Language:** {language}")
        if framework:
            lines.append(f"- **Framework:** {framework}")
        lines.append(f"- **Database:** {database or 'PostgreSQL'} (schema: `{schema_name}`)")
        lines.append(f"- **Port:** {port}")
        lines.append("")

        lines.append(f"## THIS SERVICE MUST USE {language}")
        if framework:
            lines[-1] += f" / {framework}"
        lines.append("")
        lines.append(stack_instructions)

    # ---- Mandatory Deliverables (ALL services) ----
    lines.append("## Mandatory Deliverables (ALL services)\n")
    lines.append("1. Dockerfile — Production-ready, multi-stage where appropriate")
    lines.append(f"2. Health endpoint — GET /api/{service_id}/health returning JSON with status 200")
    lines.append("3. Environment-based config — ALL config via environment variables, NO hardcoded values")
    lines.append("4. .dockerignore — Exclude node_modules, __pycache__, .git, .env, dist, build")
    lines.append("5. No print() statements — Use logging framework (Python: logging, NestJS: Logger)")
    lines.append("6. CORS configured — Allow origins from environment variable")
    lines.append("7. Graceful shutdown — Handle SIGTERM for clean container stop")
    lines.append("8. Rate limiting — Login/auth endpoints: 5 req/min. API endpoints: 100 req/min")
    lines.append("9. Security headers — X-Content-Type-Options: nosniff, X-Frame-Options: DENY")
    lines.append("10. Structured logging — Use logging module (Python) or Logger (NestJS). NO print() or console.log in production code")
    lines.append("11. Global exception handler — Catch all unhandled errors and return consistent JSON error responses")
    lines.append("")

    # ---- Owned Entities / Entity Schemas ----
    entities = builder_config.get("entities", [])
    if entities:
        if is_frontend_svc:
            lines.append("## Entity Schemas (for TypeScript interfaces / API clients)\n")
        else:
            lines.append("## Owned Entities\n")
        for ent in entities:
            ent_name = ent.get("name", "")
            ent_desc = ent.get("description", "")
            lines.append(f"### {ent_name}")
            if ent_desc:
                lines.append(f"{ent_desc}\n")

            fields = ent.get("fields", [])
            if fields:
                field_strs = []
                for f in fields:
                    fname = f.get("name", "")
                    ftype = f.get("type", "unknown")
                    freq = " (required)" if f.get("required", True) else " (optional)"
                    field_strs.append(f"  - `{fname}`: {ftype}{freq}")
                lines.append("**Fields:**")
                lines.extend(field_strs)
                lines.append("")
        lines.append("")

        if not is_frontend_svc:
            lines.append("### Entity Implementation Requirements\n")
            lines.append("For EACH entity listed above:")
            lines.append("- Create a complete ORM model with ALL listed fields")
            lines.append("- Add database index on `tenant_id` and any `status` field")
            lines.append("- Implement FULL CRUD endpoints: list (paginated), get-by-id, create, update")
            lines.append("- Every list endpoint MUST support `?page=&limit=` query parameters")
            lines.append("- Every query MUST filter by `tenant_id` from JWT for multi-tenant isolation")
            lines.append("")

    # ---- State Machines ----
    state_machines = builder_config.get("state_machines", [])
    if state_machines:
        lines.append("## State Machines\n")
        for sm in state_machines:
            sm_entity = sm.get("entity", "")
            states = sm.get("states", [])
            initial = sm.get("initial_state", "")
            transitions = sm.get("transitions", [])
            lines.append(f"### {sm_entity} State Machine")
            if states:
                lines.append(f"- **States:** {', '.join(states)}")
            if initial:
                lines.append(f"- **Initial state:** {initial}")
            if transitions:
                lines.append("- **Transitions:**")
                for tr in transitions:
                    from_s = tr.get("from_state", "")
                    to_s = tr.get("to_state", "")
                    trigger = tr.get("trigger", "")
                    lines.append(f"  - {from_s} -> {to_s} (trigger: {trigger})")
            lines.append("")
        lines.append("")

        lines.append("### State Machine Implementation Requirements\n")
        lines.append("For EACH state machine listed above:")
        lines.append("- Create a `validate_transition(current, target)` function with an explicit allowed-transitions map")
        lines.append("- The PATCH endpoint for status changes MUST call this validator")
        lines.append("- Return HTTP 409 with INVALID_TRANSITION error on invalid transitions")
        lines.append("- Log every successful transition (user_id, timestamp, from_state, to_state)")
        lines.append("- Write tests covering ALL valid transitions AND at least 3 invalid ones")
        lines.append("")

    # ---- Business Rules ----
    business_rules = builder_config.get("business_rules", [])
    if business_rules:
        lines.append("## Business Rules (MUST be enforced in code)\n")
        for i, rule in enumerate(business_rules, 1):
            lines.append(f"{i}. {rule}")
        lines.append("")
        lines.append("Every rule above MUST be implemented as validation logic, guard condition, or calculation — not just documented in comments.")
        lines.append("")

    # ---- Events Published ----
    events_pub = builder_config.get("events_published", [])
    if events_pub:
        lines.append("## Events Published\n")
        lines.append("Publish each event to its own Redis channel using the event name as the channel:\n")
        for ev in events_pub:
            lines.append(f"- Channel: `{ev}` — publish with `redis.publish(\"{ev}\", message)`")
        lines.append("")
        lines.append("**Use the standard event envelope format from the Cross-Service Standards section.**")
        lines.append("")

    # ---- Events Subscribed ----
    events_sub = builder_config.get("events_subscribed", [])
    if events_sub:
        lines.append("## Events Subscribed\n")
        lines.append("Subscribe to each event using the exact channel name below:\n")
        for ev in events_sub:
            lines.append(f"- Channel: `{ev}` — subscribe with `redis.subscribe(\"{ev}\")`")
        lines.append("")
        lines.append("**IMPORTANT:** Each event handler MUST perform a real business action (update DB, create records, trigger workflows). Do NOT create log-only stub handlers.")
        lines.append("")

        # Add specific business logic hints for subscribed events
        _event_logic_hints = {
            "receipt.created": "Create a quality inspection record (Quality), update expected inventory (Inventory), mark shipment items received (Shipping)",
            "order.approved": "Create inventory reservation for ordered items (Inventory), update supplier order status (Supplier)",
            "order.sent": "Create shipment tracking record (Shipping), send PO notification to supplier (Notification)",
            "order.cancelled": "Release inventory reservations (Inventory), cancel pending shipments (Shipping)",
            "stock.low": "Create reorder notification for procurement team (Notification), auto-generate RFQ if threshold breached (Procurement)",
            "shipment.delivered": "Update PO line received quantities (Procurement), create inspection record (Quality)",
            "inspection.completed": "Update supplier quality rating (Supplier), release quarantined stock (Inventory)",
            "inspection.failed": "Create NCR record (Quality), suspend supplier if repeat failures (Supplier)",
            "supplier.suspended": "Flag active POs for review (Procurement), block new reservations (Inventory)",
        }
        relevant_hints = [(ev, _event_logic_hints[ev]) for ev in events_sub if ev in _event_logic_hints]
        if relevant_hints:
            lines.append("### Specific Event Handler Logic\n")
            lines.append("For each subscribed event, implement THIS specific business logic:\n")
            for ev, hint in relevant_hints:
                lines.append(f"- **`{ev}`**: {hint}")
            lines.append("")

    # ---- Cross-Service Dependencies ----
    provides = builder_config.get("provides_contracts", [])
    consumes = builder_config.get("consumes_contracts", [])
    cross_contracts = builder_config.get("cross_service_contracts", {})

    if provides or consumes or cross_contracts:
        lines.append("## Cross-Service Dependencies\n")
        if provides:
            lines.append("**Provides:**")
            for c in provides:
                lines.append(f"- `{c}`")
            lines.append("")
        if consumes:
            lines.append("**Consumes:**")
            for c in consumes:
                lines.append(f"- `{c}`")
            lines.append("")

    # ---- Contract Specifications ----
    own_contracts = builder_config.get("contracts", {})
    if own_contracts:
        lines.append("## Contract Specifications\n")
        for ctype, cspec in own_contracts.items():
            if isinstance(cspec, dict):
                # Inline key endpoint info from OpenAPI spec
                info = cspec.get("info", {})
                title = info.get("title", ctype)
                version = info.get("version", "")
                lines.append(f"### {title}" + (f" v{version}" if version else ""))
                paths = cspec.get("paths", {})
                if paths:
                    lines.append("**Endpoints:**")
                    for path_url, methods in paths.items():
                        if isinstance(methods, dict):
                            for method, details in methods.items():
                                if method.lower() in ("get", "post", "put", "patch", "delete"):
                                    summary = ""
                                    if isinstance(details, dict):
                                        summary = details.get("summary", details.get("operationId", ""))
                                    lines.append(f"- `{method.upper()} {path_url}` — {summary}")
                lines.append("")
        lines.append("")

    if cross_contracts:
        lines.append("## Consumed Service Contracts\n")
        for consumed_sid, cspecs in cross_contracts.items():
            lines.append(f"### {consumed_sid}")
            for ctype, cspec in cspecs.items():
                if isinstance(cspec, dict):
                    paths = cspec.get("paths", {})
                    if paths:
                        for path_url, methods in paths.items():
                            if isinstance(methods, dict):
                                for method, details in methods.items():
                                    if method.lower() in ("get", "post", "put", "patch", "delete"):
                                        lines.append(f"- `{method.upper()} {path_url}`")
            lines.append("")

    # ---- Graph RAG Context ----
    graph_rag = builder_config.get("graph_rag_context", "")
    if graph_rag:
        lines.append("## Service Dependency Graph Context\n")
        lines.append(graph_rag)
        lines.append("")

    # ---- Contract files on disk ----
    lines.append("## Local Contract Files\n")
    lines.append(
        "Contract specification files are available in the `./contracts/` directory.\n"
        "Read these files for detailed API schemas when implementing endpoints.\n"
    )

    # ---- Implementation Notes ----
    lines.append("## Important Implementation Notes\n")
    if is_frontend_svc:
        lines.append("- All API requests must include JWT token (use auth interceptor)")
        lines.append("- Include `tenant_id` in API requests for multi-tenant isolation")
        lines.append(f"- Dev server port: {port}")
    else:
        lines.append(f"- Database schema: `{schema_name}` (use schema-qualified table names)")
        lines.append("- Use Redis Pub/Sub for event publishing/subscribing")
        lines.append("- Each event must include `tenant_id` for multi-tenant isolation")
        lines.append("- All API endpoints must validate JWT tokens via auth-service")
        lines.append(f"- Service port: {port}")
    lines.append("")

    # ---- Lockfile / Dependency Management ----
    if not is_frontend_svc:
        if stack_category == "typescript":
            lines.append("## CRITICAL: Lock Files\n")
            lines.append("- After creating `package.json`, you MUST run `npm install` to generate `package-lock.json`")
            lines.append("- The Dockerfile uses `npm ci` which REQUIRES `package-lock.json` to exist")
            lines.append("- Without it, the Docker build WILL FAIL")
            lines.append("- Verify `package-lock.json` exists before considering the service complete")
            lines.append("")
        else:
            lines.append("## Dependency Management\n")
            lines.append("- `requirements.txt` must list ALL imported packages with version pins")
            lines.append("- Example: `fastapi==0.109.0`, not just `fastapi`")
            lines.append("- Include transitive deps: `uvicorn[standard]`, `asyncpg`, `sqlalchemy[asyncio]`")
            lines.append("")

    # ---- Mandatory Test Requirements ----
    lines.append("## MANDATORY: Test Files\n")
    lines.append("A service without tests is INCOMPLETE and will be REJECTED.\n")
    if is_frontend_svc:
        lines.append("- Create `*.spec.ts` files for each Angular service (HTTP service layer)")
        lines.append("- Create `*.spec.ts` files for at least 5 key page components")
        lines.append("- Use Jasmine + TestBed with proper module imports")
        lines.append("- Each spec file must have >= 3 test cases with real assertions")
        lines.append("- Test HTTP service methods: mock HttpClient, verify request URLs and payloads")
        lines.append("- Test component rendering: verify template elements exist, inputs/outputs work")
    elif stack_category == "typescript":
        lines.append("- Create `*.spec.ts` files for each NestJS service and controller")
        lines.append("- Create `app.e2e-spec.ts` with >= 10 end-to-end test cases")
        lines.append("- Use Jest with `getRepositoryToken()` mocking for TypeORM")
        lines.append("- Each test must assert BOTH response status AND response body content")
        lines.append("- Test all CRUD operations + error cases (404, 409, 422)")
    else:
        lines.append("- Create `tests/` directory with `conftest.py` (fixtures, test client)")
        lines.append("- At minimum: `test_health.py`, `test_{primary_entity}.py`")
        lines.append("- If this service has state machines, create `test_state_machines.py`")
        lines.append("- Use `pytest` + `httpx.AsyncClient` with `app` fixture")
        lines.append("- Each test file must have >= 3 test functions with real assertions")
        lines.append("- Test all CRUD endpoints + state machine transitions + error cases")
    lines.append("")

    # ---- RBAC Enforcement ----
    if not is_frontend_svc:
        lines.append("## Role-Based Access Control\n")
        lines.append("EVERY endpoint that modifies data must enforce role-based access.\n")
        if stack_category == "typescript":
            lines.append("- Create a `@Roles(...roles)` decorator and `RolesGuard`")
            lines.append("- Use `@UseGuards(JwtAuthGuard, RolesGuard)` on protected endpoints")
            lines.append("- Extract role from JWT payload `req.user.role`")
        else:
            lines.append("- Create a `require_role(role: str)` FastAPI dependency")
            lines.append("- Apply to endpoints: `current_user = Depends(require_role('manager'))`")
            lines.append("- Extract role from JWT payload")
        lines.append("- Roles: `admin`, `manager`, `buyer`, `inspector`, `viewer`")
        lines.append("- Admin-only: user management, tenant settings")
        lines.append("- Manager-only: PO approval, supplier status changes, RFQ awarding")
        lines.append("- Viewer: read-only access to all GET endpoints")
        lines.append("")

    # ---- Audit Trail ----
    if not is_frontend_svc:
        lines.append("## Audit Trail\n")
        lines.append("EVERY state change and data mutation must be logged to an audit table.\n")
        lines.append("- Create `audit_log` table: `id`, `entity_type`, `entity_id`, `action` (create/update/delete/transition),")
        lines.append("  `old_value` (JSON), `new_value` (JSON), `user_id`, `tenant_id`, `timestamp`")
        lines.append("- Log every state machine transition (from_state, to_state)")
        lines.append("- Log every create/update/delete operation on primary entities")
        lines.append("- Include `user_id` from the JWT token in every audit record")
        lines.append("- The audit log is append-only — never update or delete audit records")
        lines.append("")

    # ---- Auth-Service Special Instructions ----
    if service_id == "auth-service":
        lines.append("## Auth-Service Special Instructions\n")
        lines.append("You are the AUTHENTICATION SERVICE. You CREATE and SIGN JWT tokens.")
        lines.append("Other services VALIDATE tokens you create.\n")
        lines.append("**YOU MUST follow the Cross-Service JWT Standard exactly:**")
        lines.append("- Sign tokens with HS256 algorithm using JWT_SECRET env var")
        lines.append("- Token payload MUST contain: sub (user UUID), tenant_id, role, email, type, iat, exp")
        lines.append("- The `sub` claim holds the user ID (standard JWT convention)")
        lines.append("- Access tokens: 15-minute expiry")
        lines.append("- Refresh tokens: 7-day expiry with `type: \"refresh\"`")
        lines.append("- Password hashing: bcrypt with 12 rounds")
        lines.append("- Do NOT use RS256 or any asymmetric algorithm")
        lines.append("- Do NOT auto-generate RSA keys")
        lines.append("- Do NOT use JWT_PRIVATE_KEY or JWT_PUBLIC_KEY env vars")
        lines.append("")

    # ---- Notification-Service Special Instructions ----
    if service_id == "notification-service":
        lines.append("## Notification-Service Special Instructions\n")
        lines.append("When you receive ANY subscribed event, you MUST:\n")
        lines.append("1. Look up `NotificationPreference` for affected user(s) / tenant")
        lines.append("2. If notification is enabled for this event type, INSERT a new `Notification` record")
        lines.append("3. Set `type`, `channel`, `reference_id`, `reference_type` from the event payload")
        lines.append("4. For escalation: check `EscalationRule` table and create escalation if conditions match")
        lines.append("5. Mark notification as `pending` → process through channel (email/in-app/SMS)")
        lines.append("")
        lines.append("**DO NOT** just log the event. You MUST create database records for every notification.")
        lines.append("The `GET /notifications` endpoint must return real persisted notifications, not empty arrays.")
        lines.append("")

    # ---- Failure context (from previous runs) ----
    failure_ctx = builder_config.get("failure_context", "")
    if failure_ctx:
        lines.append("## Previous Build Failure Context\n")
        lines.append(failure_ctx)
        lines.append("")

    # ---- Acceptance test requirements ----
    acceptance = builder_config.get("acceptance_test_requirements", "")
    if acceptance:
        lines.append(acceptance)
        lines.append("")

    # ---- Cross-Service Standards (MANDATORY for all services) ----
    standards = build_cross_service_standards(service_id, is_frontend=is_frontend_svc)
    lines.append(standards)

    content = "\n".join(lines)

    # Write to {output_dir}/.claude/CLAUDE.md
    claude_dir = output_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    claude_md_path = claude_dir / "CLAUDE.md"
    claude_md_path.write_text(content, encoding="utf-8")

    logger.info(
        "Wrote builder CLAUDE.md for %s (%d bytes) at %s",
        service_id,
        len(content),
        claude_md_path,
    )
    return claude_md_path


async def _kill_builder_tree(
    proc: asyncio.subprocess.Process, service_id: str
) -> None:
    """Kill builder subprocess and all child processes (Claude CLI sessions).

    Uses ``psutil`` when available to walk the entire process tree so that
    orphaned ``claude.CMD`` / ``claude`` children are reaped.  Falls back
    to ``proc.kill()`` when ``psutil`` is not installed.

    Always awaits ``proc.wait()`` at the end so that the asyncio
    ``proc.returncode`` attribute is populated for subsequent checks.
    """
    try:
        import psutil

        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)

        # Kill children first (Claude CLI sessions)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass

        # Then kill parent
        try:
            parent.kill()
        except psutil.NoSuchProcess:
            pass

        # Wait for all to finish (psutil-level)
        psutil.wait_procs(children + [parent], timeout=10)

    except ImportError:
        # psutil not available -- fallback to basic kill
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    except Exception as e:
        logger.warning("Error killing builder tree for %s: %s", service_id, e)
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    # Always reap the asyncio subprocess so proc.returncode is set
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        pass

    logger.info("Builder process tree for %s killed", service_id)


async def _run_single_builder(
    service_info: ServiceInfo,
    config: SuperOrchestratorConfig,
    state: PipelineState,
) -> BuilderResult:
    """Run a single builder subprocess and parse the result."""
    output_dir = Path(config.output_dir) / service_info.service_id
    ensure_dir(output_dir)

    # SKIP-COMPLETED: If this service already built successfully (has source
    # files, no error, and a success claim), reuse the existing result.
    _prev_state_file = output_dir / ".agent-team" / "STATE.json"
    if _prev_state_file.exists():
        try:
            _prev = load_json(_prev_state_file)
            _prev_summary = (_prev or {}).get("summary", {})
            _prev_err = str((_prev or {}).get("error_context", ""))
            _prev_success = _prev_summary.get("success", False)
            _prev_milestones = len((_prev or {}).get("completed_milestones", []))
            # Fix 6: agent_team_v15 uses completed_phases instead of completed_milestones
            _prev_phases = len((_prev or {}).get("completed_phases", []))
            _code_pats = ("*.py", "*.js", "*.ts", "*.tsx", "*.jsx", "Dockerfile")
            _has_src = any(
                next(output_dir.rglob(p), None) is not None for p in _code_pats
            )
            # Fix 7: Require sufficient phase completion (>= 8 of ~10 phases)
            _sufficient_progress = (
                _prev_milestones > 0 or _prev_phases >= 8
            )
            # Fix 8: Also accept stall-killed builders that completed milestones
            # (they won't have summary.success=True but have real output)
            _prev_current = (_prev or {}).get("current_milestone", "")
            _stall_recovered = (
                _has_src
                and _sufficient_progress
                and (
                    _prev_current in ("complete", "done", "finished")
                    or _prev_milestones >= 3
                )
            )
            if (_prev_success and _has_src and not _prev_err and _sufficient_progress) or _stall_recovered:
                logger.info(
                    "Builder %s already completed successfully — skipping rebuild",
                    service_info.service_id,
                )
                print(f"  [builder] {service_info.service_id} already complete, skipping")
                return _parse_builder_result(service_info.service_id, output_dir)
        except Exception:
            pass  # Fall through to normal build

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

    # CONTEXT-INJECTION: Write .claude/CLAUDE.md with all enrichment data
    # so the builder subprocess has full service context (entities, state
    # machines, contracts, events, tech stack, cross-service deps).
    # This bridges the gap identified in DEEP_AUDIT Issue 1K (T2-T6).
    try:
        _write_builder_claude_md(output_dir, builder_config)
    except Exception as exc:
        logger.warning(
            "Failed to write builder CLAUDE.md for %s: %s (non-fatal)",
            service_info.service_id,
            exc,
        )

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
            # Fix: Redirect stdout/stderr to log files instead of PIPE.
            # Using PIPE without reading causes deadlock when buffer fills.
            _agent_team_dir = output_dir / ".agent-team"
            _agent_team_dir.mkdir(parents=True, exist_ok=True)
            _stdout_log = open(_agent_team_dir / "builder_stdout.log", "w", encoding="utf-8")
            _stderr_log = open(_agent_team_dir / "builder_stderr.log", "w", encoding="utf-8")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=_stdout_log,
                stderr=_stderr_log,
                cwd=str(output_dir),  # Set working directory for subprocess
                env=sub_env,
            )

            # -- Fix 1/3: Poll STATE.json for early completion detection ------
            state_json_path = output_dir / ".agent-team" / "STATE.json"
            timeout_s = config.builder.timeout_per_builder
            poll_interval_s = config.builder.poll_interval_s
            stall_timeout_s = getattr(config.builder, "stall_timeout_s", 600)
            start_ts = time.monotonic()
            last_log_phase: str | None = None
            last_heartbeat_time: float = 0.0
            timed_out = False
            polling_complete = False
            _last_activity_ts = time.monotonic()  # Track file activity for stall detection
            _prev_newest_mtime = 0.0  # Track last-seen newest file mtime
            _planning_phase_timeout = max(stall_timeout_s, 2700)  # 45 min during planning
            _building_phase_timeout = stall_timeout_s  # Normal timeout once building

            while True:
                elapsed = time.monotonic() - start_ts

                # Check timeout
                if elapsed >= timeout_s:
                    logger.warning(
                        "Builder for %s timed out after %ds",
                        service_info.service_id,
                        timeout_s,
                    )
                    await _kill_builder_tree(proc, service_info.service_id)
                    timed_out = True
                    break

                # Check if subprocess exited on its own
                if proc.returncode is not None:
                    logger.info(
                        "Builder for %s exited with code %s",
                        service_info.service_id,
                        proc.returncode,
                    )
                    break

                # Poll STATE.json for completion
                if state_json_path.exists():
                    try:
                        state_data = json.loads(
                            state_json_path.read_text(encoding="utf-8")
                        )
                        conv = state_data.get("convergence_ratio", 0.0)
                        phases = len(state_data.get("completed_phases", []))
                        milestones = len(
                            state_data.get("completed_milestones", [])
                        )
                        current_phase = state_data.get("current_phase", "")
                        success = state_data.get("success", False)
                        if not success:
                            success = state_data.get("summary", {}).get(
                                "success", False
                            )

                        # Progress logging (phase changes)
                        if current_phase != last_log_phase:
                            logger.info(
                                "[builder-monitor] %s: phase=%s, "
                                "phases=%d, milestones=%d, conv=%.2f, "
                                "elapsed=%.0fs",
                                service_info.service_id,
                                current_phase,
                                phases,
                                milestones,
                                conv,
                                elapsed,
                            )
                            last_log_phase = current_phase

                        # Fix 3: Heartbeat every 5 minutes even if phase unchanged
                        if elapsed - last_heartbeat_time >= 300:
                            logger.info(
                                "[builder-heartbeat] %s: still running "
                                "(phase=%s, elapsed=%.0fs/%ds)",
                                service_info.service_id,
                                current_phase,
                                elapsed,
                                timeout_s,
                            )
                            last_heartbeat_time = elapsed

                        # Completion detection (checked BEFORE stall detection
                        # so that completed builders aren't killed as stalled)
                        is_complete = (
                            (conv >= 0.9 and (phases >= 8 or milestones >= 3))
                            or current_phase
                            in (
                                "convergence_complete",
                                "complete",
                                "done",
                                "finished",
                            )
                            or (
                                success and (phases >= 8 or milestones >= 3)
                            )
                        )

                        if is_complete:
                            logger.info(
                                "Builder for %s detected complete via "
                                "STATE.json (phase=%s, conv=%.2f, "
                                "phases=%d, milestones=%d). "
                                "Killing subprocess.",
                                service_info.service_id,
                                current_phase,
                                conv,
                                phases,
                                milestones,
                            )
                            await _kill_builder_tree(
                                proc, service_info.service_id
                            )
                            polling_complete = True
                            break

                        # -- Stall detection: kill builder if no file activity ------
                        # Scan for any recently modified source files in the
                        # output directory. If nothing changes for stall_timeout_s
                        # the builder is deadlocked (e.g. sub-agent cascade freeze).
                        try:
                            _newest_mtime = 0.0
                            for _root, _dirs, _files in os.walk(str(output_dir)):
                                # Skip metadata dirs to focus on actual output
                                _dirs[:] = [
                                    d for d in _dirs
                                    if d not in (
                                        "data", "pattern-store", "__pycache__",
                                        "node_modules", ".claude",
                                    )
                                ]
                                for _fname in _files:
                                    if _fname.endswith((".db", ".db-shm", ".db-wal")):
                                        continue
                                    _fp = os.path.join(_root, _fname)
                                    try:
                                        _mt = os.path.getmtime(_fp)
                                        if _mt > _newest_mtime:
                                            _newest_mtime = _mt
                                    except OSError:
                                        pass
                            # -- Improved activity detection (Issue #12) --
                            # Check if ANY file was modified since last poll,
                            # not just within the last 60s. This prevents
                            # false kills during test/verification phases
                            # where builders run commands without creating
                            # new files but DO write to stdout/stderr logs.
                            if _newest_mtime > _prev_newest_mtime:
                                _last_activity_ts = time.monotonic()
                                _prev_newest_mtime = _newest_mtime
                            # Also check builder log files explicitly —
                            # these are written during test/docker phases
                            # when no source files change.
                            _agent_dir = output_dir / ".agent-team"
                            for _log_name in (
                                "builder_stdout.log",
                                "builder_stderr.log",
                            ):
                                _log_path = _agent_dir / _log_name
                                try:
                                    _log_mt = os.path.getmtime(str(_log_path))
                                    if _log_mt > _prev_newest_mtime:
                                        _last_activity_ts = time.monotonic()
                                        _prev_newest_mtime = _log_mt
                                except OSError:
                                    pass
                        except OSError:
                            pass  # Filesystem error; skip this check

                        _stall_elapsed = time.monotonic() - _last_activity_ts
                        _effective_stall_timeout = _building_phase_timeout if _prev_newest_mtime > 0 else _planning_phase_timeout
                        if _stall_elapsed >= _effective_stall_timeout:
                            # Check if process already exited (not a stall, just done)
                            if proc.returncode is not None:
                                logger.info(
                                    "Builder for %s already exited (rc=%s), not a stall",
                                    service_info.service_id, proc.returncode,
                                )
                                break

                            # Check CPU usage before killing (process may be actively working)
                            _skip_kill = False
                            try:
                                import psutil
                                _p = psutil.Process(proc.pid)
                                _cpu = _p.cpu_percent(interval=2)
                                if _cpu > 5:
                                    logger.info(
                                        "Builder %s appears active (CPU=%.1f%%), resetting stall timer",
                                        service_info.service_id, _cpu,
                                    )
                                    _last_activity_ts = time.monotonic()
                                    _skip_kill = True
                            except ImportError:
                                pass  # psutil not installed, fall through to kill
                            except Exception:
                                pass  # Process might have exited between check, fall through

                            if _skip_kill:
                                continue

                            logger.warning(
                                "Builder for %s stalled — no file activity "
                                "for %.0fs (limit=%ds). Killing.",
                                service_info.service_id,
                                _stall_elapsed,
                                int(_effective_stall_timeout),
                            )
                            print(
                                f"  [builder-stall] {service_info.service_id}: "
                                f"no activity for {_stall_elapsed:.0f}s, killing"
                            )
                            await _kill_builder_tree(
                                proc, service_info.service_id
                            )
                            timed_out = True
                            break

                    except (json.JSONDecodeError, OSError):
                        pass  # STATE.json being written, retry next poll

                # Wait for process exit or next poll interval
                try:
                    await asyncio.wait_for(
                        proc.wait(), timeout=poll_interval_s
                    )
                    # Process exited during wait
                    logger.info(
                        "Builder for %s exited with code %s",
                        service_info.service_id,
                        proc.returncode,
                    )
                    break
                except asyncio.TimeoutError:
                    pass  # Expected -- process still running, loop again

            if timed_out:
                # Before returning failure, check STATE.json — the builder
                # may have completed milestones before it stalled.
                _stall_state_path = output_dir / ".agent-team" / "STATE.json"
                if _stall_state_path.exists():
                    try:
                        _stall_data = json.loads(
                            _stall_state_path.read_text(encoding="utf-8")
                        )
                        _stall_milestones = len(
                            _stall_data.get("completed_milestones", [])
                        )
                        _stall_phase = (
                            _stall_data.get("current_milestone", "")
                            or _stall_data.get("current_phase", "")
                        )
                        if _stall_phase in ("complete", "done", "finished") or _stall_milestones >= 3:
                            logger.info(
                                "Builder for %s stalled but STATE.json shows "
                                "%d milestones (phase=%s) — treating as complete.",
                                service_info.service_id,
                                _stall_milestones,
                                _stall_phase,
                            )
                            print(
                                f"  [builder-stall-recovery] {service_info.service_id}: "
                                f"{_stall_milestones} milestones completed, "
                                f"treating as successful"
                            )
                            break  # Fall through to _parse_builder_result
                    except (json.JSONDecodeError, OSError):
                        pass
                return BuilderResult(
                    system_id=service_info.service_id,
                    service_id=service_info.service_id,
                    success=False,
                    error=f"Timed out after {timeout_s}s",
                )
            if polling_complete:
                # Builder was detected complete via STATE.json and killed;
                # skip the returncode/stderr checks below -- go straight
                # to _parse_builder_result.
                break
            # -- End Fix 1/3 --------------------------------------------------

        except Exception as exc:
            logger.error(
                "Builder for %s failed with exception: %s",
                service_info.service_id,
                exc,
            )
            return BuilderResult(
                system_id=service_info.service_id,
                service_id=service_info.service_id,
                success=False,
                error=str(exc),
            )
        finally:
            # Fix 2: Kill entire process tree, not just the direct process
            if proc is not None and proc.returncode is None:
                await _kill_builder_tree(proc, service_info.service_id)
            # Close log file handles
            for _fh in (_stdout_log, _stderr_log):
                try:
                    _fh.close()
                except Exception:
                    pass

        # INT-003: Check if the module was not found -- try the next one.
        # Also log stdout/stderr for debugging (read from log files)
        if proc.returncode != 0:
            stdout_text = ""
            stderr_text = ""
            _stdout_path = output_dir / ".agent-team" / "builder_stdout.log"
            _stderr_path = output_dir / ".agent-team" / "builder_stderr.log"
            if _stdout_path.exists():
                stdout_text = _stdout_path.read_text(encoding="utf-8", errors="replace")
            if _stderr_path.exists():
                stderr_text = _stderr_path.read_text(encoding="utf-8", errors="replace")

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

    Convergence is resolved via a multi-fallback chain so that a service
    with real output is never reported as 0.0 due to a missing or
    differently-keyed convergence value (Issue #8).
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
        _code_patterns = ("*.py", "*.js", "*.ts", "Dockerfile", "*.go", "*.rs")
        source_file_count = 0
        has_source = False
        # Detect frontend services to exclude bogus backend files from count
        _is_frontend = False
        _bconfig_path = output_dir / "builder_config.json"
        if _bconfig_path.exists():
            try:
                _bconfig = load_json(_bconfig_path)
                _is_frontend = bool((_bconfig or {}).get("is_frontend", False))
            except Exception:
                pass
        # Directories to exclude from file counting for frontend services
        _frontend_exclude_dirs = {"services", "server", "backend"}
        if claimed_success:
            for pat in _code_patterns:
                for f in output_dir.rglob(pat):
                    # For frontend services, skip files in backend-like subdirectories
                    if _is_frontend and any(
                        part in _frontend_exclude_dirs for part in f.relative_to(output_dir).parts
                    ):
                        continue
                    source_file_count += 1
            has_source = source_file_count > 0
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

        # -- Convergence resolution (multi-fallback chain, Issue #8) ------
        convergence = float(summary.get("convergence_ratio", 0.0))

        # Fallback 1: compute from requirements counts in summary
        if convergence == 0.0:
            req_met = (
                summary.get("requirements_met", 0)
                or summary.get("requirements_checked", 0)
            )
            req_total = (
                summary.get("requirements_total", 0)
                or summary.get("total_requirements", 0)
            )
            if req_total and int(req_total) > 0:
                convergence = int(req_met) / int(req_total)
                logger.info(
                    "%s: convergence recovered from summary requirements "
                    "(%s/%s = %.2f)",
                    service_id, req_met, req_total, convergence,
                )

        # Fallback 2: root-level convergence_ratio (v15 serialises the
        # full RunState as top-level keys via dataclasses.asdict)
        if convergence == 0.0:
            root_conv = float(data.get("convergence_ratio", 0.0))
            if root_conv > 0.0:
                convergence = root_conv
                logger.info(
                    "%s: convergence recovered from root-level "
                    "convergence_ratio (%.2f)",
                    service_id, convergence,
                )

        # Fallback 3: root-level requirements_checked / requirements_total
        if convergence == 0.0:
            req_met = (
                data.get("requirements_checked", 0)
                or data.get("requirements_met", 0)
            )
            req_total = (
                data.get("requirements_total", 0)
                or data.get("total_requirements", 0)
            )
            if req_total and int(req_total) > 0:
                convergence = int(req_met) / int(req_total)
                logger.info(
                    "%s: convergence recovered from root-level requirements "
                    "(%s/%s = %.2f)",
                    service_id, req_met, req_total, convergence,
                )

        # Fallback 4: count checkboxes in VERIFICATION.md or REQUIREMENTS.md
        # Also check milestone subdirectories and VERIFICATION.md PASS/FAIL tables
        if convergence == 0.0:
            _agent_team_dir = output_dir / ".agent-team"
            # 4a: root-level VERIFICATION.md / REQUIREMENTS.md
            for md_name in ("VERIFICATION.md", "REQUIREMENTS.md"):
                md_path = _agent_team_dir / md_name
                if md_path.exists():
                    try:
                        text = md_path.read_text(errors="ignore")
                        checked = text.count("[x]") + text.count("[X]")
                        total_boxes = checked + text.count("[ ]")
                        if total_boxes > 0:
                            convergence = checked / total_boxes
                            logger.info(
                                "%s: convergence recovered from %s "
                                "checkboxes (%d/%d = %.2f)",
                                service_id, md_name, checked, total_boxes,
                                convergence,
                            )
                            break
                        # 4a-alt: parse PASS/FAIL table format
                        import re as _re
                        _passes = len(_re.findall(
                            r"\bPASS\b", text, _re.IGNORECASE
                        ))
                        _fails = len(_re.findall(
                            r"\bFAIL\b", text, _re.IGNORECASE
                        ))
                        _pf_total = _passes + _fails
                        if _pf_total > 0:
                            convergence = _passes / _pf_total
                            logger.info(
                                "%s: convergence recovered from %s "
                                "PASS/FAIL table (%d/%d = %.2f)",
                                service_id, md_name, _passes, _pf_total,
                                convergence,
                            )
                            break
                    except OSError:
                        pass
            # 4b: aggregate from milestone-*/REQUIREMENTS.md
            if convergence == 0.0 and _agent_team_dir.is_dir():
                _ms_checked = 0
                _ms_total = 0
                for _ms_dir in sorted(_agent_team_dir.iterdir()):
                    if not _ms_dir.is_dir() or not _ms_dir.name.startswith("milestone-"):
                        continue
                    _ms_req = _ms_dir / "REQUIREMENTS.md"
                    if _ms_req.exists():
                        try:
                            _ms_text = _ms_req.read_text(errors="ignore")
                            _ms_checked += (
                                _ms_text.count("[x]") + _ms_text.count("[X]")
                            )
                            _ms_total += (
                                _ms_text.count("[x]") + _ms_text.count("[X]")
                                + _ms_text.count("[ ]")
                            )
                        except OSError:
                            pass
                if _ms_total > 0:
                    convergence = _ms_checked / _ms_total
                    logger.info(
                        "%s: convergence recovered from milestone "
                        "REQUIREMENTS.md aggregate (%d/%d = %.2f)",
                        service_id, _ms_checked, _ms_total, convergence,
                    )

        # Fallback 5 (safety net): substantial code with 0 convergence is
        # almost certainly a convergence-checker bug, not a real 0%.
        # Count source files if we haven't already.
        if convergence == 0.0 and not has_source:
            for pat in _code_patterns:
                for f in output_dir.rglob(pat):
                    if _is_frontend and any(
                        part in _frontend_exclude_dirs for part in f.relative_to(output_dir).parts
                    ):
                        continue
                    source_file_count += 1
            has_source = source_file_count > 0

        if convergence == 0.0 and source_file_count >= 20:
            # More generous safety net based on file count + milestone count
            _milestone_count = 0
            try:
                _state_path = output_dir / ".agent-team" / "STATE.json"
                if _state_path.exists():
                    _sj = load_json(_state_path)
                    _milestone_count = len(_sj.get("completed_milestones", []))
            except Exception:
                pass
            if _milestone_count >= 6:
                convergence = 0.9  # 6+ milestones = near-complete
            elif _milestone_count >= 3:
                convergence = min(0.75, source_file_count / 80.0)
            else:
                convergence = min(0.5, source_file_count / 100.0)
            logger.warning(
                "%s: convergence=0.0 but %d source files + %d milestones — "
                "using safety-net estimate %.2f",
                service_id, source_file_count, _milestone_count, convergence,
            )

        return BuilderResult(
            system_id=str(data.get("system_id", "")),
            service_id=service_id,
            success=claimed_success,
            cost=float(data.get("total_cost", 0.0)),
            test_passed=int(summary.get("test_passed", 0)),
            test_total=int(summary.get("test_total", 0)),
            convergence_ratio=convergence,
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


def _check_docker_available() -> bool:
    """Return True if Docker CLI is on PATH and the daemon is running.

    Fix 14: Pre-flight check to avoid wasting time on integration
    when Docker Desktop is not running.
    """
    docker_path = shutil.which("docker")
    if not docker_path:
        logger.warning("Docker not found on PATH — integration will be skipped")
        return False
    try:
        result = subprocess.run(
            [docker_path, "info"],
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[:200]
            logger.warning(
                "Docker daemon not running (rc=%d): %s — integration will be skipped",
                result.returncode,
                stderr,
            )
            return False
    except subprocess.TimeoutExpired:
        logger.warning("Docker info timed out — integration will be skipped")
        return False
    except Exception as exc:
        logger.warning("Docker pre-check failed: %s — integration will be skipped", exc)
        return False
    return True


def _ensure_frontend_dockerfile(service_dir: Path, service_info: ServiceInfo) -> None:
    """Generate a Dockerfile for frontend services if the builder didn't create one.

    Fix 5 + D1: Produces a multi-stage build (node:20-slim + nginx:stable-alpine)
    with framework-aware dist path handling (Angular 17+ outputs to
    ``dist/{project-name}/browser/``).  Uses ``127.0.0.1`` in health checks
    and adds SPA routing + API reverse-proxy to nginx config.
    """
    dockerfile = service_dir / "Dockerfile"
    if dockerfile.exists():
        # Validate existing Dockerfile has HEALTHCHECK
        content = dockerfile.read_text(encoding="utf-8")
        if "HEALTHCHECK" not in content:
            logger.warning("Frontend Dockerfile missing HEALTHCHECK — appending")
            content += (
                "\nHEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\\n"
                '    CMD wget -qO- http://127.0.0.1:80/ || exit 1\n'
            )
            dockerfile.write_text(content, encoding="utf-8")
        return

    # Detect pre-compiled output directory
    dist_dir = None
    for candidate in ("dist", "build", "output", ".next", ".nuxt"):
        if (service_dir / candidate).exists():
            dist_dir = candidate
            break

    # For Angular, the dist dir is usually dist/{project-name}/browser/
    if dist_dir == "dist":
        dist_path = service_dir / "dist"
        subdirs = [d for d in dist_path.iterdir() if d.is_dir()]
        for sub in subdirs:
            browser_dir = sub / "browser"
            if browser_dir.is_dir():
                dist_dir = f"dist/{sub.name}/browser"
                break
        else:
            # No browser/ subfolder — use first subdir if present
            if subdirs:
                dist_dir = f"dist/{subdirs[0].name}"

    _NGINX_CONF = (
        "server {\\n"
        "    listen 80;\\n"
        "    root /usr/share/nginx/html;\\n"
        "    index index.html;\\n"
        "    location / {\\n"
        "        try_files \\$uri \\$uri/ /index.html;\\n"
        "    }\\n"
        "    location /api/ {\\n"
        "        proxy_pass http://traefik:80;\\n"
        "    }\\n"
        "}\\n"
    )

    stack = service_info.stack if isinstance(service_info.stack, dict) else {}
    framework = stack.get("framework", "")

    if not dist_dir:
        # No compiled output — multi-stage build with dynamic dist detection
        fw_name = framework or "Frontend"
        dockerfile_content = (
            f"# Multi-stage build for {fw_name} frontend\n"
            "FROM node:20-slim AS build\n"
            "WORKDIR /app\n"
            "COPY package*.json ./\n"
            "RUN npm ci\n"
            "COPY . .\n"
            "RUN npm run build\n"
            "\n"
            "FROM nginx:stable-alpine\n"
            "\n"
            "# Copy built files (Angular 17+ outputs to dist/project-name/browser/)\n"
            "COPY --from=build /app/dist/ /tmp/dist/\n"
            "\n"
            "# Find and copy the actual build output\n"
            "RUN if [ -d /tmp/dist/*/browser ]; then \\\n"
            "        cp -r /tmp/dist/*/browser/* /usr/share/nginx/html/; \\\n"
            "    elif [ -d /tmp/dist/*/ ]; then \\\n"
            "        cp -r /tmp/dist/*/* /usr/share/nginx/html/; \\\n"
            "    else \\\n"
            "        cp -r /tmp/dist/* /usr/share/nginx/html/; \\\n"
            "    fi && rm -rf /tmp/dist\n"
            "\n"
            f"# SPA routing + API proxy\n"
            f"RUN printf '{_NGINX_CONF}' > /etc/nginx/conf.d/default.conf\n"
            "\n"
            "EXPOSE 80\n"
            "HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\\n"
            "    CMD wget -qO- http://127.0.0.1:80/ || exit 1\n"
        )
    else:
        # Pre-compiled output exists — simple nginx serve
        dockerfile_content = (
            "FROM nginx:stable-alpine\n"
            f"COPY {dist_dir}/ /usr/share/nginx/html/\n"
            "\n"
            f"# SPA routing + API proxy\n"
            f"RUN printf '{_NGINX_CONF}' > /etc/nginx/conf.d/default.conf\n"
            "\n"
            "EXPOSE 80\n"
            "HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\\n"
            "    CMD wget -qO- http://127.0.0.1:80/ || exit 1\n"
        )

    service_dir.mkdir(parents=True, exist_ok=True)
    dockerfile.write_text(dockerfile_content, encoding="utf-8")
    logger.info("Generated Dockerfile for frontend service at %s", dockerfile)


def _is_frontend_service(service_info: ServiceInfo) -> bool:
    """Return True if the service is a frontend/UI application."""
    stack = service_info.stack
    if not isinstance(stack, dict):
        return False
    language = (stack.get("language") or "").lower()
    framework = (stack.get("framework") or "").lower()
    frontend_frameworks = {
        "angular", "react", "vue", "next", "nextjs", "nuxt", "svelte",
    }
    return framework in frontend_frameworks or language in frontend_frameworks


def _ensure_backend_dockerfile(
    service_dir: Path,
    service_id: str,
    stack: str,
) -> None:
    """Generate fallback Dockerfile for backend service if builder didn't create one.

    Fix D2: If a Dockerfile already exists, validates it has a HEALTHCHECK and
    appends one if missing.  If no Dockerfile exists, generates a full fallback
    based on the detected stack (python/typescript/generic).
    """
    dockerfile = service_dir / "Dockerfile"
    if dockerfile.exists():
        # Validate existing Dockerfile has HEALTHCHECK
        content = dockerfile.read_text(encoding="utf-8")
        if "HEALTHCHECK" not in content:
            logger.warning(
                "%s Dockerfile missing HEALTHCHECK — appending", service_id
            )
            if stack in ("python", "fastapi", "flask"):
                hc = (
                    "\nHEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\\n"
                    f'    CMD python -c "import urllib.request; urllib.request.urlopen('
                    f"'http://127.0.0.1:8000/api/{service_id}/health')\"\n"
                )
            elif stack in ("node", "nestjs", "express", "typescript"):
                hc = (
                    "\nHEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\\n"
                    f'    CMD node -e "const http = require(\'http\'); '
                    f"http.get('http://127.0.0.1:8080/api/{service_id}/health', "
                    f"r => process.exit(r.statusCode === 200 ? 0 : 1))"
                    f".on('error', () => process.exit(1))\"\n"
                )
            else:
                hc = (
                    "\nHEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\\n"
                    f"    CMD wget -qO- http://127.0.0.1:8080/api/{service_id}/health || exit 1\n"
                )
            content += hc
            dockerfile.write_text(content, encoding="utf-8")
        return

    # Generate full Dockerfile based on stack
    logger.info(
        "Generating fallback Dockerfile for %s (stack: %s)", service_id, stack
    )

    if stack in ("python", "fastapi", "flask"):
        content = _FASTAPI_DOCKERFILE_TEMPLATE.format(service_id=service_id)
    elif stack in ("node", "nestjs", "express", "typescript"):
        content = _NESTJS_DOCKERFILE_TEMPLATE.format(service_id=service_id)
    else:
        content = _GENERIC_DOCKERFILE_TEMPLATE.format(service_id=service_id)

    service_dir.mkdir(parents=True, exist_ok=True)
    dockerfile.write_text(content, encoding="utf-8")
    logger.info("Generated fallback Dockerfile for %s at %s", service_id, dockerfile)


def _verify_dockerfiles_exist(
    output_dir: Path,
    services: list[ServiceInfo],
) -> list[str]:
    """Check all services have Dockerfiles. Return list of services missing them.

    Fix 8 + D4: Pre-integration Dockerfile check.  For services missing a
    Dockerfile, auto-generate one: frontend services get an nginx-based
    Dockerfile, backend services get a stack-appropriate fallback.  Existing
    Dockerfiles are validated for HEALTHCHECK presence.
    """
    missing: list[str] = []
    for svc in services:
        service_dir = output_dir / svc.service_id
        dockerfile = service_dir / "Dockerfile"

        if _is_frontend_service(svc):
            # Frontend: generate or validate via _ensure_frontend_dockerfile
            _ensure_frontend_dockerfile(service_dir, svc)
            if not dockerfile.exists():
                logger.error(
                    "Service %s has no Dockerfile at %s", svc.service_id, dockerfile
                )
                missing.append(svc.service_id)
            continue

        # Backend: detect stack and generate or validate
        stack_raw = svc.stack if isinstance(svc.stack, dict) else {}
        stack_category = _detect_stack_category(stack_raw)
        _ensure_backend_dockerfile(service_dir, svc.service_id, stack_category)
        if not dockerfile.exists():
            logger.error(
                "Service %s has no Dockerfile at %s", svc.service_id, dockerfile
            )
            missing.append(svc.service_id)

    return missing


def _pre_deploy_validate(
    output_dir: Path,
    services: list[ServiceInfo],
) -> list[str]:
    """Validate all services are ready for Docker deployment.

    Checks that each service directory has the necessary files for its
    stack (Dockerfile, requirements.txt or package.json, entry point).

    Returns a list of human-readable issue strings (empty = all good).
    """
    issues: list[str] = []

    for svc in services:
        service_id = svc.service_id
        service_dir = output_dir / service_id

        if not service_dir.exists():
            issues.append(f"{service_id}: Service directory does not exist")
            continue

        # Check Dockerfile exists
        if not (service_dir / "Dockerfile").exists():
            issues.append(f"{service_id}: Missing Dockerfile")

        # Detect stack
        stack = _detect_stack_category(svc.stack)

        if stack == "python":
            req_file = service_dir / "requirements.txt"
            if not req_file.exists():
                issues.append(f"{service_id}: Missing requirements.txt")
            else:
                content = req_file.read_text(encoding="utf-8").lower()
                for dep in ["fastapi", "uvicorn", "sqlalchemy"]:
                    if dep not in content:
                        issues.append(
                            f"{service_id}: requirements.txt missing {dep}"
                        )

            if not (service_dir / "main.py").exists():
                alt_paths = ["src/main.py", "app/main.py"]
                if not any((service_dir / p).exists() for p in alt_paths):
                    issues.append(f"{service_id}: Missing main.py entry point")

        elif stack == "typescript":
            pkg_file = service_dir / "package.json"
            if not pkg_file.exists():
                issues.append(f"{service_id}: Missing package.json")
            else:
                try:
                    pkg = json.loads(pkg_file.read_text(encoding="utf-8"))
                    if "build" not in pkg.get("scripts", {}):
                        issues.append(
                            f"{service_id}: package.json missing 'build' script"
                        )
                except json.JSONDecodeError:
                    issues.append(f"{service_id}: package.json is invalid JSON")

            if not (service_dir / "tsconfig.json").exists():
                issues.append(f"{service_id}: Missing tsconfig.json")

    return issues


def _enrich_requirements_txt(service_dir: Path, service_id: str) -> None:
    """Ensure requirements.txt has all necessary FastAPI dependencies.

    Adds missing packages from a curated list of FastAPI essentials.
    Only modifies the file if new packages are actually needed.
    """
    req_file = service_dir / "requirements.txt"
    if not req_file.exists():
        return

    content = req_file.read_text(encoding="utf-8")
    required_deps = {
        "fastapi": "fastapi>=0.100.0",
        "uvicorn": "uvicorn[standard]>=0.23.0",
        "sqlalchemy": "sqlalchemy[asyncio]>=2.0.0",
        "asyncpg": "asyncpg>=0.28.0",
        "alembic": "alembic>=1.12.0",
        "pydantic": "pydantic>=2.0.0",
        "email-validator": "email-validator>=2.0.0",
    }

    lines = content.strip().split("\n") if content.strip() else []
    existing: set[str] = set()
    for line in lines:
        if line.strip() and not line.startswith("#"):
            pkg = (
                line.split(">=")[0]
                .split("==")[0]
                .split("[")[0]
                .strip()
                .lower()
            )
            existing.add(pkg)

    added: list[str] = []
    for dep_name, dep_spec in required_deps.items():
        if dep_name not in existing:
            lines.append(dep_spec)
            added.append(dep_name)

    if added:
        logger.info(
            "Enriched %s/requirements.txt with: %s",
            service_id,
            ", ".join(added),
        )
        req_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    # Fix 14: Docker pre-flight check (after service list built, before compose)
    if not _check_docker_available():
        logger.warning("Docker not available — skipping integration phase with minimal report")
        report = IntegrationReport(
            services_deployed=0,
            services_healthy=0,
            violations=[
                ContractViolation(
                    code="INFRA-DOCKER-UNAVAILABLE",
                    severity="warning",
                    service="pipeline",
                    endpoint="",
                    message="Docker Desktop is not running. Integration phase skipped.",
                )
            ],
            overall_health="skipped",
        )
        report_path = output_dir / "integration_report.json"
        atomic_write_json(report_path, dataclasses.asdict(report))
        state.integration_report_path = str(report_path)
        state.phase_artifacts[PHASE_INTEGRATION] = {
            "report_path": str(report_path),
            "services_deployed": 0,
            "services_healthy": 0,
            "docker_available": False,
        }
        if PHASE_INTEGRATION not in state.completed_phases:
            state.completed_phases.append(PHASE_INTEGRATION)
        cost_tracker.end_phase(phase_cost)
        state.total_cost = cost_tracker.total_cost
        state.phase_costs = cost_tracker.phase_costs
        state.save()
        return

    # Fix 8: Pre-integration Dockerfile check -- ensure all services have Dockerfiles
    missing_dockerfiles = _verify_dockerfiles_exist(output_dir, services)
    if missing_dockerfiles:
        logger.error(
            "Cannot run Docker integration — missing Dockerfiles: %s",
            missing_dockerfiles,
        )
        report = IntegrationReport(
            services_deployed=0,
            services_healthy=0,
            violations=[
                ContractViolation(
                    code="DOCKER-NODOCKERFILE",
                    severity="error",
                    service=sid,
                    endpoint="",
                    message=f"Service {sid} has no Dockerfile",
                )
                for sid in missing_dockerfiles
            ],
            overall_health="failed",
        )
        report_path = output_dir / "integration_report.json"
        atomic_write_json(report_path, dataclasses.asdict(report))
        state.integration_report_path = str(report_path)
        if PHASE_INTEGRATION not in state.completed_phases:
            state.completed_phases.append(PHASE_INTEGRATION)
        cost_tracker.end_phase(phase_cost)
        state.total_cost = cost_tracker.total_cost
        state.phase_costs = cost_tracker.phase_costs
        state.save()
        return

    # Fix I3: Enrich requirements.txt for Python services before Docker build
    for svc in services:
        stack_cat = _detect_stack_category(svc.stack)
        if stack_cat == "python":
            _enrich_requirements_txt(output_dir / svc.service_id, svc.service_id)

    # Fix I2: Pre-deploy validation — check all services have required files
    deploy_issues = _pre_deploy_validate(output_dir, services)
    if deploy_issues:
        for issue in deploy_issues:
            logger.warning("Pre-deploy validation: %s", issue)

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

    # Fix I1: Generate PostgreSQL init scripts (CRITICAL — was never called)
    try:
        ComposeGenerator.generate_init_sql(output_dir, services)
        logger.info("Generated init-db SQL scripts")
    except Exception as init_exc:
        logger.warning("Failed to generate init-db SQL: %s", init_exc)

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
            integration_tests_passed=flow_results.integration_tests_passed if hasattr(flow_results, "integration_tests_passed") else (flow_results.get("passed", 0) if isinstance(flow_results, dict) else 0),
            integration_tests_total=flow_results.integration_tests_total if hasattr(flow_results, "integration_tests_total") else (flow_results.get("total", 0) if isinstance(flow_results, dict) else 0),
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

    # GATE-3: Provide Graph RAG client to quality gate if available
    if config.graph_rag.enabled and state.phase_artifacts.get("graph_rag_contexts"):
        try:
            report = await _run_quality_gate_with_graph_rag(
                config, builder_results, integration_report, target_dir, state,
            )
        except Exception as exc:
            logger.warning("Graph RAG unavailable for quality gate: %s", exc)
            engine = QualityGateEngine()
            report = await engine.run_all_layers(
                builder_results=builder_results,
                integration_report=integration_report,
                target_dir=target_dir,
                fix_attempts=state.quality_attempts,
                max_fix_attempts=config.quality_gate.max_fix_retries,
            )
    else:
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


async def _run_quality_gate_with_graph_rag(
    config: SuperOrchestratorConfig,
    builder_results: list,
    integration_report: object,
    target_dir: Path,
    state: object,
) -> object:
    """Run quality gate with a live Graph RAG MCP client (GATE-3).

    Creates a temporary MCP session to the Graph RAG server so that
    Layer 4 (adversarial) can query cross-service events for ADV-001/ADV-002
    false-positive suppression.
    """
    from mcp import StdioServerParameters, ClientSession
    from mcp.client.stdio import stdio_client
    from src.graph_rag.mcp_client import GraphRAGClient
    from src.quality_gate.gate_engine import QualityGateEngine

    graph_rag_config = config.graph_rag
    env = {
        "GRAPH_RAG_DB_PATH": graph_rag_config.database_path,
        "GRAPH_RAG_CHROMA_PATH": graph_rag_config.chroma_path,
        "CI_DATABASE_PATH": graph_rag_config.ci_database_path,
        "ARCHITECT_DATABASE_PATH": graph_rag_config.architect_database_path,
        "CONTRACT_DATABASE_PATH": graph_rag_config.contract_database_path,
    }
    server_params = StdioServerParameters(
        command=graph_rag_config.mcp_command,
        args=graph_rag_config.mcp_args,
        env=env,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            client = GraphRAGClient(session)

            engine = QualityGateEngine(graph_rag_client=client)
            return await engine.run_all_layers(
                builder_results=builder_results,
                integration_report=integration_report,
                target_dir=target_dir,
                fix_attempts=state.quality_attempts,
                max_fix_attempts=config.quality_gate.max_fix_retries,
            )


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

    # Inject fix context from prior runs (no-op when persistence disabled)
    try:
        if getattr(config.persistence, "enabled", False):
            from src.persistence.context_builder import build_fix_context
            from src.persistence.pattern_store import PatternStore
            from src.build3_shared.models import ScanViolation as _SV

            _pstore = PatternStore(config.persistence.chroma_path)
            # We'll build fix_context once we have violations; store PatternStore for now
            fix_loop._persistence_config = config
            fix_loop._pattern_store = _pstore
    except Exception as exc:
        logger.debug("Fix context setup skipped: %s", exc)

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

    # Filter to only fixable violations before feeding to builders (Fix 25)
    fixable_violations: list[ContractViolation] = []
    unfixable_count = 0
    for v in all_violations:
        v_dict = {
            "code": v.code, "message": v.message, "service": v.service,
        }
        if _is_fixable_violation(v_dict):
            fixable_violations.append(v)
        else:
            unfixable_count += 1
            logger.debug(
                "Skipping unfixable violation: code=%s, service=%s, msg=%s",
                v.code, v.service, v.message[:80],
            )
    if unfixable_count:
        logger.warning(
            "Filtered out %d unfixable violations (Docker/infra/empty-service)",
            unfixable_count,
        )

    if not fixable_violations:
        logger.info("No fixable violations to process -- skipping fix pass")
        state.quality_attempts += 1
        cost_tracker.end_phase(total_fix_cost)
        return

    # Group fixable violations by service (Fix 10: skip empty/unknown/pipeline-level)
    violations_by_service: dict[str, list[ContractViolation]] = {}
    for v in fixable_violations:
        svc = v.service.strip()
        if not svc or svc == "unknown" or svc == "pipeline-level":
            logger.warning(
                "Skipping violation with non-actionable service=%r: "
                "code=%s, message=%s", svc, v.code, v.message[:80],
            )
            continue
        violations_by_service.setdefault(svc, []).append(v)

    # Build fix context from prior runs and inject into fix loop
    try:
        _pstore = getattr(fix_loop, "_pattern_store", None)
        if _pstore is not None and all_violations:
            from src.persistence.context_builder import build_fix_context
            from src.build3_shared.models import ScanViolation as _SV

            scan_violations = [
                _SV(code=v.code, severity=v.severity, category="",
                    message=v.message)
                for v in all_violations
            ]
            # Determine tech stack from first service's builder config
            _tech = "unknown"
            for _sid in violations_by_service:
                _bdir = Path(config.output_dir) / _sid
                _bcfg = _bdir / "builder_config.json"
                if _bcfg.exists():
                    _bdata = load_json(str(_bcfg))
                    _stk = _bdata.get("stack", {})
                    if isinstance(_stk, dict):
                        _lang = _stk.get("language", "")
                        _fw = _stk.get("framework", "")
                        _tech = f"{_lang}/{_fw}" if _fw else _lang
                    elif isinstance(_stk, str):
                        _tech = _stk
                    break
            fix_loop._fix_context = build_fix_context(
                scan_violations, _tech, config, _pstore,
            )
    except Exception as exc:
        logger.debug("Fix context injection skipped: %s", exc)

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
            # Fix 14: Override prd_path if saved state has empty/invalid value
            saved_prd = Path(state.prd_path) if state.prd_path else None
            if not saved_prd or not saved_prd.exists() or str(saved_prd) in ("", ".", "./"):
                if prd_path and prd_path.exists():
                    logger.info(
                        "Overriding saved prd_path '%s' with '%s'",
                        state.prd_path,
                        prd_path,
                    )
                    state.prd_path = str(prd_path)
                else:
                    raise ConfigurationError(
                        f"Saved state has invalid prd_path '{state.prd_path}' "
                        f"and no valid prd_path was provided on the command line."
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

    # Fix 19: Suppress unclosed transport warnings from MCP stdio cleanup
    import warnings
    warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed transport")

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
    except asyncio.CancelledError:
        logger.warning("CancelledError in pipeline loop -- saving state")
        state.save()
        raise PipelineError("Pipeline cancelled by asyncio cancel scope")
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
    cancel_scope_poisoned = False  # Set on first CancelledError from MCP

    async def _run_handler_isolated(handler, *args):
        """Run a phase handler in an independent asyncio task.

        This isolates the handler from cancel scope corruption caused by
        MCP stdio_client's anyio integration.  The independent task gets
        its own clean cancel scope.
        """
        handler_task = asyncio.create_task(
            handler(*args),
            name=f"isolated-{handler.__name__}",
        )
        while not handler_task.done():
            try:
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                pass  # Swallow persistent CancelledError in poisoned scope
        if handler_task.exception() is not None:
            raise handler_task.exception()

    while iteration < max_iterations:
        iteration += 1
        current = model.state
        print(f"\n{'='*60}")
        print(f"  PIPELINE LOOP #{iteration}  state={current}"
              f"  {'[ISOLATED]' if cancel_scope_poisoned else ''}")
        print(f"{'='*60}")

        if current in ("complete", "failed"):
            print(f"  Pipeline reached terminal state: {current}")
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

        handler_args = (state, config, cost_tracker, shutdown, model)
        print(f"  -> Calling handler: {handler.__name__}")

        if cancel_scope_poisoned:
            # Run in independent task to bypass corrupted cancel scope
            await _run_handler_isolated(handler, *handler_args)
        else:
            try:
                await handler(*handler_args)
            except asyncio.CancelledError:
                cancel_scope_poisoned = True
                print(f"  !! Cancel scope poisoned! Switching to isolated execution")
                await _run_handler_isolated(handler, *handler_args)

        print(f"  <- Handler returned, model.state={model.state}")

        # Budget check after every phase
        within_budget, budget_msg = cost_tracker.check_budget()
        if not within_budget:
            from src.super_orchestrator.exceptions import BudgetExceededError

            state.current_state = model.state
            state.save()
            raise BudgetExceededError(
                total_cost=cost_tracker.total_cost,
                budget_limit=cost_tracker.budget_limit or 0.0,
            )

        # Sync model state back to pipeline state
        state.current_state = model.state
        state.save()


# ---------------------------------------------------------------------------
# Persistence write hooks (crash-isolated)
# ---------------------------------------------------------------------------


def _persist_quality_gate_results(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    report: QualityGateReport,
) -> None:
    """Record quality gate results to the persistence layer.

    Completely crash-isolated: any failure is logged and swallowed.
    No-op when ``persistence.enabled`` is False.
    """
    try:
        if not getattr(config.persistence, "enabled", False):
            return

        from src.persistence import RunTracker, PatternStore

        run_tracker = RunTracker(config.persistence.db_path)
        pattern_store = PatternStore(config.persistence.chroma_path)

        run_id = state.pipeline_id
        prd_hash = state.phase_artifacts.get(PHASE_ARCHITECT, {}).get("prd_hash", "")

        verdict_str = (
            report.overall_verdict.value
            if hasattr(report.overall_verdict, "value")
            else str(report.overall_verdict)
        )

        service_count = state.total_builders
        run_tracker.record_run(run_id, prd_hash, verdict_str, service_count, state.total_cost)

        # Record each violation
        for layer_name, layer_result in report.layers.items():
            for violation in layer_result.violations:
                service_name = violation.service or "unknown"
                # Derive tech_stack from builder results if available
                tech_stack = ""
                builder_result = state.builder_results.get(service_name, {})
                if isinstance(builder_result, dict):
                    tech_stack = str(builder_result.get("tech_stack", ""))

                vid = run_tracker.record_violation(run_id, violation, service_name, tech_stack)
                pattern_store.add_violation_pattern(violation, tech_stack)

        run_tracker.update_scan_code_stats(run_id)
        logger.info("Persistence: recorded quality gate results for run %s", run_id)

    except Exception as exc:
        logger.warning("Persistence write failed (non-blocking): %s", exc)


def _persist_fix_results(
    state: PipelineState,
    config: SuperOrchestratorConfig,
) -> None:
    """Record fix pass results to the persistence layer.

    DATA GAP-1: code_before/code_after/diff fields do not exist on
    fix result objects in the current pipeline.  Empty strings are stored.

    Completely crash-isolated: any failure is logged and swallowed.
    No-op when ``persistence.enabled`` is False.
    """
    try:
        if not getattr(config.persistence, "enabled", False):
            return

        from src.persistence import RunTracker, PatternStore

        run_tracker = RunTracker(config.persistence.db_path)
        pattern_store = PatternStore(config.persistence.chroma_path)

        # The current pipeline does not capture code_before/code_after/diff.
        # This is DATA GAP-1: we store empty strings and document the gap.
        # When fix data capture is added in a future version, this can be
        # updated to store actual diffs.
        fix_artifact = state.phase_artifacts.get("fix_pass", {})
        if isinstance(fix_artifact, dict):
            logger.info(
                "Persistence: fix pass recorded (DATA GAP-1: "
                "code_before/code_after/diff not captured in current pipeline)"
            )

    except Exception as exc:
        logger.warning("Fix persistence write failed (non-blocking): %s", exc)


# ---------------------------------------------------------------------------
# PRD pre-validation (crash-isolated helper)
# ---------------------------------------------------------------------------


async def _run_prd_validation(
    state: PipelineState,
    config: SuperOrchestratorConfig,
) -> None:
    """Run PRD pre-validation on the decomposition result.

    Crash-isolated: if the validator itself fails, the pipeline continues
    with a warning.  BLOCKING issues halt the pipeline with a written
    report.  WARNING issues are logged only.
    """
    try:
        from src.super_orchestrator.prd_validator import validate_decomposition

        # Load service map and domain model from persisted JSON
        smap_data = load_json(state.service_map_path)
        dmodel_data = load_json(state.domain_model_path)

        if smap_data is None or dmodel_data is None:
            logger.warning("PRD validation skipped: service map or domain model not available")
            return

        from src.shared.models.architect import DomainModel, ServiceMap

        service_map = ServiceMap(**smap_data)
        domain_model = DomainModel(**dmodel_data)

        # Extract interview questions from architect artifacts if available
        interview_questions: list[str] = []
        arch_artifacts = state.phase_artifacts.get(PHASE_ARCHITECT, {})
        if isinstance(arch_artifacts, dict):
            interview_questions = arch_artifacts.get("interview_questions", [])

        result = validate_decomposition(service_map, domain_model, interview_questions)

        # Log warnings
        for warning in result.warnings:
            logger.warning("PRD validation [%s]: %s", warning.code, warning.message)

        # Handle blocking issues
        if not result.is_valid:
            report_path = Path(config.output_dir) / "PRD_VALIDATION_REPORT.md"
            lines = ["# PRD Validation Report\n", "## BLOCKING Issues\n"]
            for issue in result.blocking:
                lines.append(f"- **{issue.code}**: {issue.message}\n")
            if result.warnings:
                lines.append("\n## Warnings\n")
                for issue in result.warnings:
                    lines.append(f"- **{issue.code}**: {issue.message}\n")
            report_path.write_text("\n".join(lines), encoding="utf-8")

            state.phase_artifacts["prd_validation"] = {
                "status": "failed",
                "report_path": str(report_path),
                "blocking_count": len(result.blocking),
                "warning_count": len(result.warnings),
            }
            state.current_state = "architect_review"
            state.save()
            raise PipelineError(
                f"PRD validation failed with {len(result.blocking)} blocking issue(s). "
                f"Report: {report_path}"
            )

        # All clear
        state.phase_artifacts["prd_validation"] = {
            "status": "passed",
            "blocking_count": 0,
            "warning_count": len(result.warnings),
        }
        logger.info(
            "PRD validation passed (0 blocking, %d warnings)",
            len(result.warnings),
        )

    except PipelineError:
        raise  # Re-raise blocking validation errors
    except Exception as exc:
        logger.warning("PRD validation encountered an error (non-blocking): %s", exc)


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
    print("  [phase-architect] Starting architect phase")
    state.save()
    await model.start_architect()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()

    await run_architect_phase(state, config, cost_tracker, shutdown)
    print(f"  [phase-architect] Architect complete, state={model.state}")

    # TECH-025: save BEFORE transition
    state.save()
    await model.architect_done()  # type: ignore[attr-defined]
    state.current_state = model.state

    # PRD pre-validation (crash-isolated, never blocks pipeline on validator error)
    await _run_prd_validation(state, config)

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

    # PRD pre-validation (crash-isolated)
    await _run_prd_validation(state, config)

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
    await run_contract_registration(state, config, cost_tracker, shutdown)
    state.save()
    # Direct state advancement (same pattern as _phase_builders)
    if model.contracts_valid():
        model.state = "builders_running"
    else:
        try:
            await model.contracts_registered()  # type: ignore[attr-defined]
        except (asyncio.CancelledError, BaseException):
            model.state = "builders_running"
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

    # Build Graph RAG context (non-blocking best-effort)
    service_map = (
        load_json(state.service_map_path) if state.service_map_path else {}
    )
    if config.graph_rag.enabled and state.service_map_path:
        try:
            graph_rag_contexts = await _build_graph_rag_context(
                config, service_map
            )
            if graph_rag_contexts:
                state.phase_artifacts["graph_rag_contexts"] = graph_rag_contexts
                logger.info(
                    "Graph RAG context built for %d services",
                    len(graph_rag_contexts),
                )
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.warning("Graph RAG context build cancelled (non-fatal)")
        except Exception as exc:
            logger.warning(
                "Graph RAG context build failed (non-fatal): %s", exc
            )

    # FIX-8: Generate fallback context for services missing Graph RAG context
    if state.service_map_path:
        try:
            fallback_contexts = _build_fallback_contexts(state, service_map)
            existing = state.phase_artifacts.get("graph_rag_contexts", {})
            for svc_key, fallback_text in fallback_contexts.items():
                if not existing.get(svc_key):
                    existing[svc_key] = fallback_text
            if existing:
                state.phase_artifacts["graph_rag_contexts"] = existing
                logger.info(
                    "Fallback context generated for %d services "
                    "(total contexts: %d)",
                    len(fallback_contexts), len(existing),
                )
        except Exception as exc:
            logger.debug("Fallback context generation skipped: %s", exc)

    state.save()

    # Direct state advancement -- bypass async trigger to avoid cancel scope
    # corruption from MCP.  The guard condition (contracts_valid) is checked
    # inline; if it passes we force the state directly.
    if model.contracts_valid():
        print(f"  [phase-builders] contracts_valid=True, advancing to builders_running")
        model.state = "builders_running"
    else:
        # Guard failed -- try the async trigger as fallback (may fail silently)
        print(f"  [phase-builders] contracts_valid=False, trying async trigger")
        try:
            await model.contracts_registered()  # type: ignore[attr-defined]
        except (asyncio.CancelledError, BaseException) as exc:
            logger.warning(
                "State transition trigger failed (%s), forcing to builders_running",
                type(exc).__name__,
            )
            model.state = "builders_running"

    state.current_state = model.state
    print(f"  [phase-builders] done, state={state.current_state}")
    state.save()


async def _phase_builders_complete(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle builders_running → builders_complete."""
    print("  [phase-builders-complete] Starting parallel builders")
    await run_parallel_builders(state, config, cost_tracker, shutdown)
    print(f"  [phase-builders-complete] Builders finished")
    state.save()

    # Direct state advancement (same pattern as _phase_builders)
    if model.has_builder_results():
        print(f"  [phase-builders-complete] has_builder_results=True, advancing")
        model.state = "builders_complete"
    else:
        print(f"  [phase-builders-complete] has_builder_results=False, trying trigger")
        try:
            await model.builders_done()  # type: ignore[attr-defined]
        except (asyncio.CancelledError, BaseException) as exc:
            logger.warning(
                "builders_done trigger failed (%s), forcing to builders_complete",
                type(exc).__name__,
            )
            model.state = "builders_complete"

    state.current_state = model.state
    print(f"  [phase-builders-complete] done, state={state.current_state}")
    state.save()


def _build_fallback_contexts(
    state: PipelineState,
    service_map: dict,
) -> dict[str, str]:
    """Build fallback context for services when Graph RAG is unavailable.

    Generates markdown-formatted context from the service map, domain
    model, and contract registry.  Keyed by **both** service_id and
    service name so that ``generate_builder_config()`` can find the
    context regardless of which lookup key it tries.
    """
    contexts: dict[str, str] = {}
    services = service_map.get("services", [])
    if not isinstance(services, list):
        return contexts

    # Load domain model for entity enrichment
    domain_entities: dict[str, list[dict]] = {}
    domain_relationships: list[dict] = []
    try:
        if state.domain_model_path and Path(state.domain_model_path).exists():
            dm = load_json(state.domain_model_path)
            domain_relationships = dm.get("relationships", [])
            for ent in dm.get("entities", []):
                owning = ent.get("owning_service", "")
                domain_entities.setdefault(owning, []).append(ent)
    except Exception:
        pass

    for svc in services:
        if not isinstance(svc, dict):
            continue
        sid = svc.get("service_id", svc.get("name", ""))
        name = svc.get("name", sid)
        if not sid:
            continue

        lines: list[str] = []
        lines.append(f"## Service Context: {name}")
        lines.append("")

        domain = svc.get("domain", "")
        if domain:
            lines.append(f"**Domain:** {domain}")
            lines.append("")

        stack = svc.get("stack", {})
        if isinstance(stack, dict):
            lang = stack.get("language", "")
            fw = stack.get("framework", "")
            if lang or fw:
                lines.append(
                    f"**Tech Stack:** {lang}"
                    + (f" / {fw}" if fw else "")
                )
                lines.append("")

        svc_is_frontend = bool(svc.get("is_frontend", False))

        if svc_is_frontend:
            # Fix 4: Frontend gets rich context with ALL backend endpoints
            # and ALL entity schemas for API client generation
            lines.append("### FRONTEND SERVICE")
            lines.append("")
            lines.append(
                "This is a **frontend/UI service**. It does NOT own entities "
                "or create database tables. It consumes backend APIs."
            )
            lines.append("")

            # Include ALL entities from ALL services for type definitions
            all_ents = []
            for _ent_list in domain_entities.values():
                all_ents.extend(_ent_list)
            if all_ents:
                lines.append("### All Entity Schemas (for TypeScript interfaces)")
                for ent in all_ents:
                    ent_name = ent.get("name", "")
                    owning = ent.get("owning_service", "unknown")
                    lines.append(f"- **{ent_name}** (from {owning})")
                    for fld in ent.get("fields", []):
                        lines.append(
                            f"  - {fld.get('name', '')}: "
                            f"{fld.get('type', 'unknown')}"
                        )
                lines.append("")

            # Include ALL backend API endpoints
            lines.append("### Backend API Endpoints")
            for other_svc in services:
                if not isinstance(other_svc, dict):
                    continue
                other_sid = other_svc.get("service_id", other_svc.get("name", ""))
                if other_sid == sid or other_svc.get("is_frontend", False):
                    continue
                other_port = other_svc.get("port", 8080)
                lines.append(
                    f"- **{other_sid}**: `http://{other_sid}:{other_port}`"
                )
                # Include owned entity names as hints for route generation
                other_ents = domain_entities.get(other_sid, [])
                if other_ents:
                    ent_names = [e.get("name", "") for e in other_ents]
                    lines.append(f"  - Entities: {', '.join(ent_names)}")
            lines.append("")

            # Angular-specific guidance
            lines.append("### Frontend Implementation Guidance")
            lines.append("- Create standalone components (no NgModules if Angular)")
            lines.append("- Use HttpClient for API calls with proper error handling")
            lines.append("- Implement auth interceptor for JWT token injection")
            lines.append("- Create TypeScript interfaces matching entity schemas above")
            lines.append("- Implement routing for all entity CRUD pages")
            lines.append("- Use Reactive Forms for data input")
            lines.append("")
        else:
            ents = domain_entities.get(sid, []) or domain_entities.get(name, [])
            if ents:
                lines.append("### Owned Entities")
                for ent in ents:
                    ent_name = ent.get("name", "")
                    lines.append(f"- **{ent_name}**")
                    for fld in ent.get("fields", []):
                        lines.append(
                            f"  - {fld.get('name', '')}: "
                            f"{fld.get('type', 'unknown')}"
                        )
                    sm = ent.get("state_machine")
                    if sm:
                        states = sm.get("states", [])
                        if states:
                            lines.append(
                                f"  - State Machine: {' -> '.join(states)}"
                            )
                lines.append("")

        provides = svc.get("provides_contracts", [])
        consumes = svc.get("consumes_contracts", [])
        if provides:
            lines.append("### Provides Contracts")
            for c in provides:
                lines.append(f"- {c}")
            lines.append("")
        if consumes:
            lines.append("### Consumes Contracts")
            for c in consumes:
                lines.append(f"- {c}")
            lines.append("")

        if not svc_is_frontend:
            ents = domain_entities.get(sid, []) or domain_entities.get(name, [])
            entity_names = {e.get("name", "") for e in ents}
            related_lines: list[str] = []
            for rel in domain_relationships:
                src = rel.get("source_entity", rel.get("source", ""))
                tgt = rel.get("target_entity", rel.get("target", ""))
                rtype = rel.get("relationship_type", rel.get("type", ""))
                if src in entity_names and tgt not in entity_names:
                    related_lines.append(
                        f"- {src} --[{rtype}]--> {tgt} (external)"
                    )
                elif tgt in entity_names and src not in entity_names:
                    related_lines.append(
                        f"- {src} (external) --[{rtype}]--> {tgt}"
                    )
            if related_lines:
                lines.append("### Cross-Service Relationships")
                lines.extend(related_lines)
                lines.append("")

        context_text = "\n".join(lines)
        contexts[sid] = context_text
        if name and name != sid:
            contexts[name] = context_text

    return contexts


async def _build_graph_rag_context(
    config: SuperOrchestratorConfig,
    service_map: dict,
) -> dict[str, str]:
    """Build Graph RAG knowledge graph and fetch per-service context blocks.

    Returns dict mapping service_name -> context_text. Empty dict on any failure.
    """
    if not config.graph_rag.enabled:
        return {}
    try:
        import json as _json
        from mcp import StdioServerParameters, ClientSession
        from mcp.client.stdio import stdio_client

        graph_rag_config = config.graph_rag
        env = {
            "GRAPH_RAG_DB_PATH": graph_rag_config.database_path,
            "GRAPH_RAG_CHROMA_PATH": graph_rag_config.chroma_path,
            "CI_DATABASE_PATH": graph_rag_config.ci_database_path,
            "ARCHITECT_DATABASE_PATH": graph_rag_config.architect_database_path,
            "CONTRACT_DATABASE_PATH": graph_rag_config.contract_database_path,
        }
        server_params = StdioServerParameters(
            command=graph_rag_config.mcp_command,
            args=graph_rag_config.mcp_args,
            env=env,
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                from src.graph_rag.mcp_client import GraphRAGClient
                client = GraphRAGClient(session)

                # INT-2: Pre-fetch service interfaces via CI MCP
                service_interfaces_json = ""
                try:
                    from src.codebase_intelligence.mcp_client import CodebaseIntelligenceClient
                    ci_client = CodebaseIntelligenceClient()
                    interfaces: dict[str, object] = {}
                    services_data = service_map.get("services", {})
                    if isinstance(services_data, list):
                        svc_names = [
                            s.get("name", "") if isinstance(s, dict) else str(s)
                            for s in services_data
                        ]
                    else:
                        svc_names = list(services_data.keys())
                    for svc in svc_names:
                        if not svc:
                            continue
                        try:
                            iface = await ci_client.get_service_interface(svc)
                            if iface and "error" not in iface:
                                interfaces[svc] = iface
                        except Exception:
                            pass
                    if interfaces:
                        import json as _json2
                        service_interfaces_json = _json2.dumps(interfaces)
                except (ImportError, Exception) as exc:
                    logger.debug("CI MCP not available for interface pre-fetch: %s", exc)

                # Build knowledge graph
                await client.build_knowledge_graph(
                    service_interfaces_json=service_interfaces_json,
                )

                # Fetch context for each service
                contexts: dict[str, str] = {}
                services = service_map.get("services", {})
                if isinstance(services, list):
                    service_names = [
                        s.get("name", "") if isinstance(s, dict) else str(s)
                        for s in services
                    ]
                else:
                    service_names = list(services.keys())

                for svc_name in service_names:
                    if not svc_name:
                        continue
                    result = await client.get_service_context(svc_name)
                    contexts[svc_name] = result.get("context_text", "")
                return contexts
    except BaseException as e:
        logging.getLogger(__name__).warning(
            "Graph RAG context build failed (non-blocking): %s", e
        )
        return {}


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

    # Post-build cross-service validation
    service_ids = [sid for sid, status in state.builder_statuses.items() if status == "healthy"]
    try:
        validation_issues = validate_all_services(Path(config.output_dir), service_ids)
        if validation_issues:
            logger.warning("Post-build validation found %d issue categories", len(validation_issues))
            for category, issue_list in validation_issues.items():
                logger.warning("  [%s] %d issues:", category, len(issue_list))
                for issue in issue_list[:5]:
                    logger.warning("    - %s", issue)
            # Write validation report
            report_path = Path(config.output_dir) / "POST_BUILD_VALIDATION.md"
            report_lines = ["# Post-Build Validation Report\n"]
            for category, issue_list in validation_issues.items():
                report_lines.append(f"\n## {category} ({len(issue_list)} issues)\n")
                for issue in issue_list:
                    report_lines.append(f"- {issue}")
            report_path.write_text("\n".join(report_lines), encoding="utf-8")
    except Exception as exc:
        logger.warning("Post-build validation failed (non-fatal): %s", exc)

    # Auto-cleanup: Remove backend code from frontend services
    for svc_id in service_ids:
        svc_dir = Path(config.output_dir) / svc_id
        # Detect frontend service
        is_fe = any((svc_dir / f).exists() for f in ("angular.json", "next.config.js", "vite.config.ts", "nuxt.config.ts"))
        if not is_fe:
            continue
        # Remove services/ directory (backend duplication)
        services_subdir = svc_dir / "services"
        if services_subdir.exists() and services_subdir.is_dir():
            import shutil as _shutil
            logger.warning("Removing backend duplication from frontend %s: %s", svc_id, services_subdir)
            _shutil.rmtree(services_subdir, ignore_errors=True)
        # Remove any Python files (shouldn't be in frontend)
        for py_file in list(svc_dir.rglob("*.py")):
            if "__pycache__" not in str(py_file) and "node_modules" not in str(py_file):
                logger.warning("Removing Python file from frontend %s: %s", svc_id, py_file.name)
                py_file.unlink(missing_ok=True)
        # Remove docker-compose files (pipeline generates these)
        for dc_file in svc_dir.glob("docker-compose*.yml"):
            logger.warning("Removing docker-compose from frontend %s: %s", svc_id, dc_file.name)
            dc_file.unlink(missing_ok=True)

    # Safety net: Generate missing lockfiles before Docker build
    try:
        _generate_missing_lockfiles(Path(config.output_dir), service_ids)
    except Exception as exc:
        logger.warning("Lockfile generation failed (non-fatal): %s", exc)

    state.save()
    await model.start_integration()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()

    try:
        await run_integration_phase(state, config, cost_tracker, shutdown)
    except (IntegrationFailureError, Exception) as exc:
        logger.warning(
            "Integration phase failed (non-fatal, proceeding to quality gate): %s",
            str(exc)[:200],
        )
        # Record the failure but don't block pipeline
        state.phase_artifacts["integration_error"] = str(exc)[:500]
    state.save()
    await model.integration_done()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()


_UNFIXABLE_PREFIXES = (
    "INTEGRATION-", "INFRA-", "DOCKER-", "BUILD-NOSRC", "L2-INTEGRATION-FAIL",
)

_UNFIXABLE_MESSAGE_PATTERNS = [
    "docker compose",
    "docker build",
    "failed to solve",
    "dockerfile",
    "no such file or directory",
    "npm run build",
    "failed to start services",
    "no running services",
]


def _is_fixable_violation(violation: dict[str, Any]) -> bool:
    """Determine if a single violation can be fixed by re-running builders.

    Returns False for infrastructure/Docker failures, violations with
    empty service fields, and known unfixable message patterns.
    """
    code = str(violation.get("code", ""))
    message = str(violation.get("message", "")).lower()

    # Check unfixable code prefixes
    if any(code.startswith(pfx) for pfx in _UNFIXABLE_PREFIXES):
        return False

    # Check unfixable message patterns
    for pattern in _UNFIXABLE_MESSAGE_PATTERNS:
        if pattern in message:
            return False

    # Check if service field is empty (can't target a fix)
    service = str(violation.get("service", "")).strip()
    if not service or service == "unknown":
        return False

    return True


def _get_violation_signature(violations: list[dict[str, Any]]) -> frozenset:
    """Create a hashable signature of a violation set for repeat detection."""
    return frozenset(
        (
            str(v.get("code", "")),
            str(v.get("service", "")),
            str(v.get("message", ""))[:50],
        )
        for v in violations
    )


def _has_fixable_violations(quality_results: dict[str, Any]) -> bool:
    """Return True if there are code-level violations that a fix pass can address.

    Infrastructure violations (INTEGRATION-*, INFRA-*, DOCKER-*) and
    violations about missing source files cannot be fixed by code-level
    fix passes.  If only these remain, we should skip the fix loop.
    """
    found_any_violation = False

    for layer_data in quality_results.get("layers", {}).values():
        layer_violations = layer_data.get("violations", [])
        if isinstance(layer_violations, list):
            for v in layer_violations:
                found_any_violation = True
                if _is_fixable_violation(v):
                    return True

    # If no violations were found in layers, fall back to the top-level
    # blocking_violations count (some quality gate implementations may
    # not populate per-layer violation details).
    if not found_any_violation:
        blocking = quality_results.get("blocking_violations", 0)
        if blocking and blocking > 0:
            return True

    return False


async def _phase_quality(
    state: PipelineState,
    config: SuperOrchestratorConfig,
    cost_tracker: PipelineCostTracker,
    shutdown: GracefulShutdown,
    model: PipelineModel,
) -> None:
    """Handle integrating → quality_gate."""
    report = await run_quality_gate(state, config, cost_tracker, shutdown)

    # Persistence write -- crash-isolated
    _persist_quality_gate_results(state, config, report)

    verdict = report.overall_verdict
    if hasattr(verdict, "value"):
        verdict_str = verdict.value
    else:
        verdict_str = str(verdict)

    state.save()
    if verdict_str == GateVerdict.PASSED.value:
        await model.quality_passed()  # type: ignore[attr-defined]
    elif model.fix_attempts_remaining() and _has_fixable_violations(state.last_quality_results):
        await model.quality_needs_fix()  # type: ignore[attr-defined]
    elif model.advisory_only() or not _has_fixable_violations(state.last_quality_results):
        # Fix 13: Skip to complete when only unfixable violations remain
        logger.info(
            "Skipping fix pass — only unfixable/advisory violations remain"
        )
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

    # Persistence write -- crash-isolated
    _persist_quality_gate_results(state, config, report)

    verdict = report.overall_verdict
    if hasattr(verdict, "value"):
        verdict_str = verdict.value
    else:
        verdict_str = str(verdict)

    state.save()
    if verdict_str == GateVerdict.PASSED.value:
        await model.quality_passed()  # type: ignore[attr-defined]
    elif model.fix_attempts_remaining() and _has_fixable_violations(state.last_quality_results):
        await model.quality_needs_fix()  # type: ignore[attr-defined]
    elif model.advisory_only() or not _has_fixable_violations(state.last_quality_results):
        # Fix 13: Skip to complete when only unfixable violations remain
        logger.info(
            "Skipping fix pass — only unfixable/advisory violations remain"
        )
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
    """Handle fix_pass -> builders_running loop.

    Includes repeated-violation detection (Fix 12): if the current set
    of violations is identical to the previous fix pass, the fix loop
    exits early to avoid wasting budget on non-progressing passes.
    """
    # Fix 12: Check for repeated identical violations before running fix pass
    quality_results = state.last_quality_results
    current_violations: list[dict[str, Any]] = []
    for layer_data in quality_results.get("layers", {}).values():
        layer_violations = layer_data.get("violations", [])
        if isinstance(layer_violations, list):
            current_violations.extend(layer_violations)

    current_sig = _get_violation_signature(current_violations)
    prev_sig_data = state.phase_artifacts.get(PHASE_FIX_PASS, {}).get(
        "previous_violation_sig", None
    )
    if prev_sig_data is not None:
        prev_sig = frozenset(tuple(item) for item in prev_sig_data)
        if current_sig == prev_sig:
            logger.warning(
                "Identical violations detected in consecutive fix passes "
                "(%d violations) -- fixes are not making progress. "
                "Exiting fix loop.",
                len(current_violations),
            )
            # Skip fix pass and transition to done
            state.save()
            await model.fix_done()  # type: ignore[attr-defined]
            state.current_state = model.state
            state.save()
            return

    # Store current signature for next pass comparison
    fix_artifacts = state.phase_artifacts.get(PHASE_FIX_PASS, {})
    fix_artifacts["previous_violation_sig"] = [list(item) for item in current_sig]
    state.phase_artifacts[PHASE_FIX_PASS] = fix_artifacts

    await run_fix_pass(state, config, cost_tracker, shutdown)

    # Persistence write -- crash-isolated
    _persist_fix_results(state, config)

    state.save()
    await model.fix_done()  # type: ignore[attr-defined]
    state.current_state = model.state
    state.save()
