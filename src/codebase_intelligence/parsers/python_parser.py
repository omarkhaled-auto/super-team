"""Python-specific AST parser using tree-sitter 0.25.2.

Extracts class, function, and method symbols from Python source code
using tree-sitter Query/QueryCursor pattern matching.
"""

from __future__ import annotations

import logging
from typing import Any

import tree_sitter_python
from tree_sitter import Language, Parser, Query, QueryCursor

from src.shared.models.codebase import SymbolKind

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tree-sitter query patterns for Python
# ---------------------------------------------------------------------------

_CLASS_QUERY = "(class_definition name: (identifier) @name) @def"

_FUNCTION_QUERY = "(function_definition name: (identifier) @name) @def"

_DECORATED_QUERY = "(decorated_definition) @decorated"


class PythonParser:
    """Extract symbol definitions from Python source files.

    Uses tree-sitter 0.25.2 with ``tree_sitter_python`` to parse source code
    and identify classes, functions, and methods together with their metadata
    (signatures, docstrings, export visibility, parent relationships).
    """

    def __init__(self) -> None:
        self._lang: Language = Language(tree_sitter_python.language())
        self._parser: Parser = Parser(self._lang)

        # Pre-compile queries once at construction time.
        self._class_query: Query = Query(self._lang, _CLASS_QUERY)
        self._function_query: Query = Query(self._lang, _FUNCTION_QUERY)
        self._decorated_query: Query = Query(self._lang, _DECORATED_QUERY)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_symbols(self, source: bytes, file_path: str) -> list[dict[str, Any]]:
        """Extract symbol definitions from Python source code.

        Parameters
        ----------
        source:
            Raw source bytes of the Python file.
        file_path:
            Path of the file (used for diagnostics, not stored in the dict).

        Returns
        -------
        list[dict[str, Any]]
            Each dict contains the keys:
            ``name``, ``kind``, ``line_start``, ``line_end``, ``signature``,
            ``docstring``, ``is_exported``, ``parent_symbol``.
        """
        tree = self._parser.parse(source)
        root = tree.root_node

        symbols: list[dict[str, Any]] = []
        # Track which AST byte ranges have already been processed so that
        # decorated definitions and their inner definitions are not
        # double-counted.  We key on (start_byte, end_byte) because
        # tree-sitter Node Python object identity (id()) is NOT stable
        # across separate Query executions.
        seen_ranges: set[tuple[int, int]] = set()

        # 1. Handle decorated definitions first so we can mark the inner node
        #    as seen and avoid duplicates.
        self._extract_decorated(root, symbols, seen_ranges)

        # 2. Standalone (non-decorated) class definitions.
        self._extract_classes(root, symbols, seen_ranges)

        # 3. Standalone (non-decorated) function/method definitions.
        self._extract_functions(root, symbols, seen_ranges)

        return symbols

    # ------------------------------------------------------------------
    # Internal helpers -- decorated definitions
    # ------------------------------------------------------------------

    def _extract_decorated(
        self,
        root: Any,
        symbols: list[dict[str, Any]],
        seen_ranges: set[tuple[int, int]],
    ) -> None:
        """Process ``decorated_definition`` nodes.

        A decorated definition wraps either a ``class_definition`` or a
        ``function_definition``.  We unwrap the inner node and delegate to
        the appropriate handler while recording the *outer* decorated node
        span for accurate line numbers.
        """
        cursor = QueryCursor(self._decorated_query)
        for _pattern_idx, captures in cursor.matches(root):
            decorated_nodes = captures.get("decorated", [])
            if not decorated_nodes:
                continue
            decorated_node = decorated_nodes[0]

            # Find the inner class_definition or function_definition.
            inner_node = self._unwrap_decorated(decorated_node)
            if inner_node is None:
                continue

            # Mark both the decorated wrapper *and* the inner node as seen.
            seen_ranges.add((decorated_node.start_byte, decorated_node.end_byte))
            seen_ranges.add((inner_node.start_byte, inner_node.end_byte))

            inner_type: str = inner_node.type

            if inner_type == "class_definition":
                symbol = self._build_class_symbol(inner_node, decorated_node)
                symbols.append(symbol)
                # Also extract methods defined inside this class.
                self._extract_class_methods(inner_node, symbols, seen_ranges)

            elif inner_type == "function_definition":
                parent_class = self._find_enclosing_class(decorated_node)
                symbol = self._build_function_symbol(
                    inner_node, decorated_node, parent_class
                )
                symbols.append(symbol)

    # ------------------------------------------------------------------
    # Internal helpers -- classes
    # ------------------------------------------------------------------

    def _extract_classes(
        self,
        root: Any,
        symbols: list[dict[str, Any]],
        seen_ranges: set[tuple[int, int]],
    ) -> None:
        """Extract non-decorated class definitions from the AST."""
        cursor = QueryCursor(self._class_query)
        for _pattern_idx, captures in cursor.matches(root):
            def_nodes = captures.get("def", [])
            if not def_nodes:
                continue
            class_node = def_nodes[0]

            if (class_node.start_byte, class_node.end_byte) in seen_ranges:
                continue
            seen_ranges.add((class_node.start_byte, class_node.end_byte))

            symbol = self._build_class_symbol(class_node, class_node)
            symbols.append(symbol)

            # Extract methods inside this class.
            self._extract_class_methods(class_node, symbols, seen_ranges)

    def _extract_class_methods(
        self,
        class_node: Any,
        symbols: list[dict[str, Any]],
        seen_ranges: set[tuple[int, int]],
    ) -> None:
        """Extract function definitions directly inside a class body."""
        class_name = self._node_name(class_node)
        body_node = class_node.child_by_field_name("body")
        if body_node is None:
            return

        for child in body_node.named_children:
            # Handle decorated methods inside a class.
            if child.type == "decorated_definition":
                inner = self._unwrap_decorated(child)
                if inner is not None and inner.type == "function_definition":
                    if (child.start_byte, child.end_byte) not in seen_ranges and (inner.start_byte, inner.end_byte) not in seen_ranges:
                        seen_ranges.add((child.start_byte, child.end_byte))
                        seen_ranges.add((inner.start_byte, inner.end_byte))
                        symbol = self._build_function_symbol(inner, child, class_name)
                        symbols.append(symbol)

            elif child.type == "function_definition":
                if (child.start_byte, child.end_byte) not in seen_ranges:
                    seen_ranges.add((child.start_byte, child.end_byte))
                    symbol = self._build_function_symbol(child, child, class_name)
                    symbols.append(symbol)

    # ------------------------------------------------------------------
    # Internal helpers -- functions
    # ------------------------------------------------------------------

    def _extract_functions(
        self,
        root: Any,
        symbols: list[dict[str, Any]],
        seen_ranges: set[tuple[int, int]],
    ) -> None:
        """Extract non-decorated, non-method function definitions."""
        cursor = QueryCursor(self._function_query)
        for _pattern_idx, captures in cursor.matches(root):
            def_nodes = captures.get("def", [])
            if not def_nodes:
                continue
            func_node = def_nodes[0]

            if (func_node.start_byte, func_node.end_byte) in seen_ranges:
                continue
            seen_ranges.add((func_node.start_byte, func_node.end_byte))

            parent_class = self._find_enclosing_class(func_node)
            symbol = self._build_function_symbol(func_node, func_node, parent_class)
            symbols.append(symbol)

    # ------------------------------------------------------------------
    # Symbol builders
    # ------------------------------------------------------------------

    def _build_class_symbol(
        self, class_node: Any, span_node: Any
    ) -> dict[str, Any]:
        """Build a symbol dict for a class definition.

        Parameters
        ----------
        class_node:
            The ``class_definition`` tree-sitter node.
        span_node:
            The outermost node whose span determines ``line_start``/``line_end``
            (may be the same as *class_node* or its ``decorated_definition``
            wrapper).
        """
        name = self._node_name(class_node)
        return {
            "name": name,
            "kind": SymbolKind.CLASS,
            "line_start": span_node.start_point.row + 1,
            "line_end": span_node.end_point.row + 1,
            "signature": self._class_signature(class_node),
            "docstring": self._extract_docstring(class_node),
            "is_exported": not name.startswith("_"),
            "parent_symbol": None,
        }

    def _build_function_symbol(
        self,
        func_node: Any,
        span_node: Any,
        parent_class: str | None,
    ) -> dict[str, Any]:
        """Build a symbol dict for a function or method definition.

        Parameters
        ----------
        func_node:
            The ``function_definition`` tree-sitter node.
        span_node:
            The outermost node whose span determines line numbers (may be a
            ``decorated_definition`` wrapper).
        parent_class:
            Name of the enclosing class if this is a method, otherwise ``None``.
        """
        name = self._node_name(func_node)
        kind = SymbolKind.METHOD if parent_class else SymbolKind.FUNCTION
        return {
            "name": name,
            "kind": kind,
            "line_start": span_node.start_point.row + 1,
            "line_end": span_node.end_point.row + 1,
            "signature": self._function_signature(func_node),
            "docstring": self._extract_docstring(func_node),
            "is_exported": not name.startswith("_"),
            "parent_symbol": parent_class,
        }

    # ------------------------------------------------------------------
    # AST utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _node_name(node: Any) -> str:
        """Return the ``name`` field of a definition node as a string."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return "<unknown>"
        return name_node.text.decode()

    @staticmethod
    def _unwrap_decorated(decorated_node: Any) -> Any | None:
        """Return the inner ``class_definition`` or ``function_definition``
        from a ``decorated_definition`` node, or ``None`` if not found."""
        for child in decorated_node.named_children:
            if child.type in ("class_definition", "function_definition"):
                return child
        return None

    @staticmethod
    def _find_enclosing_class(node: Any) -> str | None:
        """Walk up the tree to find the nearest enclosing class name.

        Returns ``None`` when the node is at module level.
        """
        current = node.parent
        while current is not None:
            if current.type == "class_definition":
                name_node = current.child_by_field_name("name")
                if name_node is not None:
                    return name_node.text.decode()
            current = current.parent
        return None

    @staticmethod
    def _function_signature(func_node: Any) -> str:
        """Build a human-readable signature string for a function.

        Example output: ``def my_func(self, x: int, y: str) -> bool``
        """
        name = func_node.child_by_field_name("name")
        params = func_node.child_by_field_name("parameters")
        return_type = func_node.child_by_field_name("return_type")

        name_text = name.text.decode() if name else "<unknown>"
        params_text = params.text.decode() if params else "()"
        sig = f"def {name_text}{params_text}"

        if return_type is not None:
            sig += f" -> {return_type.text.decode()}"

        return sig

    @staticmethod
    def _class_signature(class_node: Any) -> str:
        """Build a human-readable signature string for a class.

        Example output: ``class MyClass(BaseModel, Mixin)``
        """
        name = class_node.child_by_field_name("name")
        name_text = name.text.decode() if name else "<unknown>"

        # Superclasses are held in the ``superclasses`` field (an
        # ``argument_list`` node) when present.
        superclasses = class_node.child_by_field_name("superclasses")
        if superclasses is not None:
            return f"class {name_text}{superclasses.text.decode()}"
        return f"class {name_text}"

    @staticmethod
    def _extract_docstring(def_node: Any) -> str | None:
        """Return the docstring of a class or function definition, if any.

        A docstring is defined as the first ``expression_statement`` in the
        body whose child is a ``string`` node.
        """
        body = def_node.child_by_field_name("body")
        if body is None:
            return None

        for child in body.named_children:
            if child.type == "expression_statement":
                for sub in child.named_children:
                    if sub.type == "string":
                        raw = sub.text.decode()
                        # Strip surrounding triple-quotes (''' or \"\"\")
                        # and single quotes/double quotes.
                        return PythonParser._strip_quotes(raw)
            # The docstring must be the *first* statement; stop after the
            # first non-expression child.
            break

        return None

    @staticmethod
    def _strip_quotes(raw: str) -> str:
        """Remove surrounding quote characters from a raw string literal."""
        for prefix in ('"""', "'''"):
            if raw.startswith(prefix) and raw.endswith(prefix):
                return raw[3:-3].strip()
        for prefix in ('"', "'"):
            if raw.startswith(prefix) and raw.endswith(prefix):
                return raw[1:-1].strip()
        return raw
