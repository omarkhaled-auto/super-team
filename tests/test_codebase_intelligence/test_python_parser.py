"""Tests for src.codebase_intelligence.parsers.python_parser.PythonParser.

Covers extract_symbols including:
    1. Class detection with kind=CLASS
    2. Function detection with kind=FUNCTION
    3. Method detection with kind=METHOD and parent_symbol
    4. Docstring extraction
    5. Private symbols have is_exported=False
    6. Decorated functions are detected correctly
    7. Line numbers are 1-indexed
"""

from __future__ import annotations

import pytest

from src.codebase_intelligence.parsers.python_parser import PythonParser
from src.shared.models.codebase import SymbolKind


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def parser() -> PythonParser:
    """Provide a fresh PythonParser instance for each test."""
    return PythonParser()


# ---------------------------------------------------------------------------
# 1. Class detection
# ---------------------------------------------------------------------------

class TestExtractClass:
    """A class definition should produce a symbol with kind=CLASS."""

    def test_extract_class(self, parser: PythonParser) -> None:
        """A simple class definition should be detected as a CLASS symbol
        with the correct name and is_exported=True."""
        source = b"""\
class OrderService:
    pass
"""
        symbols = parser.extract_symbols(source, "app/order.py")

        classes = [s for s in symbols if s["kind"] == SymbolKind.CLASS]
        assert len(classes) == 1
        assert classes[0]["name"] == "OrderService"
        assert classes[0]["is_exported"] is True
        assert classes[0]["parent_symbol"] is None


# ---------------------------------------------------------------------------
# 2. Function detection
# ---------------------------------------------------------------------------

class TestExtractFunction:
    """A top-level function definition should produce a symbol with kind=FUNCTION."""

    def test_extract_function(self, parser: PythonParser) -> None:
        """A top-level function should be detected as a FUNCTION symbol."""
        source = b"""\
def compute_total(items):
    return sum(items)
"""
        symbols = parser.extract_symbols(source, "app/utils.py")

        funcs = [s for s in symbols if s["kind"] == SymbolKind.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0]["name"] == "compute_total"
        assert funcs[0]["is_exported"] is True
        assert funcs[0]["parent_symbol"] is None


# ---------------------------------------------------------------------------
# 3. Method detection (inside a class)
# ---------------------------------------------------------------------------

class TestExtractMethod:
    """A function inside a class body should be a METHOD with parent_symbol set."""

    def test_extract_method(self, parser: PythonParser) -> None:
        """A method inside a class should have kind=METHOD and parent_symbol
        equal to the enclosing class name."""
        source = b"""\
class UserService:
    def get_user(self, user_id):
        pass
"""
        symbols = parser.extract_symbols(source, "app/users.py")

        methods = [s for s in symbols if s["kind"] == SymbolKind.METHOD]
        assert len(methods) == 1
        assert methods[0]["name"] == "get_user"
        assert methods[0]["parent_symbol"] == "UserService"


# ---------------------------------------------------------------------------
# 4. Docstring extraction
# ---------------------------------------------------------------------------

class TestExtractDocstring:
    """Docstrings should be extracted from class and function definitions."""

    def test_extract_docstring_from_function(self, parser: PythonParser) -> None:
        """A function with a triple-quoted docstring should have it extracted
        into the docstring field."""
        source = b'''\
def greet(name):
    """Say hello to the given name."""
    return f"Hello, {name}"
'''
        symbols = parser.extract_symbols(source, "app/greet.py")

        funcs = [s for s in symbols if s["kind"] == SymbolKind.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0]["docstring"] == "Say hello to the given name."

    def test_extract_docstring_from_class(self, parser: PythonParser) -> None:
        """A class with a docstring should have it extracted."""
        source = b'''\
class Engine:
    """Core processing engine."""
    pass
'''
        symbols = parser.extract_symbols(source, "app/engine.py")

        classes = [s for s in symbols if s["kind"] == SymbolKind.CLASS]
        assert len(classes) == 1
        assert classes[0]["docstring"] == "Core processing engine."


# ---------------------------------------------------------------------------
# 5. Private symbols have is_exported=False
# ---------------------------------------------------------------------------

class TestPrivateNotExported:
    """Symbols starting with an underscore should have is_exported=False."""

    def test_private_not_exported(self, parser: PythonParser) -> None:
        """A function whose name starts with '_' should not be exported."""
        source = b"""\
def _internal_setup():
    pass
"""
        symbols = parser.extract_symbols(source, "app/helpers.py")

        funcs = [s for s in symbols if s["kind"] == SymbolKind.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0]["name"] == "_internal_setup"
        assert funcs[0]["is_exported"] is False


# ---------------------------------------------------------------------------
# 6. Decorated function detection
# ---------------------------------------------------------------------------

class TestDecoratedFunction:
    """Decorated functions should be detected correctly without duplication."""

    def test_decorated_function(self, parser: PythonParser) -> None:
        """A function with a decorator should be detected as a single symbol
        with the correct name and kind."""
        source = b"""\
@staticmethod
def format_output(data):
    return str(data)
"""
        symbols = parser.extract_symbols(source, "app/formatters.py")

        funcs = [s for s in symbols if s["name"] == "format_output"]
        assert len(funcs) == 1
        assert funcs[0]["kind"] == SymbolKind.FUNCTION

    def test_decorated_method_no_duplication(self, parser: PythonParser) -> None:
        """A decorated method inside a class should appear exactly once."""
        source = b"""\
class Service:
    @property
    def name(self):
        return self._name
"""
        symbols = parser.extract_symbols(source, "app/service.py")

        name_syms = [s for s in symbols if s["name"] == "name"]
        assert len(name_syms) == 1
        assert name_syms[0]["kind"] == SymbolKind.METHOD
        assert name_syms[0]["parent_symbol"] == "Service"


# ---------------------------------------------------------------------------
# 7. Line numbers are 1-indexed
# ---------------------------------------------------------------------------

class TestLineNumbersOneIndexed:
    """Line numbers should start at 1, not 0."""

    def test_line_numbers_one_indexed(self, parser: PythonParser) -> None:
        """The first line of source code should be reported as line 1."""
        source = b"""\
def first_function():
    pass
"""
        symbols = parser.extract_symbols(source, "app/main.py")

        funcs = [s for s in symbols if s["kind"] == SymbolKind.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0]["line_start"] == 1
        assert funcs[0]["line_start"] >= 1, "Line numbers must be 1-indexed"

    def test_second_function_line_offset(self, parser: PythonParser) -> None:
        """A function on line 4 of the source should have line_start=4."""
        source = b"""\
def first():
    pass

def second():
    pass
"""
        symbols = parser.extract_symbols(source, "app/main.py")

        second = [s for s in symbols if s["name"] == "second"]
        assert len(second) == 1
        assert second[0]["line_start"] == 4
