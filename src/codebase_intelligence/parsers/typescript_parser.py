"""TypeScript/TSX AST parser using tree-sitter 0.25.2.

Extracts symbol definitions (interfaces, types, classes, functions,
methods, exported variables) from TypeScript and TSX source files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from src.shared.models.codebase import SymbolKind

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tree-sitter query patterns for TypeScript declarations
# ---------------------------------------------------------------------------

_DECLARATION_QUERY = """
(interface_declaration
  name: (type_identifier) @iface_name) @iface_decl

(type_alias_declaration
  name: (type_identifier) @type_name) @type_decl

(class_declaration
  name: (type_identifier) @class_name) @class_decl

(function_declaration
  name: (identifier) @func_name) @func_decl

(lexical_declaration
  (variable_declarator
    name: (identifier) @var_name)) @var_decl

(method_definition
  name: (property_identifier) @method_name) @method_decl
"""


def _node_text(node: Node) -> str:
    """Return the UTF-8 text of a tree-sitter node.

    ``node.text`` returns ``bytes`` in tree-sitter 0.25, so we always
    decode before comparing or returning strings.
    """
    return node.text.decode("utf-8")


def _is_exported(node: Node) -> bool:
    """Determine whether *node* is directly exported.

    A declaration is exported when it is the immediate child of an
    ``export_statement`` node, **or** when its first child is the
    ``export`` keyword (as tree-sitter sometimes models it).
    """
    # Check parent wrapper: export_statement > declaration
    parent = node.parent
    if parent is not None and parent.type == "export_statement":
        return True

    # Rare alternate: ``export`` keyword as first child of the declaration
    for child in node.children:
        if child.type == "export" or _node_text(child) == "export":
            return True
        # Only check leading keywords; stop at the first non-keyword token
        if child.is_named:
            break

    return False


def _extract_jsdoc(node: Node) -> str | None:
    """Return the JSDoc comment immediately preceding *node*, if any.

    JSDoc comments are represented as ``comment`` nodes whose text
    starts with ``/**``.  We walk backwards through the previous
    siblings of the declaration (or its ``export_statement`` wrapper)
    looking for the closest comment.
    """
    target = node
    # If the declaration is wrapped in an export_statement, the comment
    # appears *before* the export_statement, not before the declaration.
    if target.parent is not None and target.parent.type == "export_statement":
        target = target.parent

    prev = target.prev_named_sibling
    if prev is None:
        # Also check unnamed (non-named) siblings — comments are sometimes
        # not "named" children.
        prev = target.prev_sibling

    if prev is not None and prev.type == "comment":
        text = _node_text(prev).strip()
        if text.startswith("/**"):
            # Strip the comment delimiters and leading asterisks
            return _clean_jsdoc(text)

    return None


def _clean_jsdoc(raw: str) -> str:
    """Strip JSDoc comment delimiters and leading ``*`` characters."""
    body = raw
    if body.startswith("/**"):
        body = body[3:]
    if body.endswith("*/"):
        body = body[:-2]
    lines: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("*"):
            stripped = stripped[1:].strip()
        lines.append(stripped)
    result = "\n".join(lines).strip()
    return result if result else None  # type: ignore[return-value]


def _build_signature(node: Node) -> str:
    """Build a human-readable signature string for a declaration node.

    For most declarations the first line of source text (up to ``{``) is
    a reasonable signature.  We fall back to the full first line when no
    opening brace is found.
    """
    full_text = _node_text(node)
    # Take up to the first opening brace or newline
    first_line = full_text.split("\n", 1)[0]
    brace_idx = first_line.find("{")
    if brace_idx != -1:
        sig = first_line[:brace_idx].rstrip()
    else:
        sig = first_line.rstrip()

    # Trim trailing semicolons/commas for clean display
    sig = sig.rstrip(";,")
    return sig.strip()


def _find_enclosing_class(node: Node) -> str | None:
    """Walk up the tree to find the enclosing class name, if any."""
    current = node.parent
    while current is not None:
        if current.type == "class_declaration":
            name_node = current.child_by_field_name("name")
            if name_node is not None:
                return _node_text(name_node)
        current = current.parent
    return None


def _is_meaningful_variable(node: Node) -> bool:
    """Heuristic: decide if a ``lexical_declaration`` is worth indexing.

    We keep exported const/let bindings whose initialiser looks like a
    meaningful value (arrow function, function expression, object literal,
    class expression, call expression, ``as const`` assertion, etc.).
    Trivial literals (``const x = 5``) are also kept when exported,
    since they are part of the public API.
    """
    for child in node.named_children:
        if child.type == "variable_declarator":
            value = child.child_by_field_name("value")
            if value is not None:
                return True
    return False


# ---------------------------------------------------------------------------
# Main parser class
# ---------------------------------------------------------------------------


