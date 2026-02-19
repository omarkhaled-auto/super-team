"""Multi-language AST parser using tree-sitter 0.25.2."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser
import tree_sitter_python
import tree_sitter_typescript
import tree_sitter_c_sharp
import tree_sitter_go

from src.shared.models.codebase import SymbolKind, Language as LangEnum
from src.shared.errors import ParsingError
from src.codebase_intelligence.parsers.python_parser import PythonParser
from src.codebase_intelligence.parsers.typescript_parser import TypeScriptParser
from src.codebase_intelligence.parsers.csharp_parser import CSharpParser
from src.codebase_intelligence.parsers.go_parser import GoParser

logger = logging.getLogger(__name__)

# Extension to language mapping
_EXTENSION_MAP = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",  # Uses language_tsx() internally
    ".cs": "csharp",
    ".go": "go",
}


class ASTParser:
    """Multi-language AST parser that detects language from file extension
    and delegates to language-specific parsers.
    """

    def __init__(self) -> None:
        # Initialize language-specific parsers (WIRE-012)
        self._python_parser = PythonParser()
        self._typescript_parser = TypeScriptParser()
        self._csharp_parser = CSharpParser()
        self._go_parser = GoParser()

        # Also store tree-sitter Language objects for raw parsing
        self._languages = {
            "python": Language(tree_sitter_python.language()),
            "typescript": Language(tree_sitter_typescript.language_typescript()),
            "tsx": Language(tree_sitter_typescript.language_tsx()),
            "csharp": Language(tree_sitter_c_sharp.language()),
            "go": Language(tree_sitter_go.language()),
        }

    def detect_language(self, file_path: str) -> str | None:
        """Detect language from file extension.
        Returns language string or None if unsupported."""
        ext = Path(file_path).suffix.lower()
        return _EXTENSION_MAP.get(ext)

    def parse_file(self, source: bytes, file_path: str) -> dict:
        """Parse a source file and return extracted symbols.

        Args:
            source: Raw source bytes
            file_path: Path to the file

        Returns:
            Dict with keys:
            - language: str - detected language
            - symbols: list[dict] - extracted symbols
            - tree: tree_sitter.Tree - the parsed AST tree

        Raises:
            ParsingError: If file extension is unsupported or parsing fails
        """
        language = self.detect_language(file_path)
        if language is None:
            raise ParsingError(f"Unsupported file extension: {Path(file_path).suffix}")

        try:
            # Get appropriate tree-sitter language
            ts_lang_key = "tsx" if file_path.endswith(".tsx") else language
            ts_lang = self._languages[ts_lang_key if ts_lang_key in self._languages else language]

            # Parse the source
            parser = Parser(ts_lang)
            tree = parser.parse(source)

            if tree.root_node.has_error:
                logger.warning("Parse errors in %s", file_path)

            # Delegate to language-specific parser
            symbols = self._extract_symbols(language, source, file_path)

            return {
                "language": language,
                "symbols": symbols,
                "tree": tree,
            }
        except ParsingError:
            raise
        except (ValueError, RuntimeError) as exc:
            raise ParsingError(f"Failed to parse {file_path}: {exc}") from exc

    def _extract_symbols(self, language: str, source: bytes, file_path: str) -> list[dict]:
        """Delegate symbol extraction to the correct language parser."""
        if language == "python":
            return self._python_parser.extract_symbols(source, file_path)
        elif language == "typescript":
            return self._typescript_parser.extract_symbols(source, file_path)
        elif language == "csharp":
            return self._csharp_parser.extract_symbols(source, file_path)
        elif language == "go":
            return self._go_parser.extract_symbols(source, file_path)
        return []

    def get_tree(self, source: bytes, file_path: str) -> Any:
        """Parse source and return just the tree-sitter Tree.
        Useful when you only need the AST, not symbol extraction."""
        language = self.detect_language(file_path)
        if language is None:
            raise ParsingError(f"Unsupported file extension: {Path(file_path).suffix}")

        ts_lang_key = "tsx" if file_path.endswith(".tsx") else language
        ts_lang = self._languages.get(ts_lang_key, self._languages.get(language))
        parser = Parser(ts_lang)
        return parser.parse(source)
