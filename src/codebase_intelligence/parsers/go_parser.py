"""Tree-sitter based parser for Go source files.

Extracts symbol definitions (functions, methods, types) from Go code
using tree-sitter 0.25.2.
"""

from __future__ import annotations

from typing import Any

import tree_sitter_go
from tree_sitter import Language, Parser, Query, QueryCursor

from src.shared.models.codebase import SymbolKind


class GoParser:
    """Parser for Go source code using tree-sitter.

    Extracts function declarations, method declarations (with receiver
    type as parent_symbol), and type declarations (structs as ``class``,
    interfaces as ``interface``).
    """

    # Tree-sitter query patterns for Go declarations.
    _FUNCTION_QUERY = "(function_declaration name: (identifier) @name) @def"
    _METHOD_QUERY = "(method_declaration name: (field_identifier) @name) @def"
    _TYPE_QUERY = "(type_declaration (type_spec name: (type_identifier) @name)) @def"

    def __init__(self) -> None:
        self._lang = Language(tree_sitter_go.language())
        self._parser = Parser(self._lang)

        # Pre-compile queries for reuse.
        self._function_q = Query(self._lang, self._FUNCTION_QUERY)
        self._method_q = Query(self._lang, self._METHOD_QUERY)
        self._type_q = Query(self._lang, self._TYPE_QUERY)

    def extract_symbols(self, source: bytes, file_path: str) -> list[dict[str, Any]]:
        """Extract symbol definitions from Go source code.

        Args:
            source: Raw bytes of the Go source file.
            file_path: Path to the source file (used for identification).

        Returns:
            A list of dicts, each containing:
                - name: Symbol name.
                - kind: A ``SymbolKind`` value.
                - line_start: 1-indexed start line.
                - line_end: 1-indexed end line.
                - signature: The first line of the declaration.
                - docstring: Go doc comment preceding the symbol, or None.
                - is_exported: Whether the symbol name starts with an uppercase letter.
                - parent_symbol: Receiver type for methods, or None.
        """
        tree = self._parser.parse(source)
        root = tree.root_node

        symbols: list[dict[str, Any]] = []

        # --- Functions ---
        for node, name in self._run_query(self._function_q, root):
            symbols.append(self._build_symbol(
                name=name,
                kind=SymbolKind.FUNCTION,
                node=node,
                source=source,
                parent_symbol=None,
            ))

        # --- Methods (with receiver type as parent_symbol) ---
        for node, name in self._run_query(self._method_q, root):
            receiver = self._extract_receiver_type(node)
            symbols.append(self._build_symbol(
                name=name,
                kind=SymbolKind.METHOD,
                node=node,
                source=source,
                parent_symbol=receiver,
            ))

        # --- Type declarations (structs and interfaces) ---
        for def_node, type_spec_name, kind in self._extract_type_declarations(root):
            symbols.append(self._build_symbol(
                name=type_spec_name,
                kind=kind,
                node=def_node,
                source=source,
                parent_symbol=None,
            ))

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

    def _extract_type_declarations(
        self, root_node: Any
    ) -> list[tuple[Any, str, SymbolKind]]:
        """Extract type declarations, classifying them as struct or interface.

        For each ``type_declaration`` match, inspects the underlying ``type_spec``
        to determine whether the type body is a ``struct_type`` (emitted as
        ``SymbolKind.CLASS``) or ``interface_type`` (emitted as
        ``SymbolKind.INTERFACE``). Any other type alias or definition falls
        back to ``SymbolKind.TYPE``.

        Returns:
            List of (type_declaration_node, name, kind) tuples.
        """
        cursor = QueryCursor(self._type_q)
        results: list[tuple[Any, str, SymbolKind]] = []

        for _pattern_idx, captures in cursor.matches(root_node):
            def_nodes = captures.get("def", [])
            name_nodes = captures.get("name", [])
            if not def_nodes or not name_nodes:
                continue

            def_node = def_nodes[0]
            name_text = name_nodes[0].text.decode()

            # Determine the kind by inspecting the type_spec's type body.
            kind = self._classify_type_spec(def_node)
            results.append((def_node, name_text, kind))

        return results

    @staticmethod
    def _classify_type_spec(type_decl_node: Any) -> SymbolKind:
        """Classify a type_declaration node as struct, interface, or generic type.

        Walks into the ``type_spec`` child to find a ``struct_type`` or
        ``interface_type`` node.
        """
        for child in type_decl_node.children:
            if child.type == "type_spec":
                for spec_child in child.children:
                    if spec_child.type == "struct_type":
                        return SymbolKind.CLASS
                    if spec_child.type == "interface_type":
                        return SymbolKind.INTERFACE
        return SymbolKind.TYPE

    def _build_symbol(
        self,
        *,
        name: str,
        kind: SymbolKind,
        node: Any,
        source: bytes,
        parent_symbol: str | None,
    ) -> dict[str, Any]:
        """Construct a symbol dictionary from a tree-sitter node."""
        return {
            "name": name,
            "kind": kind,
            "line_start": node.start_point[0] + 1,
            "line_end": node.end_point[0] + 1,
            "signature": self._extract_signature(node),
            "docstring": self._extract_go_docstring(node, source),
            "is_exported": name[0].isupper() if name else False,
            "parent_symbol": parent_symbol,
        }

    @staticmethod
    def _extract_signature(node: Any) -> str:
        """Return the first line of the declaration as the signature."""
        node_text = node.text.decode()
        first_line = node_text.split("\n", 1)[0].strip()
        return first_line

    @staticmethod
    def _extract_go_docstring(node: Any, source: bytes) -> str | None:
        """Extract Go doc comments preceding a declaration.

        Go documentation comments are contiguous ``//`` line comments or a
        single ``/* ... */`` block comment immediately before the declaration.
        """
        doc_lines: list[str] = []
        sibling = node.prev_named_sibling

        while sibling is not None and sibling.type == "comment":
            text = sibling.text.decode().strip()
            if text.startswith("//"):
                doc_lines.append(text)
                sibling = sibling.prev_named_sibling
            elif text.startswith("/*"):
                doc_lines.append(text)
                # Block comments are single units; stop after one.
                break
            else:
                break

        if not doc_lines:
            return None

        # Lines collected in reverse order; restore original order.
        doc_lines.reverse()
        return "\n".join(doc_lines)

    @staticmethod
    def _extract_receiver_type(method_node: Any) -> str | None:
        """Extract the receiver type name from a method_declaration.

        A Go method declaration has the form::

            func (r *ReceiverType) MethodName(...) ...

        The receiver is inside a ``parameter_list`` node that appears before
        the method name.  We look for a ``type_identifier`` within the
        receiver parameter list, stripping any pointer (``*``) prefix.
        """
        for child in method_node.children:
            if child.type == "parameter_list":
                # This is the receiver parameter list (first parameter_list
                # before the method name).
                return GoParser._find_type_identifier(child)
        return None

    @staticmethod
    def _find_type_identifier(param_list_node: Any) -> str | None:
        """Recursively search a parameter list node for a type_identifier.

        Handles both value receivers ``(r ReceiverType)`` and pointer
        receivers ``(r *ReceiverType)`` by descending through
        ``pointer_type`` nodes.
        """
        for child in param_list_node.children:
            if child.type == "type_identifier":
                return child.text.decode()
            if child.type == "pointer_type":
                for ptr_child in child.children:
                    if ptr_child.type == "type_identifier":
                        return ptr_child.text.decode()
            # Recurse into parameter_declaration nodes.
            if child.type == "parameter_declaration":
                result = GoParser._find_type_identifier(child)
                if result is not None:
                    return result
        return None
