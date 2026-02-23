"""Integration tests for Graph RAG.

Tests in this module exercise real code paths through multiple modules to
catch plumbing/wiring issues that unit tests with mocks cannot detect.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Existing mock-based tests (preserved)
# ---------------------------------------------------------------------------


class TestGatingDisabled:
    def test_gating_disabled_produces_empty_context(self) -> None:
        """When graph_rag.enabled=False the pipeline should produce empty context."""
        # Simulate a config where graph_rag is disabled
        config = MagicMock()
        config.graph_rag = MagicMock()
        config.graph_rag.enabled = False

        # When disabled, the graph_rag context should be empty
        if not config.graph_rag.enabled:
            graph_rag_context = {}
        else:
            graph_rag_context = {"service_name": "test", "context_text": "..."}

        assert graph_rag_context == {}


class TestClaudeMdGeneratorInclusion:
    def test_claude_md_generator_includes_graph_rag_context(self) -> None:
        """When graph_rag_context is provided it should appear in the output."""
        # Simulate a claude.md generator that accepts graph_rag_context
        graph_rag_context = "## Graph RAG Context: auth-service\n\n### Service Dependencies\n- Depends on: none"

        # A minimal generator mock
        base_output = "# Project CLAUDE.md\n\n## Architecture\n\nStandard info here."
        if graph_rag_context:
            output = base_output + "\n\n" + graph_rag_context
        else:
            output = base_output

        assert "## Graph RAG Context:" in output
        assert "auth-service" in output

    def test_claude_md_generator_empty_context_unchanged(self) -> None:
        """When graph_rag_context is empty, output should be unchanged."""
        graph_rag_context = ""

        base_output = "# Project CLAUDE.md\n\n## Architecture\n\nStandard info here."
        if graph_rag_context:
            output = base_output + "\n\n" + graph_rag_context
        else:
            output = base_output

        assert output == base_output


class TestAdversarialScannerSuppression:
    def test_adversarial_scanner_suppresses_with_graph_rag(self) -> None:
        """When Graph RAG client returns matched_events, ADV-001 should be suppressed."""
        # Mock a Graph RAG client that returns event validation
        client = MagicMock()
        client.check_cross_service_events = MagicMock(return_value={
            "matched_events": [
                {
                    "event_name": "order.created",
                    "publishers": ["order-service"],
                    "consumers": ["notification-service"],
                }
            ],
            "orphaned_events": [],
            "unmatched_consumers": [],
            "total_events": 1,
            "match_rate": 1.0,
        })

        # Simulate adversarial scanner logic
        event_result = client.check_cross_service_events()
        matched_event_names = {
            e["event_name"] for e in event_result.get("matched_events", [])
        }

        # ADV-001: check if an event reference (e.g., "order.created") is matched
        finding_event = "order.created"
        should_suppress = finding_event in matched_event_names

        assert should_suppress is True

    def test_adversarial_scanner_flags_without_graph_rag(self) -> None:
        """Without a Graph RAG client, ADV-001 should fire normally."""
        client = None

        # Simulate adversarial scanner logic without client
        if client is None:
            should_suppress = False
        else:
            event_result = client.check_cross_service_events()
            matched_event_names = {
                e["event_name"] for e in event_result.get("matched_events", [])
            }
            should_suppress = "order.created" in matched_event_names

        assert should_suppress is False


class TestFixPassPriorityBoost:
    def test_fix_pass_boosts_priority_for_high_impact(self) -> None:
        """When find_cross_service_impact returns high total_impacted_nodes,
        the fix pass should boost priority."""
        client = MagicMock()
        client.find_cross_service_impact = MagicMock(return_value={
            "source_node": "file::src/auth/main.py",
            "source_service": "auth-service",
            "impacted_services": [
                {"service_name": "order-service", "impact_count": 8},
                {"service_name": "notification-service", "impact_count": 7},
            ],
            "impacted_contracts": [],
            "impacted_entities": [],
            "total_impacted_nodes": 15,
        })

        # Simulate fix pass priority logic
        impact = client.find_cross_service_impact(node_id="file::src/auth/main.py")
        total_impacted = impact.get("total_impacted_nodes", 0)

        # High-impact threshold: 10 nodes
        HIGH_IMPACT_THRESHOLD = 10
        base_priority = 5
        if total_impacted >= HIGH_IMPACT_THRESHOLD:
            boosted_priority = max(1, base_priority - 2)  # Boost by 2 levels
        else:
            boosted_priority = base_priority

        assert total_impacted == 15
        assert boosted_priority < base_priority
        assert boosted_priority == 3


# ---------------------------------------------------------------------------
# NEW: Real integration tests (Fix 2 — test blind spots)
# ---------------------------------------------------------------------------


class TestGate3PlumbingChain:
    """Verify the GATE-3 plumbing chain reaches AdversarialScanner.

    This test would have caught C-2 through C-5: the broken plumbing chain
    where QualityGateEngine never passed graph_rag_client to Layer4Scanner.
    """

    @pytest.mark.asyncio
    async def test_plumbing_chain_reaches_adversarial_scanner(self) -> None:
        """QualityGateEngine(graph_rag_client=mock) must invoke
        mock.check_cross_service_events during Layer 4 ADV-001 detection."""
        from src.build3_shared.models import BuilderResult, IntegrationReport
        from src.quality_gate.gate_engine import QualityGateEngine

        # Create a mock graph_rag_client with an async check_cross_service_events
        mock_client = AsyncMock()
        mock_client.check_cross_service_events = AsyncMock(return_value={
            "matched_events": [
                {"event_name": "order.created", "publishers": ["order-svc"],
                 "consumers": ["notify-svc"]}
            ],
            "orphaned_events": [],
            "unmatched_consumers": [],
            "total_events": 1,
            "match_rate": 1.0,
        })

        # Create engine with the mock client — this is the plumbing we're testing
        engine = QualityGateEngine(graph_rag_client=mock_client)

        # Provide minimal passing builder results so L1/L2/L3 pass and L4 runs
        builder_results = [
            BuilderResult(
                system_id="test-system",
                service_id="auth-service",
                success=True,
                test_passed=10,
                test_total=10,
                convergence_ratio=1.0,
            )
        ]
        integration_report = IntegrationReport(
            services_deployed=1,
            services_healthy=1,
            contract_tests_passed=1,
            contract_tests_total=1,
            integration_tests_passed=1,
            integration_tests_total=1,
            overall_health="healthy",
        )

        # Use a temp dir with a dummy Python file for the scanner to find
        with tempfile.TemporaryDirectory() as tmp:
            dummy_file = Path(tmp) / "service.py"
            # Write a file with a dead-event-handler pattern to trigger ADV-001
            dummy_file.write_text(
                '@event_handler("order.created")\n'
                'async def handle_order(event):\n'
                '    pass\n',
                encoding="utf-8",
            )

            report = await engine.run_all_layers(
                builder_results=builder_results,
                integration_report=integration_report,
                target_dir=Path(tmp),
            )

        # The key assertion: check_cross_service_events was actually called
        # This proves the plumbing chain works:
        #   QualityGateEngine -> Layer4Scanner -> AdversarialScanner -> client
        mock_client.check_cross_service_events.assert_called()

    @pytest.mark.asyncio
    async def test_layer4_scanner_passes_client_to_adversarial(self) -> None:
        """Layer4Scanner must forward graph_rag_client to AdversarialScanner."""
        from src.quality_gate.layer4_adversarial import Layer4Scanner

        mock_client = AsyncMock()
        mock_client.check_cross_service_events = AsyncMock(return_value={
            "matched_events": [],
            "orphaned_events": [],
            "unmatched_consumers": [],
        })

        scanner = Layer4Scanner(graph_rag_client=mock_client)

        # Verify the client was passed through to the inner scanner
        assert scanner._scanner._graph_rag_client is mock_client

        # Run on an empty dir — L4 is advisory so won't fail
        with tempfile.TemporaryDirectory() as tmp:
            result = await scanner.evaluate(Path(tmp))

        # Verdict is always PASSED for Layer 4
        from src.build3_shared.models import GateVerdict
        assert result.verdict == GateVerdict.PASSED


class TestBuildGraphRagContextServiceInterfaces:
    """Verify INT-2: _build_graph_rag_context calls get_service_interface per service.

    This test would have caught C-1: the empty service_interfaces_json string.
    """

    @pytest.mark.asyncio
    async def test_build_graph_rag_context_prefetches_interfaces(self) -> None:
        """_build_graph_rag_context must call get_service_interface for each
        service in the service map, and pass the results as
        service_interfaces_json to build_knowledge_graph."""
        from src.super_orchestrator.config import SuperOrchestratorConfig

        config = SuperOrchestratorConfig()
        config.graph_rag.enabled = True

        service_map = {
            "services": [
                {"name": "auth-service"},
                {"name": "order-service"},
            ]
        }

        # Mock the MCP client that _build_graph_rag_context creates
        mock_graph_rag_client = AsyncMock()
        mock_graph_rag_client.build_knowledge_graph = AsyncMock(return_value={
            "success": True, "node_count": 10, "edge_count": 5,
        })
        mock_graph_rag_client.get_service_context = AsyncMock(return_value={
            "context_text": "mock context",
        })

        # Mock the CI client for interface pre-fetch
        mock_ci_client = AsyncMock()
        mock_ci_client.get_service_interface = AsyncMock(side_effect=[
            {"endpoints": [{"method": "POST", "path": "/login", "handler": "login"}],
             "events_published": [], "events_consumed": []},
            {"endpoints": [{"method": "POST", "path": "/orders", "handler": "create_order"}],
             "events_published": ["order.created"], "events_consumed": []},
        ])

        # Build fake async context managers for MCP stdio_client and ClientSession
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        class FakeStdioClient:
            """Replaces mcp.client.stdio.stdio_client (sync function -> async CM)."""
            def __init__(self_cm, params):
                pass
            async def __aenter__(self_cm):
                return (AsyncMock(), AsyncMock())
            async def __aexit__(self_cm, *a):
                pass

        class FakeClientSession:
            """Replaces mcp.ClientSession (sync constructor -> async CM)."""
            def __init__(self_cm, read, write):
                pass
            async def __aenter__(self_cm):
                return mock_session
            async def __aexit__(self_cm, *a):
                pass

        # Patch at the module source (inline imports in _build_graph_rag_context)
        with patch("mcp.client.stdio.stdio_client", FakeStdioClient), \
             patch("mcp.ClientSession", FakeClientSession), \
             patch("src.graph_rag.mcp_client.GraphRAGClient",
                   return_value=mock_graph_rag_client), \
             patch("src.codebase_intelligence.mcp_client.CodebaseIntelligenceClient",
                   return_value=mock_ci_client):

            from src.super_orchestrator.pipeline import _build_graph_rag_context
            result = await _build_graph_rag_context(config, service_map)

        # Assert: CI client's get_service_interface was called once per service
        assert mock_ci_client.get_service_interface.call_count == 2
        call_args_list = [
            call.args[0]
            for call in mock_ci_client.get_service_interface.call_args_list
        ]
        assert "auth-service" in call_args_list
        assert "order-service" in call_args_list

        # Assert: build_knowledge_graph was called with non-empty service_interfaces_json
        mock_graph_rag_client.build_knowledge_graph.assert_called_once()
        call_kwargs = mock_graph_rag_client.build_knowledge_graph.call_args
        sij = call_kwargs.kwargs.get("service_interfaces_json", "")
        assert sij != "", "service_interfaces_json must not be empty"
        import json
        parsed = json.loads(sij)
        assert "auth-service" in parsed
        assert "order-service" in parsed
