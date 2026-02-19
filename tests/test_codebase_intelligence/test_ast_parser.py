"""Tests for the ASTParser multi-language parser service."""
from __future__ import annotations

import pytest

from src.codebase_intelligence.services.ast_parser import ASTParser
from src.shared.errors import ParsingError


@pytest.fixture(scope="module")
def parser() -> ASTParser:
    """Shared ASTParser instance for all tests in this module."""
    return ASTParser()


# ---------------------------------------------------------------------------
# detect_language tests
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    """Tests for ASTParser.detect_language()."""

    def test_detect_language_python(self, parser: ASTParser) -> None:
        """A .py file extension should be detected as python."""
        assert parser.detect_language("src/main.py") == "python"
        assert parser.detect_language("models.pyi") == "python"

    def test_detect_language_typescript(self, parser: ASTParser) -> None:
        """Both .ts and .tsx file extensions should be detected as typescript."""
        assert parser.detect_language("app/index.ts") == "typescript"
        assert parser.detect_language("components/Button.tsx") == "typescript"

    def test_detect_language_csharp(self, parser: ASTParser) -> None:
        """A .cs file extension should be detected as csharp."""
        assert parser.detect_language("Controllers/UserController.cs") == "csharp"

    def test_detect_language_go(self, parser: ASTParser) -> None:
        """A .go file extension should be detected as go."""
        assert parser.detect_language("cmd/server/main.go") == "go"

    def test_detect_language_unsupported(self, parser: ASTParser) -> None:
        """Unsupported file extensions should return None."""
        assert parser.detect_language("readme.txt") is None
        assert parser.detect_language("data.json") is None
        assert parser.detect_language("style.css") is None
        assert parser.detect_language("Makefile") is None


# ---------------------------------------------------------------------------
# parse_file tests
# ---------------------------------------------------------------------------


class TestParseFile:
    """Tests for ASTParser.parse_file()."""

    def test_parse_python_file(self, parser: ASTParser) -> None:
        """Parsing a Python file with a class and a function should extract both symbols."""
        source = b'''\
class UserService:
    """Handles user operations."""

    def get_user(self, user_id: int) -> dict:
        """Fetch a user by ID."""
        return {}


def standalone_helper(x: int) -> str:
    """A standalone helper function."""
    return str(x)
'''
        result = parser.parse_file(source, "services/user.py")

        assert result["language"] == "python"
        assert result["tree"] is not None

        symbols = result["symbols"]
        names = [s["name"] for s in symbols]
        assert "UserService" in names
        assert "get_user" in names
        assert "standalone_helper" in names

        # Verify the class symbol has correct kind
        class_sym = next(s for s in symbols if s["name"] == "UserService")
        assert class_sym["kind"].value == "class" or str(class_sym["kind"]) == "class"

        # Verify the method has a parent_symbol
        method_sym = next(s for s in symbols if s["name"] == "get_user")
        assert method_sym["parent_symbol"] == "UserService"

    def test_parse_typescript_file(self, parser: ASTParser) -> None:
        """Parsing a TypeScript file with an interface and a class should extract both."""
        source = b'''\
export interface IUser {
    id: number;
    name: string;
}

export class UserRepository {
    findById(id: number): IUser | null {
        return null;
    }
}
'''
        result = parser.parse_file(source, "repositories/user.ts")

        assert result["language"] == "typescript"
        assert result["tree"] is not None

        symbols = result["symbols"]
        names = [s["name"] for s in symbols]
        assert "IUser" in names
        assert "UserRepository" in names

        # Verify interface kind
        iface_sym = next(s for s in symbols if s["name"] == "IUser")
        assert iface_sym["kind"] == "interface"

        # Verify class kind
        class_sym = next(s for s in symbols if s["name"] == "UserRepository")
        assert class_sym["kind"] == "class"

    def test_parse_csharp_file(self, parser: ASTParser) -> None:
        """Parsing a C# file with a class and a method should extract both symbols."""
        source = b'''\
namespace MyApp.Services
{
    public class OrderService
    {
        public void ProcessOrder(int orderId)
        {
            // process
        }
    }
}
'''
        result = parser.parse_file(source, "Services/OrderService.cs")

        assert result["language"] == "csharp"
        assert result["tree"] is not None

        symbols = result["symbols"]
        names = [s["name"] for s in symbols]
        assert "OrderService" in names
        assert "ProcessOrder" in names

        # Verify the method has parent_symbol pointing to the class
        method_sym = next(s for s in symbols if s["name"] == "ProcessOrder")
        assert method_sym["parent_symbol"] == "OrderService"

    def test_parse_go_file(self, parser: ASTParser) -> None:
        """Parsing a Go file with a function and a type should extract both symbols."""
        source = b'''\
package main

// Server holds the application state.
type Server struct {
    Port int
}

// Run starts the server.
func Run() {
    // start
}
'''
        result = parser.parse_file(source, "cmd/main.go")

        assert result["language"] == "go"
        assert result["tree"] is not None

        symbols = result["symbols"]
        names = [s["name"] for s in symbols]
        assert "Run" in names
        assert "Server" in names

        # Verify Run is a function
        func_sym = next(s for s in symbols if s["name"] == "Run")
        func_kind = func_sym["kind"]
        assert func_kind == "function" or (hasattr(func_kind, "value") and func_kind.value == "function")

    def test_parse_unsupported_raises(self, parser: ASTParser) -> None:
        """Attempting to parse a file with an unsupported extension should raise ParsingError."""
        with pytest.raises(ParsingError, match="Unsupported file extension"):
            parser.parse_file(b"some content", "data.json")

    def test_parse_empty_file(self, parser: ASTParser) -> None:
        """Parsing an empty source file should return an empty symbols list."""
        result = parser.parse_file(b"", "empty.py")

        assert result["language"] == "python"
        assert result["symbols"] == []
        assert result["tree"] is not None
