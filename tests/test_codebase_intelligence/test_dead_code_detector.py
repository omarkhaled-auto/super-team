"""Tests for src.codebase_intelligence.services.dead_code_detector.DeadCodeDetector.

Covers the find_dead_code method including:
    1. Referenced symbols are not flagged
    2. Unreferenced exported symbols are flagged
    3. Entry point functions (main) are excluded
    4. Test functions (test_*) are excluded
    5. Dunder methods (__init__) are excluded
    6. Private (non-exported) symbols are skipped
    7. High confidence for plain unreferenced functions
    8. Medium confidence for methods
    9. Low confidence for handler-like names
   10. Lifecycle methods (setUp, etc.) are excluded
"""

from __future__ import annotations

import pytest
import networkx as nx

from src.codebase_intelligence.services.dead_code_detector import DeadCodeDetector
from src.shared.models.codebase import DeadCodeEntry, SymbolDefinition, SymbolKind, Language


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _symbol(
    name: str,
    kind: SymbolKind = SymbolKind.FUNCTION,
    is_exported: bool = True,
    file_path: str = "app/service.py",
    parent_symbol: str | None = None,
    line_start: int = 1,
    line_end: int = 5,
    language: Language = Language.PYTHON,
) -> SymbolDefinition:
    """Build a SymbolDefinition with sensible defaults."""
    return SymbolDefinition(
        file_path=file_path,
        symbol_name=name,
        kind=kind,
        language=language,
        line_start=line_start,
        line_end=line_end,
        is_exported=is_exported,
        parent_symbol=parent_symbol,
    )


def _detector() -> DeadCodeDetector:
    """Create a DeadCodeDetector backed by an empty directed graph."""
    return DeadCodeDetector(nx.DiGraph())


# ---------------------------------------------------------------------------
# 1. Referenced symbol is NOT flagged as dead
# ---------------------------------------------------------------------------

class TestReferencedSymbol:
    """A symbol whose id appears in the referenced set must not be flagged."""

    def test_referenced_symbol_not_dead(self) -> None:
        """When a symbol's id is in the referenced_symbols set, it should
        not appear in the dead-code results."""
        sym = _symbol("compute_total")
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols={sym.id},
        )

        assert result == [], f"Expected no dead code, got: {result}"


# ---------------------------------------------------------------------------
# 2. Unreferenced exported symbol IS flagged
# ---------------------------------------------------------------------------

class TestUnreferencedSymbol:
    """An exported symbol not in the referenced set must be flagged."""

    def test_unreferenced_symbol_is_dead(self) -> None:
        """An exported function that is not referenced anywhere should be
        reported as dead code."""
        sym = _symbol("orphaned_helper")
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert len(result) == 1
        entry = result[0]
        assert entry.symbol_name == "orphaned_helper"
        assert entry.file_path == "app/service.py"
        assert entry.kind == SymbolKind.FUNCTION


# ---------------------------------------------------------------------------
# 3. Entry point function (main) is excluded
# ---------------------------------------------------------------------------

class TestEntryPointExcluded:
    """The 'main' function should never be flagged as dead code."""

    def test_entry_point_excluded(self) -> None:
        """A function named 'main' must be excluded from dead code results
        even when it has no references."""
        sym = _symbol("main")
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert result == [], "main should never be flagged as dead code"


# ---------------------------------------------------------------------------
# 4. Test functions (test_*) are excluded
# ---------------------------------------------------------------------------

class TestTestFunctionExcluded:
    """Functions matching the test_* pattern should never be flagged."""

    def test_test_function_excluded(self) -> None:
        """A function whose name starts with 'test_' must be excluded from
        dead code results even when unreferenced."""
        sym = _symbol("test_my_feature")
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert result == [], "test_ functions should never be flagged as dead code"


# ---------------------------------------------------------------------------
# 5. Dunder methods (__init__) are excluded
# ---------------------------------------------------------------------------

class TestDunderMethodExcluded:
    """Dunder methods like __init__ should never be flagged."""

    def test_dunder_method_excluded(self) -> None:
        """A method named '__init__' must be excluded from dead code results
        because it is a special Python method."""
        sym = _symbol(
            "__init__",
            kind=SymbolKind.METHOD,
            parent_symbol="MyClass",
        )
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert result == [], "__init__ should never be flagged as dead code"


# ---------------------------------------------------------------------------
# 6. Private (non-exported) symbols are skipped
# ---------------------------------------------------------------------------

class TestPrivateSymbolExcluded:
    """Non-exported symbols should be skipped entirely."""

    def test_private_symbol_excluded(self) -> None:
        """A symbol with is_exported=False should not appear in dead code
        results, regardless of whether it is referenced."""
        sym = _symbol("_internal_helper", is_exported=False)
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert result == [], "Private symbols should be skipped"


# ---------------------------------------------------------------------------
# 7. Confidence high for plain unreferenced functions
# ---------------------------------------------------------------------------

class TestConfidenceHigh:
    """A plain unreferenced exported function should get high confidence."""

    def test_confidence_high(self) -> None:
        """An unreferenced top-level function with a generic name should be
        reported with confidence='high'."""
        sym = _symbol("calculate_discount")
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert len(result) == 1
        assert result[0].confidence == "high"


# ---------------------------------------------------------------------------
# 8. Confidence medium for methods
# ---------------------------------------------------------------------------

class TestConfidenceMedium:
    """Methods get medium confidence because they might be used via polymorphism."""

    def test_confidence_medium(self) -> None:
        """An unreferenced method inside a class should be reported with
        confidence='medium' since it may be invoked through a base class."""
        sym = _symbol(
            "process",
            kind=SymbolKind.METHOD,
            parent_symbol="OrderService",
        )
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert len(result) == 1
        assert result[0].confidence == "medium"


# ---------------------------------------------------------------------------
# 9. Confidence low for handler-like names
# ---------------------------------------------------------------------------

class TestConfidenceLow:
    """Handler-like names get low confidence because they might be called dynamically."""

    def test_confidence_low(self) -> None:
        """An unreferenced function whose name starts with 'handle_' should
        get confidence='low' because it may be a dynamic handler."""
        sym = _symbol("handle_payment")
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert len(result) == 1
        assert result[0].confidence == "low"

    def test_on_prefix_gets_low_confidence(self) -> None:
        """An unreferenced function whose name starts with 'on_' should also
        get confidence='low'."""
        sym = _symbol("on_message_received")
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert len(result) == 1
        assert result[0].confidence == "low"


# ---------------------------------------------------------------------------
# 10. Lifecycle methods (setUp, tearDown) are excluded
# ---------------------------------------------------------------------------

class TestLifecycleExcluded:
    """Lifecycle methods like setUp and tearDown should never be flagged."""

    def test_lifecycle_excluded(self) -> None:
        """A method named 'setUp' must be excluded because it is a standard
        unittest lifecycle method invoked by the framework."""
        sym = _symbol(
            "setUp",
            kind=SymbolKind.METHOD,
            parent_symbol="TestOrderService",
        )
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert result == [], "setUp should never be flagged as dead code"

    def test_teardown_excluded(self) -> None:
        """A method named 'tearDown' must also be excluded as a lifecycle method."""
        sym = _symbol(
            "tearDown",
            kind=SymbolKind.METHOD,
            parent_symbol="TestOrderService",
        )
        detector = _detector()

        result = detector.find_dead_code(
            symbols=[sym],
            referenced_symbols=set(),
        )

        assert result == [], "tearDown should never be flagged as dead code"
