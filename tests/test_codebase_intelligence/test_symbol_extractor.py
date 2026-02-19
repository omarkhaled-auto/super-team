"""Tests for the SymbolExtractor service that converts raw parser dicts to SymbolDefinition models."""
from __future__ import annotations

import logging

import pytest

from src.codebase_intelligence.services.symbol_extractor import SymbolExtractor
from src.shared.models.codebase import SymbolDefinition, SymbolKind, Language


@pytest.fixture(scope="module")
def extractor() -> SymbolExtractor:
    """Shared SymbolExtractor instance for all tests in this module."""
    return SymbolExtractor()


def _make_raw_symbol(
    *,
    name: str = "example",
    kind: str = "function",
    line_start: int = 1,
    line_end: int = 10,
    signature: str | None = "def example()",
    docstring: str | None = None,
    is_exported: bool = True,
    parent_symbol: str | None = None,
) -> dict:
    """Helper to build a raw symbol dict matching the parser output format."""
    return {
        "name": name,
        "kind": kind,
        "line_start": line_start,
        "line_end": line_end,
        "signature": signature,
        "docstring": docstring,
        "is_exported": is_exported,
        "parent_symbol": parent_symbol,
    }


# ---------------------------------------------------------------------------
# Symbol kind mapping tests
# ---------------------------------------------------------------------------


class TestKindMapping:
    """Tests for correct mapping of raw kind strings to SymbolKind enum values."""

    def test_extract_class_symbol(self, extractor: SymbolExtractor) -> None:
        """A raw symbol with kind='class' should produce a SymbolDefinition with kind=CLASS."""
        raw = [_make_raw_symbol(name="UserService", kind="class")]
        results = extractor.extract_symbols(raw, "services/user.py", "python")

        assert len(results) == 1
        assert isinstance(results[0], SymbolDefinition)
        assert results[0].kind == SymbolKind.CLASS
        assert results[0].symbol_name == "UserService"

    def test_extract_function_symbol(self, extractor: SymbolExtractor) -> None:
        """A raw symbol with kind='function' should produce a SymbolDefinition with kind=FUNCTION."""
        raw = [_make_raw_symbol(name="process_order", kind="function")]
        results = extractor.extract_symbols(raw, "handlers/order.py", "python")

        assert len(results) == 1
        assert results[0].kind == SymbolKind.FUNCTION
        assert results[0].symbol_name == "process_order"

    def test_extract_interface_symbol(self, extractor: SymbolExtractor) -> None:
        """A raw symbol with kind='interface' should map to SymbolKind.INTERFACE."""
        raw = [_make_raw_symbol(name="IRepository", kind="interface")]
        results = extractor.extract_symbols(raw, "interfaces/repo.ts", "typescript")

        assert len(results) == 1
        assert results[0].kind == SymbolKind.INTERFACE

    def test_extract_type_symbol(self, extractor: SymbolExtractor) -> None:
        """A raw symbol with kind='type' should map to SymbolKind.TYPE."""
        raw = [_make_raw_symbol(name="Config", kind="type")]
        results = extractor.extract_symbols(raw, "types/config.ts", "typescript")

        assert len(results) == 1
        assert results[0].kind == SymbolKind.TYPE


# ---------------------------------------------------------------------------
# Field propagation tests
# ---------------------------------------------------------------------------


class TestFieldPropagation:
    """Tests verifying that fields from raw dicts are correctly propagated."""

    def test_extract_method_with_parent(self, extractor: SymbolExtractor) -> None:
        """A method raw symbol with parent_symbol set should propagate that to the model."""
        raw = [_make_raw_symbol(
            name="get_user",
            kind="method",
            parent_symbol="UserService",
        )]
        results = extractor.extract_symbols(raw, "services/user.py", "python")

        assert len(results) == 1
        assert results[0].kind == SymbolKind.METHOD
        assert results[0].parent_symbol == "UserService"

    def test_auto_generated_id(self, extractor: SymbolExtractor) -> None:
        """The SymbolDefinition.id should be auto-generated as '{file_path}::{symbol_name}'."""
        raw = [_make_raw_symbol(name="MyClass", kind="class")]
        results = extractor.extract_symbols(raw, "src/models.py", "python")

        assert len(results) == 1
        assert results[0].id == "src/models.py::MyClass"

    def test_service_name_propagation(self, extractor: SymbolExtractor) -> None:
        """The service_name argument should be propagated to all extracted symbols."""
        raw = [
            _make_raw_symbol(name="Alpha", kind="class"),
            _make_raw_symbol(name="beta", kind="function"),
        ]
        results = extractor.extract_symbols(
            raw, "src/alpha.py", "python", service_name="auth-service"
        )

        assert len(results) == 2
        for sym in results:
            assert sym.service_name == "auth-service"

    def test_docstring_preserved(self, extractor: SymbolExtractor) -> None:
        """The docstring from the raw dict should be preserved in the SymbolDefinition."""
        raw = [_make_raw_symbol(
            name="calculate",
            kind="function",
            docstring="Calculate the total price including tax.",
        )]
        results = extractor.extract_symbols(raw, "utils/calc.py", "python")

        assert len(results) == 1
        assert results[0].docstring == "Calculate the total price including tax."

    def test_line_numbers_preserved(self, extractor: SymbolExtractor) -> None:
        """The line_start and line_end from the raw dict should match the SymbolDefinition."""
        raw = [_make_raw_symbol(
            name="Handler",
            kind="class",
            line_start=15,
            line_end=42,
        )]
        results = extractor.extract_symbols(raw, "handlers/base.py", "python")

        assert len(results) == 1
        assert results[0].line_start == 15
        assert results[0].line_end == 42


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for graceful handling of invalid or unexpected input."""

    def test_invalid_kind_handled(
        self, extractor: SymbolExtractor, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An invalid kind string should log a warning but not crash."""
        raw = [_make_raw_symbol(name="BadSymbol", kind="nonexistent_kind")]

        with caplog.at_level(logging.WARNING):
            results = extractor.extract_symbols(raw, "bad.py", "python")

        # The symbol should be skipped (not added) because _map_kind raises ValueError
        assert len(results) == 0
        assert any("Failed to create SymbolDefinition" in msg for msg in caplog.messages)
