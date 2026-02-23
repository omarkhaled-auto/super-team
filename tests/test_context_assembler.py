"""Unit tests for Context Assembler."""
from __future__ import annotations

import pytest

from src.graph_rag.context_assembler import ContextAssembler


class TestAssembleServiceContext:
    def test_assemble_service_context_produces_markdown(self) -> None:
        assembler = ContextAssembler(max_tokens=5000)

        output = assembler.assemble_service_context(
            service_name="order-service",
            provided_endpoints=[
                {"method": "POST", "path": "/orders", "handler": "create_order"},
                {"method": "GET", "path": "/orders/{id}", "handler": "get_order"},
            ],
            consumed_endpoints=[
                {"method": "GET", "path": "/auth/me", "provider_service": "auth-service"},
            ],
            events_published=[
                {"event_name": "order.created", "channel": "orders"},
            ],
            events_consumed=[
                {"event_name": "payment.completed", "publisher_service": "payment-service"},
            ],
            owned_entities=[
                {"name": "Order", "fields": [{"name": "id", "type": "uuid"}]},
            ],
            referenced_entities=[
                {"name": "User", "owning_service": "auth-service", "fields": [{"name": "id", "type": "uuid"}]},
            ],
            depends_on=["auth-service", "payment-service"],
            depended_on_by=["notification-service"],
        )

        assert "## Graph RAG Context:" in output
        assert "| Method | Path |" in output
        assert "order-service" in output
        assert "POST" in output
        assert "/orders" in output

    def test_assemble_service_context_empty_data(self) -> None:
        assembler = ContextAssembler(max_tokens=5000)

        output = assembler.assemble_service_context(
            service_name="empty-service",
            provided_endpoints=[],
            consumed_endpoints=[],
            events_published=[],
            events_consumed=[],
            owned_entities=[],
            referenced_entities=[],
            depends_on=[],
            depended_on_by=[],
        )

        # Should still produce valid markdown with at least the header
        assert "## Graph RAG Context: empty-service" in output
        # Should not contain table headers since there are no endpoints
        assert "| Method |" not in output


class TestTruncateToBudget:
    def test_truncate_to_budget_respects_priority(self) -> None:
        assembler = ContextAssembler()

        # Create sections with different priorities
        high_priority_text = "HIGH PRIORITY CONTENT " * 20  # ~80 chars
        low_priority_text = "LOW PRIORITY CONTENT " * 200  # ~4200 chars

        sections = [
            ("high", high_priority_text, 1),
            ("low", low_priority_text, 5),
        ]

        # Set budget that fits high but not low
        result = assembler.truncate_to_budget(sections, max_tokens=150)

        assert "HIGH PRIORITY CONTENT" in result
        # Low priority content should be truncated or absent
        if "LOW PRIORITY CONTENT" in result:
            assert "[... truncated ...]" in result

    def test_truncate_to_budget_exact_fit(self) -> None:
        assembler = ContextAssembler()

        # Each section is exactly 100 chars = 25 tokens
        section_a = "A" * 100
        section_b = "B" * 100
        section_c = "C" * 100

        sections = [
            ("a", section_a, 1),
            ("b", section_b, 2),
            ("c", section_c, 3),
        ]

        # Budget for all 3 sections (75 tokens) plus separators
        result = assembler.truncate_to_budget(sections, max_tokens=100)
        assert "A" * 100 in result
        assert "B" * 100 in result


class TestCommunitySummary:
    def test_community_summary_format(self) -> None:
        assembler = ContextAssembler()

        members = [
            {"id": "file::auth/main.py", "node_type": "file", "service_name": "auth-service"},
            {"id": "file::auth/models.py", "node_type": "file", "service_name": "auth-service"},
            {"id": "file::order/main.py", "node_type": "file", "service_name": "order-service"},
        ]
        edges = [
            {"source": "file::auth/main.py", "target": "file::auth/models.py", "relation": "IMPORTS"},
        ]

        output = assembler.assemble_community_summary(
            community_id=0,
            members=members,
            edges=edges,
        )

        assert "## Community" in output
        assert "auth-service" in output
        assert "order-service" in output
