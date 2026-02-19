"""Tests for src.codebase_intelligence.parsers.typescript_parser.TypeScriptParser.

Covers extract_symbols including:
    1. Interface detection with kind="interface"
    2. Class detection with kind="class"
    3. Exported function detection
    4. Type alias detection with kind="type"
    5. Method inside class has parent_symbol
    6. Export detection (is_exported=True for exported items)
    7. TSX file uses the tsx language parser
"""

from __future__ import annotations

import pytest

from src.codebase_intelligence.parsers.typescript_parser import TypeScriptParser
from src.shared.models.codebase import SymbolKind


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def parser() -> TypeScriptParser:
    """Provide a fresh TypeScriptParser instance for each test."""
    return TypeScriptParser()


# ---------------------------------------------------------------------------
# 1. Interface detection
# ---------------------------------------------------------------------------

class TestExtractInterface:
    """An interface declaration should produce a symbol with kind='interface'."""

    def test_extract_interface(self, parser: TypeScriptParser) -> None:
        """A TypeScript interface should be detected with kind='interface'
        and the correct name."""
        source = b"""\
interface UserProfile {
    name: string;
    email: string;
}
"""
        symbols = parser.extract_symbols(source, "src/models.ts")

        interfaces = [s for s in symbols if s["kind"] == SymbolKind.INTERFACE.value]
        assert len(interfaces) == 1
        assert interfaces[0]["name"] == "UserProfile"


# ---------------------------------------------------------------------------
# 2. Class detection
# ---------------------------------------------------------------------------

class TestExtractClass:
    """A class declaration should produce a symbol with kind='class'."""

    def test_extract_class(self, parser: TypeScriptParser) -> None:
        """A TypeScript class should be detected with kind='class'."""
        source = b"""\
class OrderService {
    private items: string[];

    constructor() {
        this.items = [];
    }
}
"""
        symbols = parser.extract_symbols(source, "src/order.ts")

        classes = [s for s in symbols if s["kind"] == SymbolKind.CLASS.value]
        assert len(classes) == 1
        assert classes[0]["name"] == "OrderService"


# ---------------------------------------------------------------------------
# 3. Exported function detection
# ---------------------------------------------------------------------------

class TestExtractFunction:
    """An exported function declaration should be detected."""

    def test_extract_function(self, parser: TypeScriptParser) -> None:
        """An exported function should be detected as kind='function'
        with is_exported=True."""
        source = b"""\
export function calculateTotal(prices: number[]): number {
    return prices.reduce((a, b) => a + b, 0);
}
"""
        symbols = parser.extract_symbols(source, "src/utils.ts")

        funcs = [s for s in symbols if s["kind"] == SymbolKind.FUNCTION.value]
        assert len(funcs) == 1
        assert funcs[0]["name"] == "calculateTotal"
        assert funcs[0]["is_exported"] is True


# ---------------------------------------------------------------------------
# 4. Type alias detection
# ---------------------------------------------------------------------------

class TestExtractTypeAlias:
    """A type alias declaration should produce a symbol with kind='type'."""

    def test_extract_type_alias(self, parser: TypeScriptParser) -> None:
        """A TypeScript type alias should be detected with kind='type'."""
        source = b"""\
type UserId = string;
"""
        symbols = parser.extract_symbols(source, "src/types.ts")

        types = [s for s in symbols if s["kind"] == SymbolKind.TYPE.value]
        assert len(types) == 1
        assert types[0]["name"] == "UserId"


# ---------------------------------------------------------------------------
# 5. Method inside class has parent_symbol
# ---------------------------------------------------------------------------

class TestExtractMethod:
    """A method inside a class should have parent_symbol set to the class name."""

    def test_extract_method(self, parser: TypeScriptParser) -> None:
        """A method defined inside a class body should have kind='method'
        and parent_symbol equal to the enclosing class name."""
        source = b"""\
class UserRepository {
    findById(id: string): User {
        return this.db.find(id);
    }
}
"""
        symbols = parser.extract_symbols(source, "src/repo.ts")

        methods = [s for s in symbols if s["kind"] == SymbolKind.METHOD.value]
        assert len(methods) == 1
        assert methods[0]["name"] == "findById"
        assert methods[0]["parent_symbol"] == "UserRepository"


# ---------------------------------------------------------------------------
# 6. Export detection
# ---------------------------------------------------------------------------

class TestExportDetection:
    """Exported items should have is_exported=True, non-exported should be False."""

    def test_export_detection(self, parser: TypeScriptParser) -> None:
        """An exported interface should have is_exported=True, while a
        non-exported interface should have is_exported=False."""
        source = b"""\
export interface PublicApi {
    endpoint: string;
}

interface InternalConfig {
    debug: boolean;
}
"""
        symbols = parser.extract_symbols(source, "src/api.ts")

        public = [s for s in symbols if s["name"] == "PublicApi"]
        internal = [s for s in symbols if s["name"] == "InternalConfig"]

        assert len(public) == 1
        assert public[0]["is_exported"] is True

        assert len(internal) == 1
        assert internal[0]["is_exported"] is False


# ---------------------------------------------------------------------------
# 7. TSX file uses tsx language parser
# ---------------------------------------------------------------------------

class TestTsxFile:
    """A .tsx file should be parsed using the TSX language grammar."""

    def test_tsx_file(self, parser: TypeScriptParser) -> None:
        """A .tsx file containing JSX syntax should be parsed without errors
        and its symbols should be detected correctly."""
        source = b"""\
interface Props {
    title: string;
}

function Greeting(props: Props) {
    return <div>{props.title}</div>;
}
"""
        symbols = parser.extract_symbols(source, "src/components/Greeting.tsx")

        interfaces = [s for s in symbols if s["kind"] == SymbolKind.INTERFACE.value]
        funcs = [s for s in symbols if s["kind"] == SymbolKind.FUNCTION.value]

        assert len(interfaces) == 1
        assert interfaces[0]["name"] == "Props"

        assert len(funcs) == 1
        assert funcs[0]["name"] == "Greeting"

    def test_tsx_vs_ts_both_work(self, parser: TypeScriptParser) -> None:
        """The same non-JSX source should parse identically whether the
        file_path ends in .ts or .tsx."""
        source = b"""\
interface Config {
    port: number;
}
"""
        ts_symbols = parser.extract_symbols(source, "src/config.ts")
        tsx_symbols = parser.extract_symbols(source, "src/config.tsx")

        assert len(ts_symbols) == len(tsx_symbols)
        assert ts_symbols[0]["name"] == tsx_symbols[0]["name"]
