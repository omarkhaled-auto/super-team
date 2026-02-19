"""Tests for src.codebase_intelligence.parsers.csharp_parser.CSharpParser.

Covers extract_symbols including:
    1. Public class detection
    2. Interface detection
    3. Method detection with parent_symbol set to the enclosing class
    4. Public classes have is_exported=True
    5. Correct 1-indexed line numbers
"""

from __future__ import annotations

import pytest

from src.codebase_intelligence.parsers.csharp_parser import CSharpParser
from src.shared.models.codebase import SymbolKind


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def parser() -> CSharpParser:
    """Provide a fresh CSharpParser instance for each test."""
    return CSharpParser()


# ---------------------------------------------------------------------------
# 1. Public class detection
# ---------------------------------------------------------------------------

class TestExtractClass:
    """A public class declaration should be detected as a CLASS symbol."""

    def test_extract_class(self, parser: CSharpParser) -> None:
        """A public class should be detected with kind=CLASS, the correct
        name, and is_exported=True."""
        source = b"""\
public class OrderService
{
    public int Id { get; set; }
}
"""
        symbols = parser.extract_symbols(source, "Services/OrderService.cs")

        classes = [s for s in symbols if s["kind"] == SymbolKind.CLASS]
        assert len(classes) >= 1
        order_svc = [c for c in classes if c["name"] == "OrderService"]
        assert len(order_svc) == 1
        assert order_svc[0]["is_exported"] is True
        assert order_svc[0]["parent_symbol"] is None


# ---------------------------------------------------------------------------
# 2. Interface detection
# ---------------------------------------------------------------------------

class TestExtractInterface:
    """An interface declaration should be detected as an INTERFACE symbol."""

    def test_extract_interface(self, parser: CSharpParser) -> None:
        """A public interface should be detected with kind=INTERFACE."""
        source = b"""\
public interface IRepository
{
    void Save();
}
"""
        symbols = parser.extract_symbols(source, "Interfaces/IRepository.cs")

        interfaces = [s for s in symbols if s["kind"] == SymbolKind.INTERFACE]
        assert len(interfaces) == 1
        assert interfaces[0]["name"] == "IRepository"
        assert interfaces[0]["is_exported"] is True


# ---------------------------------------------------------------------------
# 3. Method detection with parent_symbol
# ---------------------------------------------------------------------------

class TestExtractMethod:
    """A method inside a class should have kind=METHOD and parent_symbol set."""

    def test_extract_method(self, parser: CSharpParser) -> None:
        """A public method inside a public class should be detected as METHOD
        with parent_symbol equal to the enclosing class name."""
        source = b"""\
public class UserService
{
    public void CreateUser(string name)
    {
        // implementation
    }
}
"""
        symbols = parser.extract_symbols(source, "Services/UserService.cs")

        methods = [s for s in symbols if s["kind"] == SymbolKind.METHOD]
        assert len(methods) == 1
        assert methods[0]["name"] == "CreateUser"
        assert methods[0]["parent_symbol"] == "UserService"

    def test_private_method_not_exported(self, parser: CSharpParser) -> None:
        """A private method inside a class should have is_exported=False."""
        source = b"""\
public class Helper
{
    private void InternalWork()
    {
    }
}
"""
        symbols = parser.extract_symbols(source, "Helpers/Helper.cs")

        methods = [s for s in symbols if s["kind"] == SymbolKind.METHOD]
        assert len(methods) == 1
        assert methods[0]["name"] == "InternalWork"
        assert methods[0]["is_exported"] is False


# ---------------------------------------------------------------------------
# 4. Exported detection (public vs non-public)
# ---------------------------------------------------------------------------

class TestExportedDetection:
    """Public classes should be exported, internal classes should not."""

    def test_exported_detection(self, parser: CSharpParser) -> None:
        """A public class should have is_exported=True; a class without
        public modifier should have is_exported=False."""
        source = b"""\
public class PublicModel
{
}

class InternalModel
{
}
"""
        symbols = parser.extract_symbols(source, "Models/Models.cs")

        classes = [s for s in symbols if s["kind"] == SymbolKind.CLASS]
        public = [c for c in classes if c["name"] == "PublicModel"]
        internal = [c for c in classes if c["name"] == "InternalModel"]

        assert len(public) == 1
        assert public[0]["is_exported"] is True

        assert len(internal) == 1
        assert internal[0]["is_exported"] is False


# ---------------------------------------------------------------------------
# 5. Correct 1-indexed line numbers
# ---------------------------------------------------------------------------

class TestLineNumbers:
    """Line numbers should be 1-indexed."""

    def test_line_numbers(self, parser: CSharpParser) -> None:
        """The first class on line 1 should have line_start=1. A class
        starting on a later line should have the correct offset."""
        source = b"""\
public class First
{
}

public class Second
{
}
"""
        symbols = parser.extract_symbols(source, "Models/Two.cs")

        classes = [s for s in symbols if s["kind"] == SymbolKind.CLASS]
        first = [c for c in classes if c["name"] == "First"]
        second = [c for c in classes if c["name"] == "Second"]

        assert len(first) == 1
        assert first[0]["line_start"] == 1
        assert first[0]["line_start"] >= 1, "Line numbers must be 1-indexed"

        assert len(second) == 1
        assert second[0]["line_start"] == 5

    def test_method_line_number(self, parser: CSharpParser) -> None:
        """A method defined inside a class should have the correct line_start."""
        source = b"""\
public class MyClass
{
    public void DoWork()
    {
    }
}
"""
        symbols = parser.extract_symbols(source, "Services/MyClass.cs")

        methods = [s for s in symbols if s["kind"] == SymbolKind.METHOD]
        assert len(methods) == 1
        assert methods[0]["line_start"] == 3