class TypeScriptParser:
    """Extract symbol definitions from TypeScript and TSX source code.

    Uses ``tree_sitter_typescript.language_typescript()`` for ``.ts`` files
    and ``tree_sitter_typescript.language_tsx()`` for ``.tsx`` files, via
    the tree-sitter 0.25.2 ``Language`` / ``Parser`` / ``Query`` /
    ``QueryCursor`` API.
    """

    def __init__(self) -> None:
        self._ts_lang = Language(tree_sitter_typescript.language_typescript())
        self._tsx_lang = Language(tree_sitter_typescript.language_tsx())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_symbols(self, source: bytes, file_path: str) -> list[dict[str, Any]]:
        """Extract symbol definitions from TypeScript/TSX source code.

        Uses ``language_tsx()`` for ``.tsx`` files and
        ``language_typescript()`` for ``.ts`` files.

        Parameters
        ----------
        source:
            Raw bytes of the source file (UTF-8 encoded).
        file_path:
            Path to the source file.  Used to choose the appropriate
            tree-sitter language grammar.

        Returns
        -------
        list[dict]
            Each dict contains: ``name``, ``kind`` (a :class:`SymbolKind`
            value string), ``line_start``, ``line_end`` (both 1-indexed),
            ``signature``, ``docstring``, ``is_exported``, and
            ``parent_symbol``.
        """
        lang = self._language_for(file_path)
        parser = Parser(lang)
        tree = parser.parse(source)

        query = Query(lang, _DECLARATION_QUERY)
        cursor = QueryCursor(query)
        matches = cursor.matches(tree.root_node)

        symbols: list[dict[str, Any]] = []

        for _pattern_idx, captures in matches:
            self._process_match(captures, symbols)

        return symbols

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _language_for(self, file_path: str) -> Language:
        """Return the correct tree-sitter ``Language`` for *file_path*."""
        ext = Path(file_path).suffix
        if ext.lower() == ".tsx":
            return self._tsx_lang
        return self._ts_lang

    def _process_match(
        self,
        captures: dict[str, list[Node]],
        symbols: list[dict[str, Any]],
    ) -> None:
        """Translate a single query match into one or more symbol dicts."""

        # --- interface ---
        if "iface_decl" in captures:
            decl_node = captures["iface_decl"][0]
            name_node = captures["iface_name"][0]
            symbols.append(
                self._make_symbol(
                    name=_node_text(name_node),
                    kind=SymbolKind.INTERFACE,
                    decl_node=decl_node,
                )
            )

        # --- type alias ---
        elif "type_decl" in captures:
            decl_node = captures["type_decl"][0]
            name_node = captures["type_name"][0]
            symbols.append(
                self._make_symbol(
                    name=_node_text(name_node),
                    kind=SymbolKind.TYPE,
                    decl_node=decl_node,
                )
            )

        # --- class ---
        elif "class_decl" in captures:
            decl_node = captures["class_decl"][0]
            name_node = captures["class_name"][0]
            symbols.append(
                self._make_symbol(
                    name=_node_text(name_node),
                    kind=SymbolKind.CLASS,
                    decl_node=decl_node,
                )
            )

        # --- function ---
        elif "func_decl" in captures:
            decl_node = captures["func_decl"][0]
            name_node = captures["func_name"][0]
            symbols.append(
                self._make_symbol(
                    name=_node_text(name_node),
                    kind=SymbolKind.FUNCTION,
                    decl_node=decl_node,
                )
            )

        # --- lexical declaration (const / let) ---
        elif "var_decl" in captures:
            decl_node = captures["var_decl"][0]
            name_node = captures["var_name"][0]
            if not _is_meaningful_variable(decl_node):
                return
            symbols.append(
                self._make_symbol(
                    name=_node_text(name_node),
                    kind=SymbolKind.VARIABLE,
                    decl_node=decl_node,
                )
            )

        # --- method (inside class) ---
        elif "method_decl" in captures:
            decl_node = captures["method_decl"][0]
            name_node = captures["method_name"][0]
            parent_class = _find_enclosing_class(decl_node)
            symbols.append(
                self._make_symbol(
                    name=_node_text(name_node),
                    kind=SymbolKind.METHOD,
                    decl_node=decl_node,
                    parent_symbol=parent_class,
                )
            )

    @staticmethod
    def _make_symbol(
        *,
        name: str,
        kind: SymbolKind,
        decl_node: Node,
        parent_symbol: str | None = None,
    ) -> dict[str, Any]:
        """Build a normalised symbol dict from extracted AST information.

        Tree-sitter rows are 0-indexed; we add 1 to produce 1-indexed
        line numbers expected by the rest of the system.
        """
        # For exported declarations the actual span we want may be the
        # export_statement wrapper so that line numbers cover the
        # ``export`` keyword as well.
        span_node = decl_node
        if (
            decl_node.parent is not None
            and decl_node.parent.type == "export_statement"
        ):
            span_node = decl_node.parent

        return {
            "name": name,
            "kind": kind.value,
            "line_start": span_node.start_point.row + 1,
            "line_end": span_node.end_point.row + 1,
            "signature": _build_signature(span_node),
            "docstring": _extract_jsdoc(decl_node),
            "is_exported": _is_exported(decl_node),
            "parent_symbol": parent_symbol,
        }
