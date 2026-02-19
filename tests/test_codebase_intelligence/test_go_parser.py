"""Tests for src.codebase_intelligence.parsers.go_parser.GoParser.

Covers extract_symbols including:
    1. Function detection
    2. Method detection with receiver type as parent_symbol
    3. Struct detection as CLASS kind
    4. Exported (uppercase) vs unexported (lowercase) detection
    5. Correct 1-indexed line numbers
"""

from __future__ import annotations

import pytest

from src.codebase_intelligence.parsers.go_parser import GoParser
from src.shared.models.codebase import SymbolKind


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def parser() -> GoParser:
    """Provide a fresh GoParser instance for each test."""
    return GoParser()


# ---------------------------------------------------------------------------
# 1. Function detection
# ---------------------------------------------------------------------------

class TestExtractFunction:
    """A top-level function declaration should be detected as FUNCTION."""

    def test_extract_function(self, parser: GoParser) -> None:
        """A Go function should be detected with kind=FUNCTION and the
        correct name."""
        source = b"""\
package main

func CalculateTotal(prices []float64) float64 {
    total := 0.0
    for _, p := range prices {
        total += p
    }
    return total
}
"""
        symbols = parser.extract_symbols(source, "pkg/math.go")

        funcs = [s for s in symbols if s["kind"] == SymbolKind.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0]["name"] == "CalculateTotal"
        assert funcs[0]["parent_symbol"] is None


# ---------------------------------------------------------------------------
# 2. Method detection with receiver type
# ---------------------------------------------------------------------------

class TestExtractMethod:
    """A method declaration should have the receiver type as parent_symbol."""

    def test_extract_method(self, parser: GoParser) -> None:
        """A Go method with a pointer receiver should be detected as METHOD
        with parent_symbol set to the receiver type name."""
        source = b"""\
package service

type OrderService struct {
    db *Database
}

func (s *OrderService) ProcessOrder(id string) error {
    return nil
}
"""
        symbols = parser.extract_symbols(source, "service/order.go")

        methods = [s for s in symbols if s["kind"] == SymbolKind.METHOD]
        assert len(methods) == 1
        assert methods[0]["name"] == "ProcessOrder"
        assert methods[0]["parent_symbol"] == "OrderService"

    def test_value_receiver_method(self, parser: GoParser) -> None:
        """A Go method with a value receiver (not pointer) should also
        have parent_symbol set correctly."""
        source = b"""\
package model

type Point struct {
    X int
    Y int
}

func (p Point) String() string {
    return "point"
}
"""
        symbols = parser.extract_symbols(source, "model/point.go")

        methods = [s for s in symbols if s["kind"] == SymbolKind.METHOD]
        assert len(methods) == 1
        assert methods[0]["name"] == "String"
        assert methods[0]["parent_symbol"] == "Point"


# ---------------------------------------------------------------------------
# 3. Struct detection as CLASS kind
# ---------------------------------------------------------------------------

class TestExtractStruct:
    """A struct type declaration should be detected with kind=CLASS."""

    def test_extract_struct(self, parser: GoParser) -> None:
        """A Go struct should be detected as kind=CLASS since Go has no
        explicit class keyword."""
        source = b"""\
package model

type User struct {
    ID   string
    Name string
}
"""
        symbols = parser.extract_symbols(source, "model/user.go")

        structs = [s for s in symbols if s["kind"] == SymbolKind.CLASS]
        assert len(structs) == 1
        assert structs[0]["name"] == "User"
        assert structs[0]["parent_symbol"] is None

    def test_interface_type_detected(self, parser: GoParser) -> None:
        """A Go interface type should be detected as kind=INTERFACE."""
        source = b"""\
package repo

type Repository interface {
    FindByID(id string) error
}
"""
        symbols = parser.extract_symbols(source, "repo/repo.go")

        interfaces = [s for s in symbols if s["kind"] == SymbolKind.INTERFACE]
        assert len(interfaces) == 1
        assert interfaces[0]["name"] == "Repository"


# ---------------------------------------------------------------------------
# 4. Exported (uppercase) vs unexported (lowercase) detection
# ---------------------------------------------------------------------------

class TestExportedUppercase:
    """Go exports symbols starting with uppercase; lowercase are unexported."""

    def test_exported_uppercase(self, parser: GoParser) -> None:
        """An uppercase function name should have is_exported=True while
        a lowercase function name should have is_exported=False."""
        source = b"""\
package utils

func PublicHelper() string {
    return "public"
}

func privateHelper() string {
    return "private"
}
"""
        symbols = parser.extract_symbols(source, "utils/helpers.go")

        funcs = [s for s in symbols if s["kind"] == SymbolKind.FUNCTION]
        public = [f for f in funcs if f["name"] == "PublicHelper"]
        private = [f for f in funcs if f["name"] == "privateHelper"]

        assert len(public) == 1
        assert public[0]["is_exported"] is True

        assert len(private) == 1
        assert private[0]["is_exported"] is False

    def test_exported_struct(self, parser: GoParser) -> None:
        """An uppercase struct name should be exported; lowercase should not."""
        source = b"""\
package model

type ExportedModel struct {
    Field string
}

type internalModel struct {
    field string
}
"""
        symbols = parser.extract_symbols(source, "model/models.go")

        structs = [s for s in symbols if s["kind"] == SymbolKind.CLASS]
        exported = [s for s in structs if s["name"] == "ExportedModel"]
        internal = [s for s in structs if s["name"] == "internalModel"]

        assert len(exported) == 1
        assert exported[0]["is_exported"] is True

        assert len(internal) == 1
        assert internal[0]["is_exported"] is False


# ---------------------------------------------------------------------------
# 5. Correct 1-indexed line numbers
# ---------------------------------------------------------------------------

class TestLineNumbers:
    """Line numbers should be 1-indexed."""

    def test_line_numbers(self, parser: GoParser) -> None:
        """A function on line 3 of the source (after the package declaration
        and blank line) should have line_start=3."""
        source = b"""\
package main

func First() {
}

func Second() {
}
"""
        symbols = parser.extract_symbols(source, "main.go")

        funcs = [s for s in symbols if s["kind"] == SymbolKind.FUNCTION]
        first = [f for f in funcs if f["name"] == "First"]
        second = [f for f in funcs if f["name"] == "Second"]

        assert len(first) == 1
        assert first[0]["line_start"] == 3
        assert first[0]["line_start"] >= 1, "Line numbers must be 1-indexed"

        assert len(second) == 1
        assert second[0]["line_start"] == 6
