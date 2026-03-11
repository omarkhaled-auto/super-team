"""Wave 2 tests for contract registration enhancements.

Tests validation failure resilience, contract list format handling,
and contract context injection into builder configs.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.super_orchestrator.pipeline import (
    run_contract_registration,
    generate_builder_config,
)
from src.super_orchestrator.state import PipelineState
from src.super_orchestrator.cost import PipelineCostTracker
from src.super_orchestrator.shutdown import GracefulShutdown
from src.build3_shared.models import ServiceInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state_and_config(tmpdir: str, services: list[dict], stubs: dict | list):
    """Create state, config, cost_tracker, and shutdown objects for testing."""
    smap_path = Path(tmpdir) / "service_map.json"
    smap_path.write_text(json.dumps({"services": services}))

    contracts_dir = Path(tmpdir) / "contracts"
    contracts_dir.mkdir(exist_ok=True)
    stubs_file = contracts_dir / "stubs.json"
    stubs_file.write_text(json.dumps(stubs))

    state = PipelineState()
    state.service_map_path = str(smap_path)
    state.contract_registry_path = str(contracts_dir)

    config = MagicMock()
    config.output_dir = tmpdir

    cost_tracker = PipelineCostTracker()

    shutdown = GracefulShutdown()

    return state, config, cost_tracker, shutdown, contracts_dir


# ---------------------------------------------------------------------------
# 1. Validation failure for one contract -> others still register
# ---------------------------------------------------------------------------


class TestContractRegistrationResilience:
    """Validation failure for one contract does not block others."""

    @pytest.mark.asyncio
    async def test_one_contract_failure_others_continue(self):
        """When one contract registration fails, the others still succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            services = [
                {"name": "svc-a", "service_id": "svc-a"},
                {"name": "svc-b", "service_id": "svc-b"},
            ]
            stubs = {
                "svc-a": {"openapi": "3.1.0", "info": {"title": "SvcA"}},
                "svc-b": {"openapi": "3.1.0", "info": {"title": "SvcB"}},
            }
            state, config, cost_tracker, shutdown, contracts_dir = _make_state_and_config(
                tmpdir, services, stubs
            )

            call_count = 0

            async def mock_register(service_name, spec, cfg):
                nonlocal call_count
                call_count += 1
                if service_name == "svc-a":
                    raise RuntimeError("Registration failed for svc-a")
                return {"status": "registered", "service": service_name}

            with patch(
                "src.super_orchestrator.pipeline._register_single_contract",
                new_callable=AsyncMock,
                side_effect=mock_register,
            ):
                # Should NOT raise even though svc-a fails
                await run_contract_registration(state, config, cost_tracker, shutdown)

            # svc-a should have been saved to filesystem as fallback
            assert (contracts_dir / "svc-a.json").exists()
            # Phase should still be marked complete
            assert "contract_registration" in state.completed_phases

    @pytest.mark.asyncio
    async def test_all_contracts_fail_still_completes(self):
        """Even if all contract registrations fail, the phase completes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            services = [
                {"name": "svc-a", "service_id": "svc-a"},
            ]
            stubs = {
                "svc-a": {"openapi": "3.1.0", "info": {"title": "SvcA"}},
            }
            state, config, cost_tracker, shutdown, contracts_dir = _make_state_and_config(
                tmpdir, services, stubs
            )

            with patch(
                "src.super_orchestrator.pipeline._register_single_contract",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Failed"),
            ):
                await run_contract_registration(state, config, cost_tracker, shutdown)

            # Filesystem fallback should have saved the contract
            assert (contracts_dir / "svc-a.json").exists()


# ---------------------------------------------------------------------------
# 2. Contract list format handling
# ---------------------------------------------------------------------------


class TestContractStubFormats:
    """Contract stubs in both dict and list format are handled."""

    @pytest.mark.asyncio
    async def test_list_format_stubs(self):
        """Contract stubs provided as a list are handled correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            services = [
                {"name": "my-service", "service_id": "my-service"},
            ]
            # Stubs as a list (as generated by generate_contract_stubs)
            stubs = [
                {"openapi": "3.1.0", "info": {"title": "my-service API", "version": "1.0.0"}},
            ]
            state, config, cost_tracker, shutdown, contracts_dir = _make_state_and_config(
                tmpdir, services, stubs
            )

            with patch(
                "src.super_orchestrator.pipeline._register_single_contract",
                new_callable=AsyncMock,
                return_value={"status": "ok"},
            ) as mock_reg:
                await run_contract_registration(state, config, cost_tracker, shutdown)
                # Should have been called at least once
                assert mock_reg.called


# ---------------------------------------------------------------------------
# 3. Contract context injection into builder configs
# ---------------------------------------------------------------------------


class TestContractContextInjection:
    """Builder configs can include contract context."""

    def test_builder_config_includes_service_metadata(self):
        """generate_builder_config includes service_id and domain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service_info = ServiceInfo(
                service_id="invoice-service",
                domain="billing",
                stack={"language": "python", "framework": "fastapi"},
                port=8001,
            )
            config = MagicMock()
            config.output_dir = tmpdir
            config.builder.depth = "thorough"
            config.persistence = MagicMock()
            config.persistence.enabled = False

            state = PipelineState()
            state.prd_path = "/dummy/prd.md"
            state.phase_artifacts = {}

            config_dict, config_path = generate_builder_config(service_info, config, state)

            assert config_dict["service_id"] == "invoice-service"
            assert config_dict["domain"] == "billing"
            assert config_dict["depth"] == "thorough"
            assert config_dict["port"] == 8001

    def test_builder_config_includes_graph_rag_context(self):
        """Builder config includes graph_rag_context when available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service_info = ServiceInfo(
                service_id="user-service",
                domain="identity",
                stack={"language": "python"},
                port=8002,
            )
            config = MagicMock()
            config.output_dir = tmpdir
            config.builder.depth = "thorough"
            config.persistence = MagicMock()
            config.persistence.enabled = False

            state = PipelineState()
            state.prd_path = "/dummy/prd.md"
            state.phase_artifacts = {
                "graph_rag_contexts": {
                    "user-service": "Context for user service from graph RAG",
                },
            }

            config_dict, _ = generate_builder_config(service_info, config, state)
            assert config_dict["graph_rag_context"] == "Context for user service from graph RAG"
