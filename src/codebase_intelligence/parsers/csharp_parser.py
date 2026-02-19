"""Tree-sitter based parser for C# source files.

Extracts symbol definitions (classes, interfaces, methods, enums, structs)
from C# code using tree-sitter 0.25.2.
"""

from __future__ import annotations

from typing import Any

import tree_sitter_c_sharp
from tree_sitter import Language, Parser, Query, QueryCursor

from src.shared.models.codebase import SymbolKind


class CSharpParser:
    """Parser for C# source code using tree-sitter.

    Extracts class, interface, method, enum, and struct declarations.
    Namespace declarations are used for service_name inference but are
    not emitted as standalone symbols.
    """

    # Tree-sitter query patterns for each C# declaration type.
    _CLASS_QUERY = "(class_declaration name: (identifier) @name) @def"
    _INTERFACE_QUERY = "(interface_declaration name: (identifier) @name) @def"
    _METHOD_QUERY = "(method_declaration name: (identifier) @name) @def"
    _ENUM_QUERY = "(enum_declaration name: (identifier) @name) @def"
    _STRUCT_QUERY = "(struct_declaration name: (identifier) @name) @def"
    _NAMESPACE_QUERY = "(namespace_declaration name: (_) @name) @def"

    def __init__(self) -> None:
        self._lang = Language(tree_sitter_c_sharp.language())
        self._parser = Parser(self._lang)

        # Pre-compile queries for reuse.
        self._class_q = Query(self._lang, self._CLASS_QUERY)
        self._interface_q = Query(self._lang, self._INTERFACE_QUERY)
        self._method_q = Query(self._lang, self._METHOD_QUERY)
        self._enum_q = Query(self._lang, self._ENUM_QUERY)
        self._struct_q = Query(self._lang, self._STRUCT_QUERY)
        self._namespace_q = Query(self._lang, self._NAMESPACE_QUERY)

    def extract_symbols(self, source: bytes, file_path: str) -> list[dict[str, Any]]:
        """Extract symbol definitions from C# source code.

        Args:
            source: Raw bytes of the C# source file.
            file_path: Path to the source file (used for identification).

        Returns:
            A list of dicts, each containing:
                - name: Symbol name.
                - kind: A ``SymbolKind`` value.
                - line_start: 1-indexed start line.
                - line_end: 1-indexed end line.
                - signature: The first line of the declaration.
                - docstring: XML doc comment (``///``) preceding the symbol, or None.
                - is_exported: Whether the symbol has ``public`` visibility.
                - parent_symbol: Enclosing class/struct name for methods, or None.
        """
        tree = self._parser.parse(source)
        root = tree.root_node

        symbols: list[dict[str, Any]] = []

        # --- Collect namespace context for service_name inference ---
        namespaces = self._extract_namespaces(root)

        # --- Classes ---
        for node, name in self._run_query(self._class_q, root):
            symbols.append(self._build_symbol(
                name=name,
                kind=SymbolKind.CLASS,
                node=node,
                source=source,
                is_exported=self._has_public_modifier(node),
                parent_symbol=None,
            ))

        # --- Interfaces ---
        for node, name in self._run_query(self._interface_q, root):
            symbols.append(self._build_symbol(
                name=name,
                kind=SymbolKind.INTERFACE,
                node=node,
                source=source,
                is_exported=self._has_public_modifier(node),
                parent_symbol=None,
            ))

        # --- Enums ---
        for node, name in self._run_query(self._enum_q, root):
            symbols.append(self._build_symbol(
                name=name,
                kind=SymbolKind.ENUM,
                node=node,
                source=source,
                is_exported=self._has_public_modifier(node),
                parent_symbol=None,
            ))

        # --- Structs (treated as classes) ---
        for node, name in self._run_query(self._struct_q, root):
            symbols.append(self._build_symbol(
                name=name,
                kind=SymbolKind.CLASS,
                node=node,
                source=source,
                is_exported=self._has_public_modifier(node),
                parent_symbol=None,
            ))

        # --- Methods (with parent class/struct context) ---
        for node, name in self._run_query(self._method_q, root):
            parent_name = self._find_enclosing_type(node)
            parent_exported = self._is_parent_exported(node)
            symbols.append(self._build_symbol(
                name=name,
                kind=SymbolKind.METHOD,
                node=node,
                source=source,
                is_exported=parent_exported and self._has_public_modifier(node),
                parent_symbol=parent_name,
            ))

        # Attach namespace-based service_name to all symbols.
        service_name = self._infer_service_name(namespaces)
        if service_name:
            for sym in symbols:
                sym["service_name"] = service_name

        return symbols

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_query(self, query: Query, root_node: Any) -> list[tuple[Any, str]]:
        """Execute a tree-sitter query and yield (definition_node, name_string) pairs.

        ``QueryCursor.matches()`` returns ``(pattern_idx, captures_dict)`` where
        each capture value is a list of nodes.
        """
        cursor = QueryCursor(query)
        results: list[tuple[Any, str]] = []
        for _pattern_idx, captures in cursor.matches(root_node):
            def_nodes = captures.get("def", [])
            name_nodes = captures.get("name", [])
            if def_nodes and name_nodes:
                def_node = def_nodes[0]
                name_text = name_nodes[0].text.decode()
                results.append((def_node, name_text))
        return results

    def _build_symbol(
        self,
        *,
        name: str,
        kind: SymbolKind,
        node: Any,
        source: bytes,
        is_exported: bool,
        parent_symbol: str | None,
    ) -> dict[str, Any]:
        """Construct a symbol dictionary from a tree-sitter node."""
        return {
            "name": name,
            "kind": kind,
            "line_start": node.start_point[0] + 1,
            "line_end": node.end_point[0] + 1,
            "signature": self._extract_signature(node, source),
            "docstring": self._extract_xml_docstring(node, source),
            "is_exported": is_exported,
            "parent_symbol": parent_symbol,
        }

    @staticmethod
    def _extract_signature(node: Any, source: bytes) -> str:
        """Return the first line of the declaration as the signature."""
        node_text = node.text.decode()
        first_line = node_text.split("\n", 1)[0].strip()
        return first_line

    @staticmethod
    def _extract_xml_docstring(node: Any, source: bytes) -> str | None:
        """Extract XML documentation comments (``///``) preceding a declaration.

        Walks backwards through previous siblings to collect consecutive
        ``comment`` nodes that start with ``///``.
        """
        doc_lines: list[str] = []
        sibling = node.prev_named_sibling

        while sibling is not None and sibling.type == "comment":
            text = sibling.text.decode().strip()
            if text.startswith("///"):
                doc_lines.append(text)
                sibling = sibling.prev_named_sibling
            else:
                break

        if not doc_lines:
            return None

        # Lines were collected in reverse order; restore original order.
        doc_lines.reverse()
        return "\n".join(doc_lines)

    @staticmethod
    def _has_public_modifier(node: Any) -> bool:
        """Check whether a declaration node has a ``public`` modifier."""
        for child in node.children:
            if child.type == "modifier" and child.text.decode() == "public":
                return True
        return False

    @staticmethod
    def _find_enclosing_type(node: Any) -> str | None:
        """Walk up the tree to find the nearest enclosing class or struct name."""
        current = node.parent
        while current is not None:
            if current.type in ("class_declaration", "struct_declaration"):
                for child in current.children:
                    if child.type == "identifier":
                        return child.text.decode()
            current = current.parent
        return None

    @staticmethod
    def _is_parent_exported(node: Any) -> bool:
        """Check whether the enclosing class/struct is public."""
        current = node.parent
        while current is not None:
            if current.type in ("class_declaration", "struct_declaration"):
                for child in current.children:
                    if child.type == "modifier" and child.text.decode() == "public":
                        return True
                return False
            current = current.parent
        return False

    def _extract_namespaces(self, root_node: Any) -> list[str]:
        """Extract namespace names from the tree for service_name inference."""
        namespaces: list[str] = []
        for _pattern_idx, captures in QueryCursor(self._namespace_q).matches(root_node):
            name_nodes = captures.get("name", [])
            if name_nodes:
                namespaces.append(name_nodes[0].text.decode())
        return namespaces

    @staticmethod
    def _infer_service_name(namespaces: list[str]) -> str | None:
        """Infer a service name from collected namespace declarations.

        Uses the first namespace found. If the namespace is dotted
        (e.g. ``MyCompany.OrderService.Models``), takes the second segment
        as the service name. Otherwise uses the full namespace.
        """
        if not namespaces:
            return None
        ns = namespaces[0]
        parts = ns.split(".")
        if len(parts) >= 2:
            return parts[1]
        return parts[0]
